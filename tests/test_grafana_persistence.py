from copy import deepcopy
from pathlib import Path
import socket

import pytest

from radmon.config import Settings
from radmon.grafana_persistent import PersistentGrafanaBootstrap
from radmon.grafana_tv import DASHBOARD_UIDS, PAGE_UIDS, PLAYLIST_UID


def test_healthy_existing_datasource_is_left_untouched_while_saved_dashboards_are_preserved(tmp_path: Path) -> None:
    settings = Settings(
        db_host="127.0.0.1",
        db_port=3306,
        db_user="radmon_reader",
        db_password="current-secret",
        db_name="ipradmon",
    )
    bootstrap = PersistentGrafanaBootstrap(settings, project_root=tmp_path)
    writes: list[tuple[str, str, dict]] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            assert method == "POST"
            return {"status": "OK", "message": "Database Connection OK"}
        if method != "GET":
            writes.append((method, url, payload or {}))
            return {"status": "ok"}
        if "/api/datasources/uid/" in url:
            return {"uid": "ipradmon-mysql", "name": "ipradmon"}
        if "/api/dashboards/uid/" in url:
            return {"dashboard": {"uid": url.rsplit("/", 1)[-1], "editable": True, "panels": [{"id": 99}]}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID, "resourceVersion": "42"}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    datasource_writes = [
        (method, url)
        for method, url, _ in writes
        if "/api/datasources" in url
    ]
    assert datasource_writes == []
    assert len(writes) == 1
    assert writes[0][0] == "POST"
    assert writes[0][1].endswith("/api/dashboards/db")
    assert writes[0][2]["dashboard"]["uid"] == PAGE_UIDS[1]
    assert writes[0][2]["dashboard"]["time"] == {"from": "now-1h", "to": "now"}


def test_persisted_managed_dashboard_queries_are_refreshed_without_clobbering_layout(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    factory_dashboards = bootstrap._dashboard_payloads()
    factory_by_uid = {str(item["uid"]): item for item in factory_dashboards}
    first_uid = str(factory_dashboards[0]["uid"])
    factory_panel = next(panel for panel in factory_dashboards[0]["panels"] if panel.get("id") == 10)
    writes: list[tuple[str, str, dict]] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            assert method == "POST"
            return {"status": "OK", "message": "Database Connection OK"}
        if method != "GET":
            writes.append((method, url, payload or {}))
            return {"status": "ok"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql"):
            return {"uid": "ipradmon-mysql", "name": "ipradmon"}
        if "/api/dashboards/uid/" in url:
            uid = url.rsplit("/", 1)[-1]
            if uid == first_uid:
                return {
                    "dashboard": {
                        "uid": uid,
                        "title": "Operator custom layout",
                        "editable": True,
                        "panels": [
                            {
                                "id": 10,
                                "title": "Operator renamed panel",
                                "gridPos": {"x": 7, "y": 8, "w": 9, "h": 10},
                                "datasource": {"type": "mysql", "uid": "old-datasource"},
                                "targets": [{"rawSql": "SELECT doserate FROM measurement"}],
                                "options": {"operator": "preserve-me"},
                            },
                            {
                                "id": 999,
                                "type": "text",
                                "title": "Operator custom panel",
                                "gridPos": {"x": 0, "y": 20, "w": 24, "h": 2},
                                "targets": [],
                            },
                        ],
                    }
                }
            saved = deepcopy(factory_by_uid[uid])
            saved["editable"] = True
            return {"dashboard": saved}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    dashboard_writes = [
        payload
        for method, url, payload in writes
        if method == "POST" and url.endswith("/api/dashboards/db")
    ]
    assert len(dashboard_writes) == 1
    migrated = dashboard_writes[0]["dashboard"]
    assert migrated["title"] == "Operator custom layout"
    assert migrated["editable"] is True
    assert len(migrated["panels"]) == 2

    managed = next(panel for panel in migrated["panels"] if panel.get("id") == 10)
    assert managed["title"] == "Operator renamed panel"
    assert managed["gridPos"] == {"x": 7, "y": 8, "w": 9, "h": 10}
    assert managed["options"] == factory_panel["options"]
    assert managed["fieldConfig"] == factory_panel["fieldConfig"]
    assert managed["datasource"] == factory_panel["datasource"]
    assert managed["targets"] == factory_panel["targets"]
    assert "measurement" not in str(managed["targets"]).lower()
    assert "vrecent" in str(managed["targets"]).lower()
    assert next(panel for panel in migrated["panels"] if panel.get("id") == 999)["title"] == "Operator custom panel"


def test_status_lamp_contract_migrates_colors_without_changing_operator_layout(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    factory = bootstrap._dashboard_payloads()[0]
    saved = deepcopy(factory)
    saved_panel = next(panel for panel in saved["panels"] if panel.get("description") == "central-status-lamp")
    original_position = {"x": 4, "y": 9, "w": 8, "h": 3}
    saved_panel["gridPos"] = original_position.copy()
    saved_panel["title"] = "Operator station lamp"
    saved_panel["fieldConfig"] = {"defaults": {"color": {"mode": "fixed"}}, "overrides": []}
    saved_panel["options"] = {"colorMode": "value"}
    saved["panels"].append({"id": 999, "title": "Operator custom panel", "gridPos": {"x": 0, "y": 22, "w": 24, "h": 2}})

    migrated, changed = bootstrap._refresh_managed_dashboard_queries(saved, factory)
    managed = next(panel for panel in migrated["panels"] if panel.get("description") == "central-status-lamp")
    options = managed["fieldConfig"]["defaults"]["mappings"][0]["options"]

    assert changed is True
    assert managed["gridPos"] == original_position
    assert managed["title"] == "Operator station lamp"
    assert options["0"]["color"] == "gray"
    assert options["1"]["color"] == "green"
    assert options["2"]["color"] == "yellow"
    assert options["3"]["color"] == "red"
    assert next(panel for panel in migrated["panels"] if panel.get("id") == 999)["title"] == "Operator custom panel"


def test_legacy_page_one_migrates_to_dose_values_and_adds_separate_status_lamps(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    factory = bootstrap._dashboard_payloads()[0]
    saved = deepcopy(factory)
    saved["panels"] = [
        panel for panel in saved["panels"]
        if panel.get("description") != "central-status-lamp"
    ]

    # Model the persisted pre-fix layout and status-code stat panels. The
    # migration should reflow only this known factory layout, retain station
    # labels, and add one thin status panel per station.
    for panel in saved["panels"]:
        panel_id = panel.get("id")
        if not isinstance(panel_id, int) or not 10 <= panel_id <= 54:
            continue
        station_index, part = divmod(panel_id - 10, 3)
        row, col = divmod(station_index, 5)
        x_positions, widths = [0, 5, 10, 15, 20], [5, 5, 5, 5, 4]
        y = 4 + row * 4
        panel["gridPos"] = {
            "x": x_positions[col],
            "y": y + (0 if part == 0 else 2 if part == 1 else 3),
            "w": widths[col],
            "h": 2 if part == 0 else 1,
        }
        if part == 0:
            panel["description"] = "central-status-lamp"
            panel["targets"] = [{"rawSql": "SELECT CASE status WHEN 'OFFLINE' THEN 0 END AS value FROM vrecent"}]
            panel["fieldConfig"] = {"defaults": {"mappings": []}, "overrides": []}
            panel["options"] = {"colorMode": "background"}
            panel["transformations"] = [{"id": "organize", "options": {"excludeByName": {"value": True}}}]

    original_title = saved["title"]
    migrated, changed = bootstrap._refresh_managed_dashboard_queries(saved, factory)

    assert changed is True
    assert migrated["title"] == original_title
    assert len(migrated["panels"]) == len(factory["panels"])
    dose_panels = [panel for panel in migrated["panels"] if panel.get("description") == "latest-dose-value"]
    lamp_panels = [panel for panel in migrated["panels"] if panel.get("description") == "central-status-lamp"]
    assert len(dose_panels) == len(lamp_panels) == 15
    for dose, lamp in zip(dose_panels, lamp_panels):
        assert "doserate" in dose["targets"][0]["rawSql"]
        assert "SELECT doserate AS doserate" in dose["targets"][0]["rawSql"]
        assert "CASE status" not in dose["targets"][0]["rawSql"]
        assert dose["fieldConfig"]["defaults"]["unit"] == "suffix: µSv/h"
        assert dose["options"]["colorMode"] == "none"
        assert "transformations" not in dose
        assert dose["fieldConfig"] == next(
            item for item in factory["panels"] if item.get("id") == dose["id"]
        )["fieldConfig"]
        mappings = lamp["fieldConfig"]["defaults"]["mappings"][0]["options"]
        assert mappings["0"]["color"] == "gray"
        assert mappings["1"]["color"] == "green"
        assert mappings["2"]["color"] == "yellow"
        assert mappings["3"]["color"] == "red"
    assert [
        panel["gridPos"]["y"]
        for panel in sorted(dose_panels, key=lambda item: item["id"])
    ] == [4] * 5 + [9] * 5 + [14] * 5
    assert [
        panel["gridPos"]["y"]
        for panel in sorted(lamp_panels, key=lambda item: item["id"])
    ] == [8] * 5 + [13] * 5 + [18] * 5


def test_persisted_dose_panels_migrate_to_two_decimals_without_clobbering_other_formatting(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    page_two = bootstrap._dashboard_payloads()[1]
    saved_page_two = deepcopy(page_two)
    trend = next(panel for panel in saved_page_two["panels"] if panel.get("description") == "building-dose-trend")
    trend["fieldConfig"]["defaults"]["decimals"] = 3
    trend["fieldConfig"]["defaults"]["custom"]["lineWidth"] = 2
    migrated_page_two, changed = bootstrap._refresh_managed_dashboard_queries(saved_page_two, page_two)
    migrated_trend = next(panel for panel in migrated_page_two["panels"] if panel.get("description") == "building-dose-trend")
    assert changed is True
    assert migrated_trend["fieldConfig"]["defaults"]["decimals"] == 2
    assert migrated_trend["fieldConfig"]["defaults"]["custom"]["lineWidth"] == 2

    operations = bootstrap._dashboard_payloads()[2]
    saved_operations = deepcopy(operations)
    table = next(panel for panel in saved_operations["panels"] if panel.get("description") == "operational-condition")
    dose_override = next(item for item in table["fieldConfig"]["overrides"] if item["matcher"].get("options") == "Dose Rate")
    dose_override["properties"].append({"id": "decimals", "value": 3})
    migrated_operations, changed = bootstrap._refresh_managed_dashboard_queries(saved_operations, operations)
    migrated_table = next(panel for panel in migrated_operations["panels"] if panel.get("description") == "operational-condition")
    migrated_override = next(item for item in migrated_table["fieldConfig"]["overrides"] if item["matcher"].get("options") == "Dose Rate")
    assert changed is True
    assert {item["id"]: item["value"] for item in migrated_override["properties"]}["decimals"] == 2


def test_persisted_page_two_time_and_factory_titles_are_migrated_safely(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    factory = next(item for item in bootstrap._dashboard_payloads() if item["uid"] == PAGE_UIDS[1])
    saved = deepcopy(factory)
    saved["time"] = {"from": "now-3h", "to": "now"}
    saved["panels"][4]["gridPos"] = {"x": 3, "y": 7, "w": 18, "h": 6}
    for panel in saved["panels"]:
        if panel.get("description") == "building-dose-trend":
            panel["title"] = panel["title"].replace("1 Jam", "3 Jam")
    custom = {"id": 999, "title": "Operator custom panel", "gridPos": {"x": 0, "y": 20, "w": 24, "h": 2}}
    saved["panels"].append(custom)

    migrated, changed = bootstrap._refresh_managed_dashboard_queries(saved, factory)

    assert changed is True
    assert migrated["time"] == {"from": "now-1h", "to": "now"}
    assert all(panel["title"].endswith(" · 1 Jam") for panel in migrated["panels"] if panel.get("description") == "building-dose-trend")
    assert migrated["panels"][4]["gridPos"] == {"x": 3, "y": 7, "w": 18, "h": 6}
    assert migrated["panels"][-1] == custom


def test_legacy_readonly_dashboard_is_unlocked_without_restoring_factory_layout(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    writes: list[dict] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            assert method == "POST"
            return {"status": "OK", "message": "Database Connection OK"}
        if method != "GET":
            writes.append(payload or {})
            return {"status": "ok"}
        if "/api/datasources/uid/" in url:
            return {"uid": "ipradmon-mysql"}
        if "/api/dashboards/uid/" in url:
            uid = url.rsplit("/", 1)[-1]
            return {"dashboard": {"uid": uid, "editable": False, "title": "Operator custom", "panels": [{"id": 777, "title": "Saved custom panel"}]}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    dashboard_writes = [item for item in writes if "dashboard" in item]
    assert len(dashboard_writes) == len(DASHBOARD_UIDS)
    for item in dashboard_writes:
        assert item["overwrite"] is True
        assert item["dashboard"]["editable"] is True
        assert item["dashboard"]["title"] == "Operator custom"
        assert item["dashboard"]["panels"] == [{"id": 777, "title": "Saved custom panel"}]


def test_missing_grafana_resources_are_seeded_editable_without_overwrite(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    posts: list[tuple[str, dict]] = []
    datasource_created = False

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        nonlocal datasource_created
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health") and datasource_created:
            assert method == "POST"
            return {"status": "OK", "message": "Database Connection OK"}
        if method == "GET":
            raise RuntimeError("missing")
        posts.append((url, payload or {}))
        if method == "POST" and url.endswith("/api/datasources"):
            datasource_created = True
        return {"status": "ok"}

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    dashboard_posts = [p for u, p in posts if u.endswith("/api/dashboards/db")]
    assert len(dashboard_posts) == len(DASHBOARD_UIDS)
    assert all(p.get("overwrite") is False for p in dashboard_posts)
    assert all(p["dashboard"].get("editable") is True for p in dashboard_posts)
    assert any("/api/datasources" in u for u, _ in posts)
    assert any("/playlists" in u for u, _ in posts)


def test_native_grafana_is_loopback_only_and_persistent(tmp_path: Path) -> None:
    settings = Settings(runtime_dir=Path("runtime"), grafana_fallback_port=3300)
    env = PersistentGrafanaBootstrap(settings, project_root=tmp_path)._native_environment(3300)
    assert env["GF_SERVER_HTTP_ADDR"] == "127.0.0.1"
    assert env["GF_SERVER_HTTP_PORT"] == "3300"
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    assert env["GF_AUTH_DISABLE_LOGIN_FORM"] == "false"
    assert env["GF_PLUGINS_PREINSTALL_AUTO_UPDATE"] == "false"
    assert str(tmp_path / "runtime" / "grafana" / "data") in env["GF_PATHS_DATA"]


def test_grafana_never_silently_moves_away_from_port_3300(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(grafana_fallback_port=3300), project_root=tmp_path)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    occupied = int(blocker.getsockname()[1])
    try:
        with pytest.raises(RuntimeError, match="tidak akan pindah port otomatis"):
            bootstrap._find_free_port(occupied)
    finally:
        blocker.close()


def test_unhealthy_existing_datasource_repairs_only_password_and_preserves_configuration(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(
        Settings(db_host="new-host", db_user="new-user", db_name="new-database", db_password="current-secret"),
        project_root=tmp_path,
    )
    writes: list[tuple[str, str, dict]] = []
    health_checks = 0

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        nonlocal health_checks
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            assert method == "POST"
            health_checks += 1
            if health_checks == 1:
                return {"status": "ERROR", "message": "Database Connection Failed"}
            return {"status": "OK", "message": "Database Connection OK"}
        if method != "GET":
            writes.append((method, url, payload or {}))
            return {"status": "ok"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql"):
            return {
                "id": 7,
                "orgId": 1,
                "uid": "ipradmon-mysql",
                "name": "ipradmon",
                "type": "mysql",
                "access": "proxy",
                "url": "127.0.0.1:3306",
                "database": "ipradmon",
                "user": "radmon_reader",
                "basicAuth": False,
                "withCredentials": False,
                "isDefault": True,
                "jsonData": {"maxOpenConns": 20, "maxIdleConns": 10},
                "secureJsonFields": {"password": True},
                "version": 11,
            }
        if "/api/dashboards/uid/" in url:
            uid = url.rsplit("/", 1)[-1]
            return {"dashboard": {"uid": uid, "editable": True}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    assert health_checks == 2
    datasource_updates = [
        payload
        for method, url, payload in writes
        if method == "PUT" and url.endswith("/api/datasources/uid/ipradmon-mysql")
    ]
    assert len(datasource_updates) == 1
    assert datasource_updates[0] == {
        "id": 7,
        "orgId": 1,
        "uid": "ipradmon-mysql",
        "name": "ipradmon",
        "type": "mysql",
        "access": "proxy",
        "url": "127.0.0.1:3306",
        "database": "ipradmon",
        "user": "radmon_reader",
        "basicAuth": False,
        "withCredentials": False,
        "isDefault": True,
        "jsonData": {"maxOpenConns": 20, "maxIdleConns": 10},
        "secureJsonData": {"password": "current-secret"},
    }
    assert all(method != "DELETE" for method, _, _ in writes)
    assert all(not (method == "POST" and url.endswith("/api/datasources")) for method, url, _ in writes)


def test_unsupported_auth_plugin_keeps_dashboards_available_without_mutating_datasource(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(
        Settings(db_password="current-secret"),
        project_root=tmp_path,
    )
    writes: list[tuple[str, str, dict]] = []
    health_checks = 0

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        nonlocal health_checks
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            assert method == "POST"
            health_checks += 1
            return {
                "status": "ERROR",
                "message": "[auth] MySQL rejected the configured account.",
                "details": {"verboseMessage": "this authentication plugin is not supported"},
            }
        if method != "GET":
            writes.append((method, url, payload or {}))
            return {"status": "ok"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql"):
            return {
                "uid": "ipradmon-mysql",
                "name": "ipradmon",
                "type": "mysql",
                "access": "proxy",
                "url": "127.0.0.1:3306",
                "database": "ipradmon",
                "user": "radmon_reader",
                "jsonData": {"maxOpenConns": 20},
            }
        if "/api/dashboards/uid/" in url or "/apis/playlist.grafana.app/" in url:
            raise RuntimeError("resource missing")
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    assert health_checks == 1
    assert not [item for item in writes if "/api/datasources" in item[1]]
    assert len([item for item in writes if item[1].endswith("/api/dashboards/db")]) == len(DASHBOARD_UIDS)
    assert any(item[1].endswith("/playlists") for item in writes)
