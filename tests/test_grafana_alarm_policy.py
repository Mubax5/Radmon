import inspect

from radmon.grafana_tv import build_dashboard_payloads
from radmon.recent_read_model import RollingRecentManager


def test_operation_status_consumes_runtime_policy_projected_by_vrecent():
    operation = build_dashboard_payloads()[2]
    table = next(p for p in operation["panels"] if p.get("description") == "operational-condition")
    sql = table["targets"][0]["rawSql"]

    assert "FROM vrecent" in sql
    assert "radmon_runtime_status" not in sql
    assert "underlying_status" in sql
    assert "status" in sql.lower()
    assert "trigger_count" in sql
    assert "retrigger_locked" in sql
    assert "suppression_expires_at" in sql
    assert "doserate" in sql.lower()
    assert "FIELD(s.status, 'OFFLINE' COLLATE utf8mb4_uca1400_ai_ci, 'SUPPRESSED' COLLATE utf8mb4_uca1400_ai_ci, 'ALARM' COLLATE utf8mb4_uca1400_ai_ci, 'ALERT' COLLATE utf8mb4_uca1400_ai_ci, 'NORMAL' COLLATE utf8mb4_uca1400_ai_ci)" in sql

    view_source = inspect.getsource(RollingRecentManager._create_view)
    assert "radmon_runtime_status" in view_source
    assert "underlying_dose_status" in view_source
    assert "suppressed" in view_source


def test_wib_epoch_conversion_is_still_present():
    payload = str(build_dashboard_payloads())
    assert "CONVERT_TZ" in payload
    assert "+07:00" in payload
