from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import Settings
from .grafana_tv import (
    PAGE_UIDS,
    PLAYLIST_UID,
    build_dashboard_payloads,
    build_playlist_payload,
    playlist_url,
)


DASHBOARD_UID = PAGE_UIDS[0]
DASHBOARD_SLUG = "radmon-tv-page-1-realtime"
DATASOURCE_UID = "ipradmon-mysql"


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid Grafana URL: {value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def dashboard_url(base_url: str) -> str:
    """Compatibility URL for the first TV page."""
    return (
        f"{base_url.rstrip('/')}/d/{DASHBOARD_UID}/{DASHBOARD_SLUG}"
        "?orgId=1&refresh=2s&kiosk=1&autofitpanels"
    )


class GrafanaBootstrap:
    """Ensure RadMon Grafana datasource, TV dashboards, and playlist exist."""

    def __init__(
        self,
        settings: Settings,
        *,
        project_root: Path | None = None,
        dashboard_probe: Callable[[str], bool] | None = None,
        playlist_probe: Callable[[str], bool] | None = None,
        grafana_health_probe: Callable[[str], bool] | None = None,
        api_provisioner: Callable[[str], bool] | None = None,
        native_runner: Callable[..., None] | None = None,
        compose_runner: Callable[..., None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        attempts: int = 20,
    ) -> None:
        self.settings = settings
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.dashboard_probe = dashboard_probe or self._probe_dashboard
        self.playlist_probe = playlist_probe or self._probe_playlist
        self.grafana_health_probe = grafana_health_probe or self._probe_health
        self.api_provisioner = api_provisioner or self._provision_via_api
        self.native_runner = native_runner or self._run_native
        self.compose_runner = compose_runner or self._run_compose
        self.sleeper = sleeper
        self.attempts = max(1, attempts)

    @property
    def fallback_base_url(self) -> str:
        return f"http://localhost:{self.settings.grafana_fallback_port}"

    def _candidate_base_urls(self) -> list[str]:
        preferred = _base_url(self.settings.grafana_url)
        candidates = [preferred]
        local_default = "http://localhost:3000"
        if local_default not in candidates:
            candidates.append(local_default)
        return candidates

    def _ready(self, base_url: str) -> bool:
        return self.dashboard_probe(base_url) and self.playlist_probe(base_url)

    def ensure(self) -> str:
        candidates = self._candidate_base_urls()
        errors: list[str] = []

        for base in candidates:
            if self._ready(base):
                return playlist_url(base)

        for base in candidates:
            if not self.grafana_health_probe(base):
                continue
            try:
                provisioned = self.api_provisioner(base)
                if provisioned and self._ready(base):
                    return playlist_url(base)
            except Exception as exc:
                errors.append(f"{base}: {exc}")

        native_port = self._find_free_port(self.settings.grafana_fallback_port)
        native_base = f"http://localhost:{native_port}"
        native_env = self._native_environment(native_port)
        try:
            self.native_runner(env=native_env, port=native_port)
            native_verified = False
            for _ in range(self.attempts):
                if self.grafana_health_probe(native_base):
                    try:
                        if self.api_provisioner(native_base) and self._ready(native_base):
                            native_verified = True
                            return playlist_url(native_base)
                    except Exception as exc:
                        errors.append(f"native {native_base}: {exc}")
                        break
                self.sleeper(1.0)
            if not native_verified and not any(native_base in item for item in errors):
                errors.append(f"native {native_base}: playlist monitoring belum terverifikasi")
        except Exception as exc:
            errors.append(f"native Grafana: {exc}")

        fallback = self.fallback_base_url
        docker_env = self._docker_environment()
        try:
            self.compose_runner(env=docker_env)
            docker_verified = False
            for _ in range(self.attempts):
                if self.grafana_health_probe(fallback):
                    try:
                        if self.api_provisioner(fallback) and self._ready(fallback):
                            docker_verified = True
                            return playlist_url(fallback)
                    except Exception as exc:
                        errors.append(f"Docker {fallback}: {exc}")
                        break
                self.sleeper(1.0)
            if not docker_verified and not any(fallback in item for item in errors):
                errors.append(f"Docker {fallback}: playlist monitoring belum terverifikasi")
        except Exception as exc:
            errors.append(f"Docker Grafana: {exc}")

        detail = "; ".join(errors[-4:]) if errors else "playlist monitoring tidak terverifikasi"
        raise RuntimeError(
            "Grafana RadMon tidak dapat disiapkan otomatis. "
            f"{detail}. Set RADMON_GRAFANA_BIN bila Grafana terpasang di lokasi non-standar."
        )

    def _dashboard_payloads(self) -> list[dict]:
        return build_dashboard_payloads()

    def _dashboard_payload(self) -> dict:
        """Compatibility helper returning page 1."""
        return self._dashboard_payloads()[0]

    def _datasource_payload(self) -> dict:
        return {
            "uid": DATASOURCE_UID,
            "name": "ipradmon",
            "type": "mysql",
            "access": "proxy",
            "url": f"{self.settings.db_host}:{self.settings.db_port}",
            "database": self.settings.db_name,
            "user": self.settings.db_user,
            "jsonData": {
                "maxOpenConns": 10,
                "maxIdleConns": 5,
                "connMaxLifetime": 14400,
            },
            "secureJsonData": {"password": self.settings.db_password},
        }

    def _provision_via_api(self, base_url: str) -> bool:
        """Install or repair datasource, TV dashboards, and the 10-second playlist."""
        base = base_url.rstrip("/")
        datasource_endpoint = f"{base}/api/datasources/uid/{DATASOURCE_UID}"
        payload = self._datasource_payload()
        try:
            self._request_json(datasource_endpoint)
        except Exception:
            self._request_json(
                f"{base}/api/datasources",
                method="POST",
                payload=payload,
            )
        else:
            self._request_json(datasource_endpoint, method="PUT", payload=payload)

        for dashboard in self._dashboard_payloads():
            self._request_json(
                f"{base}/api/dashboards/db",
                method="POST",
                payload={
                    "dashboard": dashboard,
                    "folderId": 0,
                    "overwrite": True,
                    "message": "RadMon TV automatic setup",
                },
            )

        playlist_endpoint = (
            f"{base}/apis/playlist.grafana.app/v1/namespaces/default/playlists/{PLAYLIST_UID}"
        )
        try:
            current = self._request_json(playlist_endpoint)
        except Exception:
            self._request_json(
                f"{base}/apis/playlist.grafana.app/v1/namespaces/default/playlists",
                method="POST",
                payload=build_playlist_payload(),
            )
        else:
            metadata = current.get("metadata", {}) if isinstance(current, dict) else {}
            self._request_json(
                playlist_endpoint,
                method="PUT",
                payload=build_playlist_payload(
                    resource_version=str(metadata.get("resourceVersion"))
                    if metadata.get("resourceVersion") is not None
                    else None
                ),
            )
        return True

    def _native_environment(self, port: int) -> dict[str, str]:
        runtime = self.project_root / self.settings.runtime_dir / "grafana"
        data = runtime / "data"
        logs = runtime / "logs"
        plugins = runtime / "plugins"
        for path in (runtime, data, logs, plugins):
            path.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "GF_SERVER_HTTP_ADDR": "127.0.0.1",
                "GF_SERVER_HTTP_PORT": str(port),
                "GF_PATHS_DATA": str(data.resolve()),
                "GF_PATHS_LOGS": str(logs.resolve()),
                "GF_PATHS_PLUGINS": str(plugins.resolve()),
                "GF_SECURITY_ADMIN_USER": self.settings.grafana_user,
                "GF_SECURITY_ADMIN_PASSWORD": self.settings.grafana_password,
                "GF_AUTH_ANONYMOUS_ENABLED": "true",
                "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
                "GF_DASHBOARDS_MIN_REFRESH_INTERVAL": "2s",
                "GF_USERS_DEFAULT_THEME": "light",
            }
        )
        return env

    def _docker_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "RADMON_GRAFANA_PORT": str(self.settings.grafana_fallback_port),
                "RADMON_DB_PORT": str(self.settings.db_port),
                "RADMON_DB_USER": self.settings.db_user,
                "RADMON_DB_PASSWORD": self.settings.db_password,
                "RADMON_GRAFANA_DB_HOST": "host.docker.internal",
            }
        )
        return env

    def _find_free_port(self, preferred: int) -> int:
        for port in range(preferred, preferred + 20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    continue
                return port
        raise RuntimeError(f"tidak ada port Grafana kosong mulai {preferred}")

    def _find_native_grafana(self) -> Path | None:
        candidates: list[Path] = []
        if self.settings.grafana_bin:
            candidates.append(Path(self.settings.grafana_bin).expanduser())

        for executable in (
            shutil.which("grafana-server.exe"),
            shutil.which("grafana.exe"),
            shutil.which("grafana-server"),
            shutil.which("grafana"),
        ):
            if executable:
                candidates.append(Path(executable))

        if os.name == "nt":
            program_files = [
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            for root in filter(None, program_files):
                base = Path(root)
                candidates.extend(
                    [
                        base / "GrafanaLabs" / "grafana" / "bin" / "grafana-server.exe",
                        base / "GrafanaLabs" / "grafana" / "bin" / "grafana.exe",
                        base / "Programs" / "GrafanaLabs" / "grafana" / "bin" / "grafana-server.exe",
                        base / "Programs" / "GrafanaLabs" / "grafana" / "bin" / "grafana.exe",
                    ]
                )
            candidates.extend(
                [
                    Path("C:/Grafana/bin/grafana-server.exe"),
                    Path("C:/Grafana/bin/grafana.exe"),
                ]
            )
            running = self._running_grafana_executable()
            if running is not None:
                candidates.insert(0, running)

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _running_grafana_executable(self) -> Path | None:
        if os.name != "nt":
            return None
        command = (
            "$names=@('grafana-server.exe','grafana.exe'); "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $names -contains $_.Name -and $_.ExecutablePath } | "
            "Select-Object -First 1 -ExpandProperty ExecutablePath"
        )
        kwargs: dict = {
            "capture_output": True,
            "text": True,
            "timeout": 5,
            "check": False,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        path = (result.stdout or "").strip().splitlines()
        if not path:
            return None
        candidate = Path(path[0].strip())
        return candidate if candidate.is_file() else None

    def _run_native(self, *, env: dict[str, str], port: int) -> None:
        executable = self._find_native_grafana()
        if executable is None:
            raise RuntimeError(
                "Grafana executable tidak ditemukan. Set RADMON_GRAFANA_BIN ke grafana-server.exe/grafana.exe"
            )

        home = executable.parent.parent
        command = [str(executable)]
        if executable.name.lower() == "grafana.exe":
            command.append("server")
        command.extend(["--homepath", str(home)])

        runtime = self.project_root / self.settings.runtime_dir / "grafana"
        runtime.mkdir(parents=True, exist_ok=True)
        log_path = runtime / f"grafana-{port}.log"
        log_handle = log_path.open("a", encoding="utf-8")
        kwargs: dict = {
            "cwd": str(home),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(command, **kwargs)
        finally:
            log_handle.close()
        (runtime / "grafana.pid").write_text(str(process.pid), encoding="ascii")

    def _run_compose(self, *, env: dict[str, str]) -> None:
        compose_file = self.project_root / "grafana" / "docker-compose.yml"
        if not compose_file.exists():
            raise FileNotFoundError(compose_file)
        kwargs: dict = {
            "cwd": str(self.project_root),
            "env": env,
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": 30,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "up", "-d"],
                **kwargs,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Docker tidak ditemukan") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("docker compose timeout setelah 30 detik") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"docker compose gagal: {detail}") from exc

    def _probe_health(self, base_url: str) -> bool:
        try:
            data = self._request_json(f"{base_url.rstrip('/')}/api/health", use_auth=False)
            return isinstance(data, dict) and bool(data)
        except Exception:
            return False

    def _probe_dashboard(self, base_url: str) -> bool:
        base = base_url.rstrip("/")
        try:
            for uid in PAGE_UIDS:
                dashboard = self._request_json(f"{base}/api/dashboards/uid/{uid}")
                if not (
                    isinstance(dashboard, dict)
                    and isinstance(dashboard.get("dashboard"), dict)
                    and dashboard["dashboard"].get("uid") == uid
                ):
                    return False
            return True
        except Exception:
            return False

    def _probe_playlist(self, base_url: str) -> bool:
        endpoint = (
            f"{base_url.rstrip('/')}/apis/playlist.grafana.app/v1/"
            f"namespaces/default/playlists/{PLAYLIST_UID}"
        )
        try:
            playlist = self._request_json(endpoint)
            spec = playlist.get("spec", {}) if isinstance(playlist, dict) else {}
            items = spec.get("items", []) if isinstance(spec, dict) else []
            return bool(
                playlist.get("metadata", {}).get("name") == PLAYLIST_UID
                and spec.get("interval") == "10s"
                and [item.get("value") for item in items] == list(PAGE_UIDS)
            )
        except Exception:
            return False

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        use_auth: bool = True,
    ) -> dict:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if use_auth:
            credentials = f"{self.settings.grafana_user}:{self.settings.grafana_password}"
            encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=2.0) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if use_auth and method == "GET" and exc.code in {401, 403}:
                return self._request_json(url, method=method, payload=payload, use_auth=False)
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Grafana API {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Grafana tidak dapat dihubungi: {exc.reason}") from exc
