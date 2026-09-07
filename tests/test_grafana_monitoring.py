import json
from dataclasses import replace
from pathlib import Path

from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap

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


def test_bootstrap_falls_back_from_unrelated_port_3000_and_verifies_uid():
    settings = replace(
        Settings(),
        grafana_url=(
            "http://localhost:3000/d/radmon-radiation-monitoring/"
            "radiation-monitoring?orgId=1&refresh=2s&kiosk=tv"
        ),
        grafana_fallback_port=3300,
    )
    probes: list[str] = []
    compose_calls: list[dict] = []

    def probe(base_url: str) -> bool:
        probes.append(base_url)
        return base_url == "http://localhost:3300"

    def compose_runner(*, env):
        compose_calls.append(dict(env))

    bootstrap = GrafanaBootstrap(
        settings,
        dashboard_probe=probe,
        compose_runner=compose_runner,
        sleeper=lambda _: None,
        attempts=2,
    )
    result = bootstrap.ensure()

    assert probes[0] == "http://localhost:3000"
    assert "http://localhost:3300" in probes
    assert compose_calls
    assert compose_calls[0]["RADMON_GRAFANA_PORT"] == "3300"
    assert result.startswith("http://localhost:3300/d/radmon-radiation-monitoring/")
    assert "refresh=2s" in result and "kiosk=tv" in result


def test_bootstrap_refuses_to_return_unverified_dashboard():
    bootstrap = GrafanaBootstrap(
        replace(Settings(), grafana_fallback_port=3300),
        dashboard_probe=lambda base_url: False,
        compose_runner=lambda **kwargs: None,
        sleeper=lambda _: None,
        attempts=2,
    )
    try:
        bootstrap.ensure()
    except RuntimeError as exc:
        assert "dashboard" in str(exc).lower()
    else:
        raise AssertionError("unverified Grafana dashboard must not be returned")


def test_grafana_dashboard_refreshes_every_two_seconds_and_uses_existing_schema_only():
    dashboard = json.loads(read("grafana/dashboards/radiation-monitoring.json"))
    assert dashboard["refresh"] == "2s"
    assert dashboard["timezone"] == "browser"
    payload = json.dumps(dashboard, ensure_ascii=False)
    for table in ("device", "measurement", "recent", "alarm"):
        assert table in payload
    assert "radmon_" not in payload
    assert "REAL TIME DOSE RATE MONITORING SYSTEM" in payload
    assert "µSv/h" in payload
    assert "Laju dosis" in payload
    assert "Waktu pengukuran" in payload
    assert "Dose Rate Monitoring" in payload


def test_grafana_provisioning_uses_mysql_and_collision_safe_bundled_port():
    datasource = read("grafana/provisioning/datasources/ipradmon.yaml")
    provider = read("grafana/provisioning/dashboards/radmon.yaml")
    compose = read("grafana/docker-compose.yml")
    assert "type: mysql" in datasource
    assert "database: ipradmon" in datasource
    assert "RADMON_DB" in datasource
    assert "/var/lib/grafana/dashboards" in provider
    assert '${RADMON_GRAFANA_PORT:-3300}:3000' in compose
    assert "GF_AUTH_ANONYMOUS_ENABLED" in compose
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE" in compose


def test_grafana_owns_public_monitoring_and_queries_alarm_table_explicitly():
    assert not (ROOT / "radmon/public_api.py").exists()
    assert not (ROOT / "monitoring").exists()
    payload = read("grafana/dashboards/radiation-monitoring.json")
    assert "FROM alarm" in payload or "FROM `alarm`" in payload


def test_all_station_selection_expands_for_repeated_cards():
    dashboard = json.loads(read("grafana/dashboards/radiation-monitoring.json"))
    station = dashboard["templating"]["list"][0]
    assert station["includeAll"] is True
    assert "allValue" not in station
    assert station["current"]["value"] == ["$__all"]
