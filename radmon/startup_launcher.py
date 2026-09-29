"""Idempotent operator entry point for recovering the RadMon local stack."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

from .config import Settings
from .grafana_persistent import PersistentGrafanaBootstrap
from .paths import ApplicationPaths


@dataclass
class ComponentState:
    name: str
    status: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.name}: {self.status}" + (f" ({self.detail})" if self.detail else "")


class RadMonLauncher:
    """Probe before starting; a successful probe always suppresses a new start."""

    def __init__(
        self,
        settings: Settings,
        paths: ApplicationPaths,
        *,
        tcp_probe: Callable[[str, int], bool] | None = None,
        http_probe: Callable[[str], bool] | None = None,
        run_task: Callable[[], bool] | None = None,
        start_process: Callable[[], object] | None = None,
        ensure_grafana: Callable[[], object] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        timeout: float = 90.0,
        poll_interval: float = 1.0,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self.tcp_probe = tcp_probe or self._tcp_probe
        self.http_probe = http_probe or self._http_probe
        self.run_task = run_task or self._run_scheduled_task
        self.start_process = start_process or self._start_managed_server
        self.ensure_grafana = ensure_grafana or self._ensure_grafana
        self.sleeper = sleeper
        self.timeout = max(0.0, timeout)
        self.poll_interval = max(0.01, poll_interval)

    @staticmethod
    def _tcp_probe(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=0.4):
                return True
        except OSError:
            return False

    @staticmethod
    def _http_probe(url: str) -> bool:
        try:
            with urlopen(url, timeout=1.0) as response:
                return 200 <= response.status < 400
        except (OSError, URLError, ValueError):
            return False

    @property
    def central_url(self) -> str:
        return "http://127.0.0.1:8090/health"

    @property
    def grafana_health_urls(self) -> list[str]:
        from urllib.parse import urlsplit

        configured = urlsplit(self.settings.grafana_url)
        urls = [f"{configured.scheme or 'http'}://{configured.netloc}/api/health"] if configured.netloc else []
        for port in (self.settings.grafana_fallback_port, 3000):
            url = f"http://127.0.0.1:{port}/api/health"
            if url not in urls:
                urls.append(url)
        return urls

    def _grafana_url(self) -> str | None:
        return next((url for url in self.grafana_health_urls if self.http_probe(url)), None)

    def _run_scheduled_task(self) -> bool:
        if os.name != "nt":
            return False
        kwargs = {"capture_output": True, "text": True, "timeout": 10, "check": False}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        query = subprocess.run(["schtasks.exe", "/Query", "/TN", "RadMon Server"], **kwargs)
        if query.returncode != 0:
            return False
        launched = subprocess.run(["schtasks.exe", "/Run", "/TN", "RadMon Server"], **kwargs)
        return launched.returncode == 0

    def _start_managed_server(self) -> object:
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--server"]
        else:
            command = [sys.executable, "-m", "radmon", "--server"]
        kwargs: dict = {"cwd": str(self.paths.install_root), "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                        "close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        return subprocess.Popen(command, **kwargs)

    def _ensure_grafana(self) -> object:
        return PersistentGrafanaBootstrap(self.settings, project_root=self.paths.app_dir).ensure()

    def _wait_for(self, predicate: Callable[[], bool]) -> bool:
        deadline = time.monotonic() + self.timeout
        while True:
            if predicate():
                return True
            if time.monotonic() >= deadline:
                return False
            self.sleeper(min(self.poll_interval, max(0.0, deadline - time.monotonic())))

    def start(self) -> list[ComponentState]:
        states: list[ComponentState] = []
        started_central = False
        db_ok = self.tcp_probe(self.settings.db_host, self.settings.db_port)
        states.append(ComponentState("MariaDB", "siap" if db_ok else "tidak tersedia", f"{self.settings.db_host}:{self.settings.db_port}"))

        central_ok = self.http_probe(self.central_url)
        if central_ok:
            states.append(ComponentState("Central/API", "sudah berjalan"))
        else:
            started_by = "Scheduled Task"
            try:
                task_started = self.run_task()
            except Exception:
                task_started = False
            if not task_started:
                started_by = "proses RadMon terkelola"
                try:
                    self.start_process()
                except Exception as exc:
                    states.append(ComponentState("Central/API", "gagal memulai", str(exc)))
                    central_ok = False
                else:
                    central_ok = self._wait_for(lambda: self.http_probe(self.central_url))
                    if not central_ok:
                        states.append(ComponentState("Central/API", "timeout", f"{started_by}; {self.timeout:g} detik"))
            else:
                central_ok = self._wait_for(lambda: self.http_probe(self.central_url))
                if not central_ok:
                    states.append(ComponentState("Central/API", "timeout", f"{started_by}; {self.timeout:g} detik"))
            if central_ok:
                started_central = True
                states.append(ComponentState("Central/API", "dimulai", started_by))

        grafana = self._grafana_url()
        if grafana:
            states.append(ComponentState("Grafana", "sudah berjalan", grafana))
        elif central_ok:
            if started_central:
                # The server process/task owns Grafana bootstrap. Wait for that
                # owner instead of racing it with a second Grafana start.
                ready = self._wait_for(lambda: self._grafana_url() is not None)
                grafana = self._grafana_url() if ready else None
                states.append(ComponentState("Grafana", "siap" if grafana else "timeout", grafana or f"{self.timeout:g} detik"))
            else:
                try:
                    self.ensure_grafana()
                except Exception as exc:
                    states.append(ComponentState("Grafana", "gagal memulai", str(exc)))
                else:
                    grafana = self._grafana_url()
                    states.append(ComponentState("Grafana", "siap" if grafana else "timeout", grafana or f"{self.timeout:g} detik"))
        else:
            states.append(ComponentState("Grafana", "belum diperiksa; Central/API belum siap"))

        if not any(state.name == "Central/API" for state in states):
            states.append(ComponentState("Central/API", "tidak tersedia"))
        return states


def show_startup_report(states: list[ComponentState], *, mode: str = "admin") -> None:
    """Report state to operators and open the best available interface."""
    import webbrowser

    central_ready = any(s.name == "Central/API" and s.status in {"sudah berjalan", "dimulai"} for s in states)
    grafana_ready = any(s.name == "Grafana" and s.status in {"sudah berjalan", "siap"} for s in states)
    target = "http://127.0.0.1:8090/app" if mode == "admin" else "http://127.0.0.1:8090/"
    if central_ready:
        webbrowser.open(target)
    elif grafana_ready:
        url = next((s.detail for s in states if s.name == "Grafana" and s.detail.startswith("http")), None)
        if url:
            webbrowser.open(url.replace("/api/health", "/"))
    report = "RadMon - Status pemulihan\n\n" + "\n".join(str(state) for state in states)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, report, "RadMon", 0x40 | 0x1000)
    except (AttributeError, OSError):
        print(report)


def run_start(mode: str = "admin") -> int:
    paths = ApplicationPaths.discover()
    for folder in (paths.config_dir, paths.runtime_dir, paths.archive_dir, paths.report_dir, paths.log_dir):
        folder.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(paths.env_file).for_application_paths(paths)
    states = RadMonLauncher(settings, paths).start()
    show_startup_report(states, mode=mode)
    return 0 if any(s.name == "Central/API" and s.status in {"sudah berjalan", "dimulai"} for s in states) else 1
