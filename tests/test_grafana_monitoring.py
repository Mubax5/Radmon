import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_python_runtime_no_longer_hosts_public_monitoring():
    runtime = read("radmon/runtime.py")
    assert "create_public_app" not in runtime
    assert "uvicorn" not in runtime
    assert "radmon-public" not in runtime


def test_settings_and_admin_open_grafana_monitoring():
    config = read("radmon/config.py")
    main_window = read("radmon/admin/main_window.py")
    assert "grafana_url" in config
    assert "RADMON_GRAFANA_URL" in config
    assert "QDesktopServices.openUrl" in main_window
    assert "self.settings.grafana_url" in main_window


def test_grafana_dashboard_refreshes_every_two_seconds_and_uses_existing_schema_only():
    dashboard = json.loads(read("grafana/dashboards/radiation-monitoring.json"))
    assert dashboard["refresh"] == "2s"
    assert dashboard["timezone"] == "browser"
    payload = json.dumps(dashboard)
    for table in ("device", "measurement", "recent", "alarm"):
        assert table in payload
    assert "radmon_" not in payload
    assert "Notifikasi Laju Dosis" in payload
    assert "Laju dosis" in payload
    assert "Waktu pengukuran" in payload
    assert "Dose Rate Monitoring" in payload


def test_grafana_provisioning_uses_mysql_and_no_extra_database_schema():
    datasource = read("grafana/provisioning/datasources/ipradmon.yaml")
    provider = read("grafana/provisioning/dashboards/radmon.yaml")
    assert "type: mysql" in datasource
    assert "database: ipradmon" in datasource
    assert "RADMON_DB" in datasource
    assert "/var/lib/grafana/dashboards" in provider


def test_grafana_owns_public_monitoring_and_queries_alarm_table_explicitly():
    assert not (ROOT / "radmon/public_api.py").exists()
    assert not (ROOT / "monitoring").exists()
    payload = read("grafana/dashboards/radiation-monitoring.json")
    assert "FROM alarm" in payload or "FROM `alarm`" in payload
