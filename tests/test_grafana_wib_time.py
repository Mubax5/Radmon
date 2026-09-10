from __future__ import annotations

from radmon.grafana_tv import build_dashboard_payloads


def _panel(dashboard, *, description=None, title=None):
    for item in dashboard["panels"]:
        if description is not None and item.get("description") == description:
            return item
        if title is not None and item.get("title") == title:
            return item
    raise AssertionError(f"panel not found: {description or title}")


def test_realtime_sparkline_filters_local_wib_datetimes_by_epoch():
    realtime = build_dashboard_payloads()[0]
    sparkline = _panel(realtime, description="latest-dose-sparkline")
    sql = sparkline["targets"][0]["rawSql"]
    assert "CONVERT_TZ(m.dtom, '+07:00', '+00:00')" in sql
    assert "$__unixEpochFrom()" in sql
    assert "$__unixEpochTo()" in sql
    assert "$__timeFilter(m.dtom)" not in sql


def test_realtime_measurement_time_converts_wib_datetime_to_absolute_epoch():
    realtime = build_dashboard_payloads()[0]
    time_panel = _panel(realtime, description="latest-measurement-time")
    sql = time_panel["targets"][0]["rawSql"]
    assert "CONVERT_TZ(dtom, '+07:00', '+00:00')" in sql
    assert "TIMESTAMPDIFF" in sql


def test_operation_offline_check_compares_source_datetime_to_wib_now():
    operations = build_dashboard_payloads()[2]
    table = _panel(operations, description="operational-condition")
    sql = table["targets"][0]["rawSql"]
    assert "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')" in sql
    assert "TIMESTAMPDIFF(SECOND, dtom, NOW())" not in sql


def test_trend_query_uses_wib_to_utc_numeric_epoch_filter():
    trends = build_dashboard_payloads()[1]
    trend = _panel(trends, description="building-dose-trend")
    sql = trend["targets"][0]["rawSql"]
    assert "CONVERT_TZ(m.dtom, '+07:00', '+00:00')" in sql
    assert "$__unixEpochFrom()" in sql
    assert "$__unixEpochTo()" in sql
