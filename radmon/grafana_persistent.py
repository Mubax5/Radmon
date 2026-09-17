from __future__ import annotations

from copy import deepcopy
import os
import socket

from .grafana_bootstrap import DATASOURCE_UID, GrafanaBootstrap
from .grafana_tv import PAGE_UIDS, PLAYLIST_UID, build_playlist_payload, playlist_url


class PersistentGrafanaBootstrap(GrafanaBootstrap):
    """Seed missing Grafana resources while treating saved Grafana state as authoritative."""

    def __init__(self, *args, **kwargs) -> None:
        compose_runner = kwargs.get("compose_runner")
        super().__init__(*args, **kwargs)
        self._compose_fallback_explicit = compose_runner is not None

    def _candidate_base_urls(self) -> list[str]:
        """Production Grafana has one stable address: localhost:<configured port>."""
        return [self.fallback_base_url]

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

    def _datasource_health(self, base_url: str) -> tuple[bool, str]:
        endpoint = (
            f"{base_url.rstrip('/')}/api/datasources/uid/{DATASOURCE_UID}/health"
        )
        try:
            response = self._request_json(endpoint)
        except Exception as exc:
            return False, str(exc)
        status = str(response.get("status") or "").strip().casefold()
        detail = str(
            response.get("message")
            or response.get("error")
            or response.get("status")
            or "unknown datasource health response"
        ).strip()
        return status in {"ok", "success"}, detail

    def _ensure_datasource_connection(self, base_url: str) -> None:
        """Verify Grafana can actually query MariaDB and recreate stale datasource state once."""
        base = base_url.rstrip("/")
        datasource_endpoint = f"{base}/api/datasources/uid/{DATASOURCE_UID}"
        healthy, detail = self._datasource_health(base)
        if healthy:
            return

        # A persisted Grafana SQLite datasource can keep stale/invalid secure state
        # across upgrades. Recreate the datasource with the same stable UID and the
        # current RadMon DB settings, leaving dashboards and playlists untouched.
        self._request_json(datasource_endpoint, method="DELETE")
        self._request_json(
            f"{base}/api/datasources",
            method="POST",
            payload=self._datasource_payload(),
        )
        repaired, repaired_detail = self._datasource_health(base)
        if not repaired:
            raise RuntimeError(
                "Grafana datasource MariaDB tetap tidak sehat setelah repair: "
                f"{repaired_detail or detail}"
            )

    @staticmethod
    def _refresh_managed_dashboard_queries(
        saved_dashboard: dict,
        factory_dashboard: dict,
    ) -> tuple[dict, bool]:
        """Refresh managed state while preserving operator-owned presentation state."""
        migrated = deepcopy(saved_dashboard)
        changed = False

        # Grafana persists the dashboard root time range separately from panel
        # queries. Sync only this managed page-2 setting; never replace the
        # saved dashboard or its panel layout.
        is_page_two = str(factory_dashboard.get("uid") or "") == PAGE_UIDS[1]
        if is_page_two:
            factory_time = factory_dashboard.get("time")
            if isinstance(factory_time, dict) and migrated.get("time") != factory_time:
                migrated["time"] = deepcopy(factory_time)
                changed = True

        if migrated.get("editable") is False:
            migrated["editable"] = True
            changed = True

        factory_panels = {
            panel.get("id"): panel
            for panel in factory_dashboard.get("panels", [])
            if panel.get("id") is not None and panel.get("targets")
        }
        panels = migrated.get("panels")
        if not isinstance(panels, list):
            return migrated, changed

        for panel in panels:
            if not isinstance(panel, dict):
                continue
            factory_panel = factory_panels.get(panel.get("id"))
            if not isinstance(factory_panel, dict):
                continue

            factory_targets = factory_panel.get("targets")
            if panel.get("targets") != factory_targets:
                panel["targets"] = deepcopy(factory_targets)
                changed = True

            factory_datasource = factory_panel.get("datasource")
            if factory_datasource is not None and panel.get("datasource") != factory_datasource:
                panel["datasource"] = deepcopy(factory_datasource)
                changed = True

            # Migrate the installed factory label, but leave an operator's
            # deliberate panel rename intact.
            if is_page_two and factory_panel.get("description") == "building-dose-trend":
                saved_title = panel.get("title")
                if isinstance(saved_title, str) and saved_title.endswith(" · 3 Jam"):
                    factory_title = factory_panel.get("title")
                    if saved_title != factory_title:
                        panel["title"] = factory_title
                        changed = True

        return migrated, changed

    def _provision_via_api(self, base_url: str) -> bool:
        base = base_url.rstrip("/")
        datasource_endpoint = f"{base}/api/datasources/uid/{DATASOURCE_UID}"
        datasource_payload = self._datasource_payload()
        try:
            self._request_json(datasource_endpoint)
        except Exception:
            self._request_json(
                f"{base}/api/datasources",
                method="POST",
                payload=datasource_payload,
            )
        else:
            # Dashboard state is persistent and operator-owned, but datasource
            # connection settings must follow the current RadMon config. This
            # also repairs credentials after an installer upgrade or .env edit.
            self._request_json(
                datasource_endpoint,
                method="PUT",
                payload=datasource_payload,
            )

        self._ensure_datasource_connection(base)

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
                # Keep saved layout/title/visual options and custom panels, but the
                # SQL contract of known RadMon panels must follow the installed
                # version. Otherwise a persisted Grafana database can keep running
                # pre-upgrade queries forever (for example FROM measurement after
                # the rolling recent/vrecent migration) and show No data.
                saved = current.get("dashboard") if isinstance(current, dict) else None
                if isinstance(saved, dict):
                    migrated, changed = self._refresh_managed_dashboard_queries(
                        saved,
                        factory_dashboard,
                    )
                    if changed:
                        self._request_json(
                            f"{base}/api/dashboards/db",
                            method="POST",
                            payload={
                                "dashboard": migrated,
                                "folderId": 0,
                                "overwrite": True,
                                "message": "RadMon monitoring query contract migration",
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
        env["GF_SERVER_HTTP_ADDR"] = "127.0.0.1"
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
        """Seed/migrate safely on a healthy Grafana, otherwise start native Grafana."""
        base = self.fallback_base_url
        if self.grafana_health_probe(base):
            if self.api_provisioner(base) and self._ready(base):
                return playlist_url(base)
        return self._ensure_base()
