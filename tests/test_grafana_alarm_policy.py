from radmon.grafana_tv import build_dashboard_payloads


def test_operation_status_joins_runtime_policy_and_keeps_underlying_dose():
    operation = build_dashboard_payloads()[2]
    table = next(p for p in operation["panels"] if p.get("description") == "operational-condition")
    sql = table["targets"][0]["rawSql"]
    assert "radmon_runtime_status" in sql
    assert "SUPPRESSED" in sql
    assert "underlying" in sql.lower()
    assert "doserate" in sql.lower()
    assert "FIELD(s.status, 'OFFLINE', 'SUPPRESSED', 'ALARM', 'ALERT', 'NORMAL')" in sql


def test_wib_epoch_conversion_is_still_present():
    payload = str(build_dashboard_payloads())
    assert "CONVERT_TZ" in payload
    assert "+07:00" in payload
