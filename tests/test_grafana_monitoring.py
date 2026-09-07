import json
from dataclasses import replace
from pathlib import Path

from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import PAGE_UIDS, PLAYLIST_UID, build_dashboard_payloads

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_python_runtime_no_longer_hosts_public_monitoring():
    runtime = read("radmon/runtime.py")
    assert "create_public_app" not in runtime
    assert "uvicorn" not in runtime
    assert "radmon-public" not in runtime


def test_settings_and_admin_open_verified_grafana_monitoring():
    config = read("radmon/config.py")
    main_window = read("radmon/admin/main_window.py")
    assert "grafana_url" in config
    assert "grafana_fallback_port" in config
    assert "RADMON_GRAFANA_URL" in config
    assert "RADMON_GRAFANA_PORT" in config
    assert "GrafanaBootstrap" in main_window
    assert "QDesktopServices.openUrl" in main_window
    assert "self._grafana_ready_url" in main_window


def test_bootstrap_falls_back_from_unrelated_port_3000_and_verifies_playlist():
    settings = replace(Settings(), grafana_url="http://localhost:3000", grafana_fallback_port=3300)
    compose_calls: list[dict] = []

    def probe(base_url: str) -> bool:
        return base_url == "http://localhost:3300"

    def compose_runner(*, env):
        compose_calls.append(dict(env))

    bootstrap = GrafanaBootstrap(
        settings,
        dashboard_probe=probe,
        playlist_probe=probe,
        grafana_health_probe=lambda base: base == "http://localhost:3300",
        api_provisioner=lambda base: True,
        native_runner=lambda **_: (_ for _ in ()).throw(RuntimeError("native unavailable")),
        compose_runner=compose_runner,
        sleeper=lambda _: None,
        attempts=2,
    )
    result = bootstrap.ensure()

    assert compose_calls
    assert compose_calls[0]["RADMON_GRAFANA_PORT"] == "3300"
    assert result.startswith(f"http://localhost:3300/playlists/play/{PLAYLIST_UID}")
    assert "kiosk=1" in result and "autofitpanels" in result


def test_bootstrap_refuses_to_return_unverified_playlist():
    bootstrap = GrafanaBootstrap(
        replace(Settings(), grafana_fallback_port=3300),
        dashboard_probe=lambda base_url: False,
        playlist_probe=lambda base_url: False,
        compose_runner=lambda **kwargs: None,
        sleeper=lambda _: None,
        attempts=2,
    )
    try:
        bootstrap.ensure()
    except RuntimeError as exc:
        assert "playlist" in str(exc).lower()
    else:
        raise AssertionError("unverified Grafana playlist must not be returned")


def test_grafana_tv_pages_refresh_every_two_seconds_and_use_existing_schema_only():
    dashboards = build_dashboard_payloads()
    assert [dashboard["uid"] for dashboard in dashboards] == list(PAGE_UIDS)
    for dashboard in dashboards:
        assert dashboard["refresh"] == "2s"
        assert dashboard["timezone"] == "browser"
        assert dashboard["templating"]["list"] == []
    payload = json.dumps(dashboards, ensure_ascii=False)
    for table in ("device", "measurement", "alarm"):
        assert table in payload
    assert " recent " not in payload.lower()
    assert "radmon_" not in payload
    assert "REAL TIME DOSE RATE MONITORING SYSTEM" in payload
    assert "µSv/h" in payload
    assert "Dose Rate Monitoring" in payload


def test_grafana_provisioning_uses_mysql_and_collision_safe_bundled_port():
    datasource = read("grafana/provisioning/datasources/ipradmon.yaml")
    compose = read("grafana/docker-compose.yml")
    assert "type: mysql" in datasource
    assert "database: ipradmon" in datasource
    assert "RADMON_DB" in datasource
    assert '${RADMON_GRAFANA_PORT:-3300}:3000' in compose
    assert "GF_AUTH_ANONYMOUS_ENABLED" in compose
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE" in compose
    assert "/var/lib/grafana/dashboards" not in compose
    assert not (ROOT / "grafana/provisioning/dashboards/radmon.yaml").exists()


def test_grafana_owns_public_monitoring_and_queries_alarm_table_explicitly():
    assert not (ROOT / "radmon/public_api.py").exists()
    assert not (ROOT / "monitoring").exists()
    payload = json.dumps(build_dashboard_payloads()[2])
    assert "FROM alarm" in payload or "FROM `alarm`" in payload


def test_tv_pages_have_no_operator_variables():
    for dashboard in build_dashboard_payloads():
        assert dashboard["templating"]["list"] == []
