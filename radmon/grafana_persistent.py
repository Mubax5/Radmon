from __future__ import annotations

from copy import deepcopy
import logging
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
            response = self._request_json(endpoint, method="POST")
        except Exception as exc:
            return False, str(exc)
        status = str(response.get("status") or "").strip().casefold()
        details = response.get("details") if isinstance(response, dict) else None
        verbose_message = details.get("verboseMessage") if isinstance(details, dict) else None
        detail = str(
            verbose_message
            or response.get("message")
            or response.get("error")
            or response.get("status")
            or "unknown datasource health response"
        ).strip()
        return status in {"ok", "success"}, detail

    def _ensure_datasource_connection(self, base_url: str) -> bool:
        """Verify Grafana's datasource, repairing only its configured secret if needed."""
        base = base_url.rstrip("/")
        datasource_endpoint = f"{base}/api/datasources/uid/{DATASOURCE_UID}"
        healthy, detail = self._datasource_health(base)
        if healthy:
            return True

        if "authentication plugin is not supported" in detail.casefold():
            logging.getLogger(__name__).error(
                "Grafana datasource is degraded: its MariaDB account advertises an unsupported authentication plugin"
            )
            return False

        # Grafana intentionally redacts secure fields from datasource GET responses.
        # Keep its saved UID and all non-secret settings, and refresh only the
        # password held in the active RadMon DB configuration. Never delete or
        # recreate persistent datasource state as a health-repair shortcut.
        try:
            current = self._request_json(datasource_endpoint)
        except Exception as exc:
            detail = str(exc)
            for secret in (self.settings.db_password, self.settings.grafana_password):
                if secret:
                    detail = detail.replace(secret, "<redacted>")
            logging.getLogger(__name__).error(
                "Grafana datasource is degraded and its settings could not be safely read: %s",
                detail,
            )
            return False
        if not isinstance(current, dict) or current.get("uid") != DATASOURCE_UID:
            logging.getLogger(__name__).error(
                "Grafana datasource is degraded and its settings could not be safely read; persistent state was left untouched"
            )
            return False
        preserved_fields = (
            "id",
            "orgId",
            "uid",
            "name",
            "type",
            "access",
            "url",
            "database",
            "user",
            "basicAuth",
            "basicAuthUser",
            "withCredentials",
            "isDefault",
            "jsonData",
        )
        payload = {
            key: deepcopy(current[key])
            for key in preserved_fields
            if key in current
        }
        payload["secureJsonData"] = {"password": self.settings.db_password}
        self._request_json(datasource_endpoint, method="PUT", payload=payload)

        repaired, repaired_detail = self._datasource_health(base)
        if not repaired:
            safe_detail = repaired_detail or detail
            for secret in (self.settings.db_password, self.settings.grafana_password):
                if secret:
                    safe_detail = safe_detail.replace(secret, "<redacted>")
            logging.getLogger(__name__).error(
                "Grafana datasource remains degraded after password-only repair: %s",
                safe_detail,
            )
            return False
        return True

    @staticmethod
    def _refresh_managed_dashboard_queries(
        saved_dashboard: dict,
        factory_dashboard: dict,
    ) -> tuple[dict, bool]:
        """Refresh managed state while preserving operator-owned presentation state."""
        migrated = deepcopy(saved_dashboard)
        changed = False

        # Grafana persists the dashboard root time range separately from panel
        # queries. Keep the managed trend windows and stable refresh in sync,
        # while preserving saved layout and panel presentation.
        is_page_one = str(factory_dashboard.get("uid") or "") == PAGE_UIDS[0]
        is_page_two = str(factory_dashboard.get("uid") or "") == PAGE_UIDS[1]
        if is_page_one or is_page_two:
            factory_time = factory_dashboard.get("time")
            if isinstance(factory_time, dict) and migrated.get("time") != factory_time:
                migrated["time"] = deepcopy(factory_time)
                changed = True
            factory_refresh = factory_dashboard.get("refresh")
            if factory_refresh and migrated.get("refresh") != factory_refresh:
                migrated["refresh"] = factory_refresh
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

        if is_page_one:
            # The factory no longer uses the timestamp-only row; the trend
            # itself now occupies that card area beneath status and dose.
            retained_panels = [
                panel for panel in panels
                if not (isinstance(panel, dict) and panel.get("description") == "latest-measurement-time")
            ]
            if len(retained_panels) != len(panels):
                panels = retained_panels
                migrated["panels"] = panels
                changed = True

        if is_page_one:
            # Reflow only panels still at known factory coordinates. A panel
            # moved by an operator is left untouched.
            old_x_positions = (0, 5, 10, 15, 20)
            old_widths = (5, 5, 5, 5, 4)
            for panel in panels:
                if not isinstance(panel, dict):
                    continue
                panel_id = panel.get("id")
                factory_panel = factory_panels.get(panel_id)
                factory_position = factory_panel.get("gridPos") if isinstance(factory_panel, dict) else None
                if not isinstance(factory_position, dict):
                    continue
                old_position = None
                if isinstance(panel_id, int) and 10 <= panel_id <= 54:
                    station_index, part = divmod(panel_id - 10, 3)
                    row, col = divmod(station_index, 5)
                    old_y = 4 + row * 5
                    old_position = {
                        "x": old_x_positions[col],
                        "y": old_y + (0 if part == 0 else 2 if part == 1 else 3),
                        "w": old_widths[col],
                        "h": 2 if part == 0 else 1,
                    }
                elif isinstance(panel_id, int) and 55 <= panel_id <= 69:
                    station_index = panel_id - 55
                    row, col = divmod(station_index, 5)
                    old_position = {
                        "x": old_x_positions[col], "y": 8 + row * 5,
                        "w": old_widths[col], "h": 1,
                    }
                if panel.get("gridPos") == old_position:
                    if panel.get("gridPos") != factory_position:
                        panel["gridPos"] = deepcopy(factory_position)
                        changed = True

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

            # Page-one dose values and status lamps are managed presentation:
            # update visualization type/format/mappings while preserving each
            # panel's saved title and any non-factory grid position.
            if factory_panel.get("description") in {"latest-dose-value", "central-status-lamp"}:
                for key in ("type", "description", "fieldConfig", "options", "transformations"):
                    factory_value = factory_panel.get(key)
                    if factory_value is None and key in panel:
                        panel.pop(key)
                        changed = True
                    elif factory_value is not None and panel.get(key) != factory_value:
                        panel[key] = deepcopy(factory_value)
                        changed = True

            # Keep managed dose fields at exactly two decimals while retaining
            # every unrelated operator-owned field setting.
            factory_config = factory_panel.get("fieldConfig") or {}
            saved_config = panel.get("fieldConfig")
            if isinstance(factory_config, dict) and isinstance(saved_config, dict):
                factory_defaults = factory_config.get("defaults") or {}
                saved_defaults = saved_config.get("defaults")
                if (
                    isinstance(factory_defaults, dict)
                    and factory_defaults.get("decimals") == 2
                    and isinstance(saved_defaults, dict)
                    and saved_defaults.get("decimals") != 2
                ):
                    saved_defaults["decimals"] = 2
                    changed = True

                if (
                    isinstance(factory_defaults, dict)
                    and factory_defaults.get("noValue")
                    and isinstance(saved_defaults, dict)
                ):
                    if saved_defaults.get("noValue") != factory_defaults["noValue"]:
                        saved_defaults["noValue"] = factory_defaults["noValue"]
                        changed = True
                factory_custom = factory_defaults.get("custom") if isinstance(factory_defaults, dict) else None
                saved_custom = saved_defaults.get("custom") if isinstance(saved_defaults, dict) else None
                if (
                    isinstance(factory_custom, dict)
                    and factory_custom.get("spanNulls") is False
                    and isinstance(saved_custom, dict)
                    and saved_custom.get("spanNulls") is not False
                ):
                    saved_custom["spanNulls"] = False
                    changed = True

                factory_overrides = factory_config.get("overrides") or []
                saved_overrides = saved_config.get("overrides") or []
                factory_decimals = {
                    (item.get("matcher", {}).get("id"), item.get("matcher", {}).get("options")): next(
                        (prop.get("value") for prop in item.get("properties", []) if prop.get("id") == "decimals"),
                        None,
                    )
                    for item in factory_overrides
                    if isinstance(item, dict)
                    and any(prop.get("id") == "decimals" for prop in item.get("properties", []))
                }
                for override in saved_overrides:
                    if not isinstance(override, dict):
                        continue
                    matcher = override.get("matcher") or {}
                    key = (matcher.get("id"), matcher.get("options"))
                    if key not in factory_decimals:
                        continue
                    properties = override.get("properties") or []
                    decimal_value = factory_decimals[key]
                    decimal_props = [item for item in properties if item.get("id") == "decimals"]
                    decimal_prop = decimal_props[0] if decimal_props else None
                    if decimal_prop is None:
                        properties.append({"id": "decimals", "value": decimal_value})
                        override["properties"] = properties
                        changed = True
                    elif decimal_prop.get("value") != decimal_value or len(decimal_props) > 1:
                        decimal_prop["value"] = decimal_value
                        override["properties"] = [
                            item for item in properties
                            if item.get("id") != "decimals" or item is decimal_prop
                        ]
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

        has_managed_station_panels = sum(
            1 for panel in panels
            if isinstance(panel, dict)
            and (
                panel.get("description") in {"latest-dose-value", "latest-dose-sparkline"}
                or isinstance(panel.get("id"), int) and 10 <= panel["id"] <= 54
            )
        ) >= 15
        if is_page_one and has_managed_station_panels:
            saved_ids = {
                panel.get("id")
                for panel in panels
                if isinstance(panel, dict)
            }
            for panel_id, factory_panel in factory_panels.items():
                if (
                    panel_id not in saved_ids
                    and factory_panel.get("description") == "central-status-lamp"
                ):
                    panels.append(deepcopy(factory_panel))
                    changed = True

        return migrated, changed

    def _provision_dashboards_via_api(self, base_url: str) -> None:
        """Provision dashboard contracts through Grafana's API without touching datasource state."""
        base = base_url.rstrip("/")
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

        self._ensure_datasource_connection(base)
        self._provision_dashboards_via_api(base)

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
