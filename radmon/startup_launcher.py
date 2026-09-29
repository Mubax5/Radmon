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

    def _scheduled_task_result(self) -> str:
        """Return the task's last result when Task Scheduler permits inspection."""
        if os.name != "nt":
            return "unavailable"
        kwargs = {"capture_output": True, "text": True, "timeout": 5, "check": False}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", "RadMon Server", "/V", "/FO", "LIST"],
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError):
            return "unavailable"
        if result.returncode != 0:
            return "unavailable"
        for line in (result.stdout or "").splitlines():
            label, separator, value = line.partition(":")
            if separator and label.strip().casefold() in {"last run result", "last run result:"}:
                return value.strip() or "unknown"
        return "unknown"

    def _lock_holder(self) -> str:
        """Describe a runtime lock holder without treating the file as authority."""
        lock_file = self.paths.runtime_dir / "instance.lock"
        try:
            pid = int(lock_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return "no readable lock"
        if pid <= 0:
            return "invalid lock PID"
        try:
            os.kill(pid, 0)
        except PermissionError:
            return f"lock PID {pid} present; managed start will use single-instance recovery"
        except OSError:
            return f"stale lock PID {pid}"
        return f"lock PID {pid} present; managed start will use single-instance recovery"

    def _start_managed_server(self) -> object:
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--server"]
        else:
            command = [sys.executable, "-m", "radmon", "--server"]
        return self._spawn_managed_process(command, self.paths)

    @staticmethod
    def _spawn_managed_process(command: list[str], paths: ApplicationPaths) -> subprocess.Popen:
        """Start a managed child independently, retaining its output in runtime logs."""
        paths.log_dir.mkdir(parents=True, exist_ok=True)
        paths.app_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = paths.log_dir / "managed-server.stdout.log"
        stderr_path = paths.log_dir / "managed-server.stderr.log"
        stdout_log = stdout_path.open("ab")
        stderr_log = stderr_path.open("ab")
        kwargs: dict = {
            "cwd": str(paths.app_dir),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_log,
            "stderr": stderr_log,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
            )
        else:
            kwargs["start_new_session"] = True
        try:
            return subprocess.Popen(command, **kwargs)
        except Exception:
            stdout_log.close()
            stderr_log.close()
            raise

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
            task_started = False
            try:
                task_started = self.run_task()
            except Exception:
                task_error = "trigger raised an exception"
            else:
                task_error = ""

            deadline = time.monotonic() + self.timeout

            def wait_until_deadline(wait_deadline: float) -> bool:
                while True:
                    if self.http_probe(self.central_url):
                        return True
                    remaining = wait_deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self.sleeper(min(self.poll_interval, remaining))

            # Leave half the bounded recovery window for managed startup when the
            # task trigger is accepted but its process never becomes healthy.
            task_deadline = time.monotonic() + max(0.0, self.timeout / 2)
            central_ok = wait_until_deadline(min(task_deadline, deadline)) if task_started else False
            task_result = ""
            if not central_ok and task_started:
                task_result = self._scheduled_task_result()

            if not central_ok:
                # Re-probe immediately before fallback. A scheduled task may have
                # started late; if so, reuse it instead of launching another.
                central_ok = self.http_probe(self.central_url)
            if not central_ok:
                started_by = "proses RadMon terkelola (fallback)"
                lock_detail = self._lock_holder()
                try:
                    self.start_process()
                except Exception as exc:
                    task_detail = f"Scheduled Task failed (last result: {task_result or 'not started'}{'; ' + task_error if task_error else ''})"
                    states.append(ComponentState("Central/API", "gagal memulai", f"{task_detail}; fallback failed: {exc}; {lock_detail}"))
                    central_ok = False
                else:
                    central_ok = wait_until_deadline(deadline)
                    if not central_ok:
                        task_detail = f"Scheduled Task {'trigger accepted' if task_started else 'unavailable'} (last result: {task_result or 'unavailable'})"
                        states.append(ComponentState("Central/API", "timeout", f"{task_detail}; {started_by} did not become healthy within {self.timeout:g} seconds; {lock_detail}"))
            elif task_started:
                started_by = "Scheduled Task"
            if central_ok:
                started_central = True
                detail = started_by
                if task_started and started_by != "Scheduled Task":
                    detail += f" after Scheduled Task did not become healthy (last result: {task_result or 'unavailable'})"
                states.append(ComponentState("Central/API", "dimulai", detail))

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
