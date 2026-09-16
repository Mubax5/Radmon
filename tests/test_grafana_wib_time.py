from __future__ import annotations

import inspect

from radmon.grafana_tv import build_dashboard_payloads
from radmon.recent_read_model import RollingRecentManager


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
    # Indexed recent scan: $__timeFilter(dtom) is a PK range in the session
    # timezone (Asia/Jakarta on the central DB), and UNIX_TIMESTAMP(dtom) is
    # numerically identical to the legacy CONVERT_TZ WIB epoch.
    assert "FROM recent" in sql
    assert "UNIX_TIMESTAMP(dtom)" in sql
    assert "$__timeFilter(dtom)" in sql
    assert "CONVERT_TZ" not in sql
    assert "$__unixEpochFrom()" not in sql


def test_realtime_measurement_time_converts_wib_datetime_to_absolute_epoch():
    realtime = build_dashboard_payloads()[0]
    time_panel = _panel(realtime, description="latest-measurement-time")
    sql = time_panel["targets"][0]["rawSql"]
    assert "CONVERT_TZ(dtom, '+07:00', '+00:00')" in sql
    assert "TIMESTAMPDIFF" in sql


def test_operation_offline_check_is_projected_by_vrecent_using_wib_now():
    operations = build_dashboard_payloads()[2]
    table = _panel(operations, description="operational-condition")
    sql = table["targets"][0]["rawSql"]
    assert "FROM vrecent" in sql
    assert "s.status" in sql
    assert "TIMESTAMPDIFF(SECOND, dtom, NOW())" not in sql

    view_source = inspect.getsource(RollingRecentManager._create_view)
    assert "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')" in view_source
    assert "TIMESTAMPDIFF(" in view_source
    assert "r.dtom" in view_source
    assert "maxidlemin" in view_source


def test_trend_query_uses_wib_to_utc_numeric_epoch_filter():
    trends = build_dashboard_payloads()[1]
    trend = _panel(trends, description="building-dose-trend")
    sql = trend["targets"][0]["rawSql"]
    assert "FROM recent r" in sql
    assert "UNIX_TIMESTAMP(r.dtom)" in sql
    assert "$__timeFilter(r.dtom)" in sql
    assert "CONVERT_TZ" not in sql
    assert "$__unixEpochFrom()" not in sql
