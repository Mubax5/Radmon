from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import Settings


DASHBOARD_UID = "radmon-radiation-monitoring"
DASHBOARD_SLUG = "radiation-monitoring"
DATASOURCE_UID = "ipradmon-mysql"


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid Grafana URL: {value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def dashboard_url(base_url: str) -> str:
    return (
        f"{base_url.rstrip('/')}/d/{DASHBOARD_UID}/{DASHBOARD_SLUG}"
        "?orgId=1&refresh=2s&kiosk=tv"
    )


class GrafanaBootstrap:
    """Ensure a usable RadMon dashboard exists before Monitoring is opened."""

    def __init__(
        self,
        settings: Settings,
        *,
        project_root: Path | None = None,
        dashboard_probe: Callable[[str], bool] | None = None,
        grafana_health_probe: Callable[[str], bool] | None = None,
        api_provisioner: Callable[[str], bool] | None = None,
        compose_runner: Callable[..., None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        attempts: int = 20,
    ) -> None:
        self.settings = settings
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.dashboard_probe = dashboard_probe or self._probe_dashboard
        self.grafana_health_probe = grafana_health_probe or self._probe_health
        self.api_provisioner = api_provisioner or self._provision_via_api
        self.compose_runner = compose_runner or self._run_compose
        self.sleeper = sleeper
        self.attempts = max(1, attempts)

    @property
    def fallback_base_url(self) -> str:
        return f"http://localhost:{self.settings.grafana_fallback_port}"

    def ensure(self) -> str:
        preferred = _base_url(self.settings.grafana_url)
        if self.dashboard_probe(preferred):
            return dashboard_url(preferred)

        # If Grafana already exists locally, install the RadMon datasource and
        # dashboard into that instance instead of requiring another Grafana.
        if self.grafana_health_probe(preferred):
            try:
                provisioned = self.api_provisioner(preferred)
            except Exception:
                provisioned = False
            if provisioned and self.dashboard_probe(preferred):
                return dashboard_url(preferred)

        fallback = self.fallback_base_url
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
        try:
            self.compose_runner(env=env)
        except Exception as exc:
            raise RuntimeError(
                "Grafana RadMon belum tersedia. Auto-setup ke Grafana lokal gagal "
                f"dan bundled Grafana tidak dapat dijalankan: {exc}"
            ) from exc

        for _ in range(self.attempts):
            if self.dashboard_probe(fallback):
                return dashboard_url(fallback)
            self.sleeper(1.0)
        raise RuntimeError(
            f"Grafana dashboard {DASHBOARD_UID} tidak terverifikasi di {fallback}"
        )

    def _dashboard_payload(self) -> dict:
        path = self.project_root / "grafana" / "dashboards" / "radiation-monitoring.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _provision_via_api(self, base_url: str) -> bool:
        """Install datasource/dashboard into an already-running local Grafana."""
        datasource_url = f"{self.settings.db_host}:{self.settings.db_port}"
        try:
            self._request_json(
                f"{base_url.rstrip('/')}/api/datasources/uid/{DATASOURCE_UID}"
            )
        except Exception:
            self._request_json(
                f"{base_url.rstrip('/')}/api/datasources",
                method="POST",
                payload={
                    "uid": DATASOURCE_UID,
                    "name": "ipradmon",
                    "type": "mysql",
                    "access": "proxy",
                    "url": datasource_url,
                    "database": self.settings.db_name,
                    "user": self.settings.db_user,
                    "jsonData": {"maxOpenConns": 10, "maxIdleConns": 5, "connMaxLifetime": 14400},
                    "secureJsonData": {"password": self.settings.db_password},
                },
            )

        self._request_json(
            f"{base_url.rstrip('/')}/api/dashboards/db",
            method="POST",
            payload={
                "dashboard": self._dashboard_payload(),
                "folderId": 0,
                "overwrite": True,
                "message": "RadMon automatic setup",
            },
        )
        return True

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
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "up", "-d"],
                **kwargs,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Docker tidak ditemukan; instal/aktifkan Docker Desktop") from exc
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
        try:
            dashboard = self._request_json(
                f"{base_url.rstrip('/')}/api/dashboards/uid/{DASHBOARD_UID}"
            )
            return bool(
                isinstance(dashboard, dict)
                and isinstance(dashboard.get("dashboard"), dict)
                and dashboard["dashboard"].get("uid") == DASHBOARD_UID
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
