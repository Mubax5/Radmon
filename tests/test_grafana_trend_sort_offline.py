"""Regression: trends wide-series sort + offline last-data inside time range.

Bukti user:
- trends: "failed to convert long to wide series... not sorted in ascending order by time"
- realtime offline (3001-3004 stale 15 Sep, 5701 Jun) "Data outside time range" padahal
  wajib tampilkan data terakhir termasuk grafik page1. Page2 disesuaikan, page3 sisanya.
- loading 20s+ wajib 1-3s. Manfaatkan vrecent/recent, jangan scan measurement 33jt.

Kontrak:
- semua target time_series (wide-series) wajib ORDER BY time ASC eksplisit.
- spark page1 + tren page2 wajib punya fallback last-known TANPA $__timeFilter
  yang memproyeksikan waktu ke dalam range dashboard via $__unixEpochTo()/From()
  (bukan UNIX_TIMESTAMP(dtom) tua di luar range) sehingga offline tetap tampil.
- spark LIMIT 100-300, tren per-menit LIMIT <= 2000, tanpa CONVERT_TZ per-baris,
  tanpa FROM measurement, newest dari recent (PK) bukan vrecent.
"""

from __future__ import annotations

import re


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
    assert sql
    return sql


def _limit_value(sql: str) -> int:
    m = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
    assert m, f"expected LIMIT in: {sql[:160]}"
    return int(m.group(1))


def test_no_panel_scans_measurement_33jt():
    for sql in _all_raw_sql():
        assert "FROM measurement" not in sql, f"must not scan 33jt measurement: {sql[:160]}"


def test_wide_series_targets_sort_time_asc_explicit():
    checked = 0
    for dashboard in build_dashboard_payloads():
        for panel in dashboard["panels"]:
            for target in panel.get("targets") or []:
                if target.get("format") != "time_series":
                    continue
                sql = target.get("rawSql") or ""
                checked += 1
                # Grafana long->wide conversion gagal bila time tidak ASC eksplisit.
                assert re.search(r"ORDER\s+BY\s+[^\n;]*\bASC\b", sql, re.IGNORECASE), (
                    f"time_series must ORDER BY ... ASC explicit: {sql[:200]}"
                )
    assert checked >= 20, f"expected >=20 time_series targets, got {checked}"


def test_page1_sparkline_offline_last_data_inside_range():
    sparks = _panels("latest-dose-sparkline")
    assert len(sparks) == 15
    for panel in sparks:
        targets = panel.get("targets") or []
        assert len(targets) == 2, "sparkline wajib main + fallback offline"
        main, fallback = targets[0]["rawSql"], targets[1]["rawSql"]
        # Main ringan: recent + timefilter + limit kecil, tanpa CONVERT_TZ berat.
        assert "FROM recent" in main
        assert "$__timeFilter(dtom)" in main
        assert "CONVERT_TZ" not in main
        assert 100 <= _limit_value(main) <= 300
        # Fallback offline: tanpa timefilter, proyeksikan ke dalam range
        # via $__unixEpochTo/From (bukan timestamp tua di luar range).
        assert "FROM recent" in fallback
        assert "$__timeFilter" not in fallback
        assert ("$__unixEpochTo()" in fallback or "$__unixEpochFrom()" in fallback), (
            f"offline fallback must project inside range via $__unixEpochTo/From: {fallback[:200]}"
        )
        assert "LIMIT 1" in fallback or "LIMIT 2" in fallback


def test_page2_trend_offline_last_data_inside_range_and_bounded():
    trends = _panels("building-dose-trend")
    assert len(trends) == 5
    for panel in trends:
        targets = panel.get("targets") or []
        assert len(targets) == 2, "trend wajib main + fallback offline"
        main, fallback = targets[0]["rawSql"], targets[1]["rawSql"]
        assert "FROM recent" in main
        assert "$__timeFilter(" in main
        assert "GROUP BY" in main
        assert "CONVERT_TZ" not in main
        assert _limit_value(main) <= 2000, f"trend per-menit wajib LIMIT rendah: {main[:200]}"
        assert "FROM measurement" not in fallback
        assert "$__timeFilter" not in fallback
        assert ("$__unixEpochTo()" in fallback or "$__unixEpochFrom()" in fallback), (
            f"trend fallback must project inside range: {fallback[:200]}"
        )
        assert "LIMIT" in fallback
