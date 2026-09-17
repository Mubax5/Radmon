"""Offline last-known + lightweight regression contract.

User contract:
- Grafana + admin panel wajib tampilkan data TERAKHIR jika offline,
  termasuk grafik page 1. Page 2 disesuaikan, page 3 sisanya.
- Page 1 grafik pakai recent + $__timeFilter + latest-10.
- Page 2 tren pakai agregasi per-menit dari recent + LIMIT <= 600,
  dengan fallback last-known jika offline.
- Status/offline logic terpusat di vrecent (panel tidak menduplikasi
  CASE status; subquery latest yang berat wajib dari recent berindeks,
  bukan full-scan view vrecent / measurement).
"""

from __future__ import annotations

import inspect
import re

from radmon import repository as repository_module
from radmon.grafana_tv import build_dashboard_payloads


def _panels(description: str) -> list[dict]:
    found = []
    for dashboard in build_dashboard_payloads():
        for panel in dashboard["panels"]:
            if panel.get("description") == description:
                found.append(panel)
    assert found, f"no panels with description {description!r}"
    return found


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


def _limit_value(sql: str) -> int:
    match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
    assert match, f"expected LIMIT guardrail in: {sql[:160]}"
    return int(match.group(1))


def test_page1_sparkline_is_lightweight_with_offline_fallback():
    spark = _panels("latest-dose-sparkline")
    assert len(spark) == 15
    for panel in spark:
        targets = panel.get("targets") or []
        # Main lightweight window + dedicated last-known fallback so an
        # offline detector keeps its last point instead of No Data.
        assert len(targets) == 2, "sparkline must carry main + offline fallback targets"
        main, fallback = targets[0]["rawSql"], targets[1]["rawSql"]
        assert "FROM recent" in main
        assert "FROM vrecent" not in main
        assert "FROM measurement" not in main
        assert "$__timeFilter(dtom)" in main
        assert "CONVERT_TZ" not in main
        assert _limit_value(main) <= 300
        assert "FROM recent" in fallback
        assert "FROM measurement" not in fallback
        assert "$__timeFilter" not in fallback
        assert "ORDER BY dtom DESC" in fallback
        assert "LIMIT 1" in fallback


def test_page1_stat_panels_show_offline_last_known():
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
        assert "dtom IS NOT NULL" not in sql
        assert "LIMIT 1" in sql


def test_page2_trends_bounded_with_offline_fallback():
    trends = _panels("building-dose-trend")
    assert len(trends) == 5
    for panel in trends:
        targets = panel.get("targets") or []
        assert len(targets) == 2, "trend must carry main + offline fallback targets"
        main, fallback = targets[0]["rawSql"], targets[1]["rawSql"]
        assert "FROM measurement" not in main
        assert "FROM recent" in main
        assert "$__timeFilter(" in main
        assert "GROUP BY" in main
        assert _limit_value(main) <= 600
        assert "FROM measurement" not in fallback
        assert "$__timeFilter" not in fallback
        assert "LIMIT" in fallback


def test_latest_relations_use_indexed_recent_for_newest():
    source = inspect.getsource(__import__("radmon.grafana_tv", fromlist=["x"])._latest_vrecent_relation)
    assert "MAX(dtom)" in source
    # The newest-dtom subquery must hit the narrow indexed recent table,
    # never the 40k-row vrecent view (per-row CONVERT_TZ + double joins).
    assert "FROM recent" in source
    assert source.count("FROM vrecent") == 1, "only the outer status query may read vrecent"
    assert "FROM measurement" not in source


def test_status_logic_stays_centralized_in_vrecent():
    for sql in _all_raw_sql():
        # Panels must reuse vrecent.status, never duplicate the idle/
        # threshold CASE logic inline. (TIMESTAMPDIFF(MICROSECOND, ...)
        # epoch conversion for the time panel is presentation, not
        # status logic; the SECOND-based idle check belongs to the view.)
        assert "TIMESTAMPDIFF(SECOND" not in sql.upper().replace(" ", ""), (
            f"panel duplicates offline idle logic: {sql[:160]}"
        )
        assert "MAXIDLEMIN" not in sql.upper() or "COALESCE(v.maxidlemin" in sql or "COALESCE(s.maxidlemin" in sql, (
            f"panel duplicates idle threshold logic: {sql[:160]}"
        )
    view_source = inspect.getsource(
        __import__("radmon.recent_read_model", fromlist=["x"]).RollingRecentManager._create_view
    )
    assert "WHEN r.dtom IS NULL" in view_source
    assert "AS status" in view_source


def test_admin_live_rows_keep_offline_detectors():
    source = inspect.getsource(repository_module.MariaDBRepository.live_rows)
    assert "FROM measurement" not in source
    # INNER JOIN newest drops fully-offline detectors (no recent rows);
    # admin panel must keep them via LEFT JOIN with last-known data.
    assert "LEFT JOIN" in source
    assert "JOIN (" not in source.replace("LEFT JOIN (", "")
