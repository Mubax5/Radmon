from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import Settings


DASHBOARD_UID = "radmon-radiation-monitoring"
DASHBOARD_SLUG = "radiation-monitoring"


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
    """Verify the RadMon dashboard and start the bundled Grafana when needed."""

    def __init__(
        self,
        settings: Settings,
        *,
        project_root: Path | None = None,
        dashboard_probe: Callable[[str], bool] | None = None,
        compose_runner: Callable[..., None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        attempts: int = 20,
    ) -> None:
        self.settings = settings
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.dashboard_probe = dashboard_probe or self._probe_dashboard
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

        # The preferred endpoint may be an unrelated Grafana. Always bring up
        # the bundled/provisioned instance before trusting the fallback port.
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
            raise RuntimeError(f"Grafana auto setup failed: {exc}") from exc

        for _ in range(self.attempts):
            if self.dashboard_probe(fallback):
                return dashboard_url(fallback)
            self.sleeper(1.0)
        raise RuntimeError(
            f"Grafana dashboard {DASHBOARD_UID} tidak terverifikasi di {fallback}"
        )

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

    def _probe_dashboard(self, base_url: str) -> bool:
        try:
            health = self._request_json(f"{base_url.rstrip('/')}/api/health")
            if not isinstance(health, dict):
                return False
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

    def _request_json(self, url: str) -> dict:
        credentials = f"{self.settings.grafana_user}:{self.settings.grafana_password}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers = {"Accept": "application/json", "Authorization": f"Basic {encoded}"}
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=1.5) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Bundled Grafana permits anonymous Viewer access. Retry without
            # Basic auth in case existing admin credentials differ.
            if exc.code not in {401, 403}:
                raise
            request = Request(url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=1.5) as response:
                return json.loads(response.read().decode("utf-8"))
