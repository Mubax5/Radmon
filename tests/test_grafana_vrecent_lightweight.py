"""Grafana panels must stay 100% working and lightweight via vrecent/recent.

Regression contract for the No-Data + heavy-query incident:
- live/realtime single-value panels read vrecent (never measurement full-scan)
  and must return an offline (NULL) row instead of zero rows for detectors
  without recent samples;
- time-series panels (sparklines/trends) read the narrow indexed ``recent``
  table with an index-friendly ``$__timeFilter(dtom)`` range and a LIMIT
  guardrail, without per-row CONVERT_TZ range filters;
- no generated panel may full-scan ``measurement`` (32M+ rows).
"""

from __future__ import annotations

import inspect

from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.config import Settings
from radmon.grafana_tv import build_dashboard_payloads
from radmon.recent_read_model import RollingRecentManager


def _all_raw_sql() -> list[str]:
    sql: list[str] = []
    for dashboard in build_dashboard_payloads():
        for panel in dashboard["panels"]:
            for target in panel.get("targets") or []:
                raw = target.get("rawSql")
                if raw:
                    sql.append(raw)
    assert sql, "expected dashboard panels with rawSql"
    return sql


def _panels(description: str) -> list[dict]:
    found = []
    for dashboard in build_dashboard_payloads():
        for panel in dashboard["panels"]:
            if panel.get("description") == description:
                found.append(panel)
    assert found, f"no panels with description {description!r}"
    return found


def test_no_panel_queries_full_scan_measurement():
    for sql in _all_raw_sql():
        assert "FROM measurement" not in sql
        assert "measurement_history(" not in sql


def test_live_dose_panels_use_vrecent_and_return_offline_row():
    dose = [
        panel
        for dashboard in build_dashboard_payloads()
        for panel in dashboard["panels"]
        if panel.get("title", "").startswith("[")
    ]
    assert len(dose) == 15
    for panel in dose:
        sql = panel["targets"][0]["rawSql"]
        assert "FROM vrecent" in sql
        # Detectors without recent samples still expose one vrecent row with
        # NULL doserate; filtering it out turns OFFLINE into No Data.
        assert "dtom IS NOT NULL" not in sql
        assert "ORDER BY dtom DESC" in sql
        assert "LIMIT 1" in sql


def test_live_time_panels_use_vrecent_and_return_offline_row():
    for panel in _panels("latest-measurement-time"):
        sql = panel["targets"][0]["rawSql"]
        assert "FROM vrecent" in sql
        assert "dtom IS NOT NULL" not in sql
        assert "ORDER BY dtom DESC" in sql
        assert "LIMIT 1" in sql


def test_sparklines_use_indexed_recent_with_timefilter():
    spark = _panels("latest-dose-sparkline")
    assert len(spark) == 15
    for panel in spark:
        sql = panel["targets"][0]["rawSql"]
        assert "FROM recent" in sql
        assert "FROM vrecent" not in sql
        assert "FROM measurement" not in sql
        assert "$__timeFilter(dtom)" in sql
        assert "CONVERT_TZ" not in sql
        assert "UNIX_TIMESTAMP(dtom)" in sql
        assert "LIMIT" in sql


def test_building_trends_use_lightweight_aggregation_over_recent():
    trends = _panels("building-dose-trend")
    assert len(trends) == 5
    for panel in trends:
        sql = panel["targets"][0]["rawSql"]
        assert "FROM measurement" not in sql
        # Aggregated recent rows (or vrecent) keep the 3h trend bounded and
        # cheap; raw per-sample scans of the 51k-row view are not allowed.
        assert "FROM recent" in sql or "FROM vrecent" in sql
        assert "$__timeFilter(" in sql
        assert "CONVERT_TZ" not in sql or "$__timeFilter(" in sql
        assert "BETWEEN $__unixEpochFrom() AND $__unixEpochTo()" not in sql
        assert "GROUP BY" in sql
        assert "LIMIT" in sql


def test_vrecent_view_exposes_dashboard_contract_columns():
    source = inspect.getsource(RollingRecentManager._create_view)
    for column in (
        "serid",
        "name",
        "location",
        "dtom",
        "doserate",
        "dose",
        "underlying_status",
        "status",
        "suppressed",
        "trigger_count",
        "retrigger_locked",
    ):
        assert column in source


def test_datasource_payload_always_carries_active_password():
    settings = Settings(db_host="127.0.0.1", db_password="current-secret")
    payload = GrafanaBootstrap(settings)._datasource_payload()
    assert payload["uid"] == "ipradmon-mysql"
    assert payload["secureJsonData"]["password"] == "current-secret"
