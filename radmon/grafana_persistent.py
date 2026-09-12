from __future__ import annotations

import os
import socket

from .grafana_bootstrap import DATASOURCE_UID, GrafanaBootstrap
from .grafana_tv import PLAYLIST_UID, build_playlist_payload, playlist_url


class PersistentGrafanaBootstrap(GrafanaBootstrap):
    """Seed missing Grafana resources while treating saved Grafana state as authoritative."""

    def __init__(self, *args, **kwargs) -> None:
        compose_runner = kwargs.get("compose_runner")
        super().__init__(*args, **kwargs)
        self._compose_fallback_explicit = compose_runner is not None

    def _probe_playlist(self, base_url: str) -> bool:
        endpoint = (
            f"{base_url.rstrip('/')}/apis/playlist.grafana.app/v1/"
            f"namespaces/default/playlists/{PLAYLIST_UID}"
        )
        try:
            playlist = self._request_json(endpoint)
            return bool(
                isinstance(playlist, dict)
                and playlist.get("metadata", {}).get("name") == PLAYLIST_UID
            )
        except Exception:
            return False

    def _provision_via_api(self, base_url: str) -> bool:
        base = base_url.rstrip("/")
        datasource_endpoint = f"{base}/api/datasources/uid/{DATASOURCE_UID}"
        try:
            self._request_json(datasource_endpoint)
        except Exception:
            self._request_json(
                f"{base}/api/datasources",
                method="POST",
                payload=self._datasource_payload(),
            )

        for factory_dashboard in self._dashboard_payloads():
            uid = str(factory_dashboard.get("uid") or "")
            dashboard_endpoint = f"{base}/api/dashboards/uid/{uid}"
            try:
                current = self._request_json(dashboard_endpoint)
            except Exception:
                dashboard = dict(factory_dashboard)
                dashboard["editable"] = True
                self._request_json(
                    f"{base}/api/dashboards/db",
                    method="POST",
                    payload={
                        "dashboard": dashboard,
                        "folderId": 0,
                        "overwrite": False,
                        "message": "RadMon initial monitoring seed",
                    },
                )
            else:
                # One-time compatibility migration for dashboards seeded by older
                # RadMon builds. Preserve the saved dashboard verbatim and only
                # unlock Grafana editing; never restore factory layout/content.
                saved = current.get("dashboard") if isinstance(current, dict) else None
                if isinstance(saved, dict) and saved.get("editable") is False:
                    editable = dict(saved)
                    editable["editable"] = True
                    self._request_json(
                        f"{base}/api/dashboards/db",
                        method="POST",
                        payload={
                            "dashboard": editable,
                            "folderId": 0,
                            "overwrite": True,
                            "message": "RadMon unlock existing monitoring dashboard",
                        },
                    )

        playlist_endpoint = (
            f"{base}/apis/playlist.grafana.app/v1/namespaces/default/playlists/{PLAYLIST_UID}"
        )
        try:
            self._request_json(playlist_endpoint)
        except Exception:
            self._request_json(
                f"{base}/apis/playlist.grafana.app/v1/namespaces/default/playlists",
                method="POST",
                payload=build_playlist_payload(),
            )
        return True

    def _native_environment(self, port: int) -> dict[str, str]:
        env = super()._native_environment(port)
        env["GF_SERVER_HTTP_ADDR"] = "0.0.0.0"
        env["GF_AUTH_ANONYMOUS_ENABLED"] = "true"
        env["GF_AUTH_ANONYMOUS_ORG_ROLE"] = "Viewer"
        env["GF_AUTH_DISABLE_LOGIN_FORM"] = "false"
        return env

    def _find_free_port(self, preferred: int) -> int:
        """Keep Grafana's production address stable instead of silently moving ports."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", int(preferred)))
            except OSError as exc:
                raise RuntimeError(
                    f"port Grafana {preferred} sudah dipakai proses lain; RadMon tidak akan pindah port otomatis"
                ) from exc
        return int(preferred)

    def _ensure_base(self) -> str:
        candidates = self._candidate_base_urls()
        errors: list[str] = []
        for base in candidates:
            if self._ready(base):
                return playlist_url(base)
        for base in candidates:
            if not self.grafana_health_probe(base):
                continue
            try:
                if self.api_provisioner(base) and self._ready(base):
                    return playlist_url(base)
            except Exception as exc:
                errors.append(f"{base}: {exc}")

        native_port = self._find_free_port(self.settings.grafana_fallback_port)
        native_base = f"http://localhost:{native_port}"
        try:
            self.native_runner(env=self._native_environment(native_port), port=native_port)
            for _ in range(self.attempts):
                if self.grafana_health_probe(native_base):
                    if self.api_provisioner(native_base) and self._ready(native_base):
                        return playlist_url(native_base)
                self.sleeper(1.0)
            errors.append(f"native {native_base}: monitoring belum terverifikasi")
        except Exception as exc:
            errors.append(f"native Grafana: {exc}")

        allow_compose = self._compose_fallback_explicit or os.getenv(
            "RADMON_GRAFANA_DOCKER_FALLBACK", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if allow_compose:
            fallback = self.fallback_base_url
            try:
                self.compose_runner(env=self._docker_environment())
                for _ in range(self.attempts):
                    if self.grafana_health_probe(fallback):
                        if self.api_provisioner(fallback) and self._ready(fallback):
                            return playlist_url(fallback)
                    self.sleeper(1.0)
            except Exception as exc:
                errors.append(f"Docker Grafana: {exc}")

        detail = "; ".join(errors[-4:]) if errors else "monitoring tidak terverifikasi"
        raise RuntimeError(
            "Grafana RadMon tidak dapat disiapkan otomatis. "
            f"{detail}. Install Grafana native atau set RADMON_GRAFANA_BIN."
        )

    def ensure(self) -> str:
        """Reuse saved dashboards as-is; provision only when resources are missing."""
        candidates = self._candidate_base_urls()
        for base in candidates:
            if self._ready(base):
                return playlist_url(base)
        return self._ensure_base()
