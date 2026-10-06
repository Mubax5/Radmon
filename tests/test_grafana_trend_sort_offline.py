"""Contracts for useful, timestamped Grafana trends and offline cards."""

from __future__ import annotations

import re

from radmon.grafana_tv import build_dashboard_payloads


def _dashboard(index: int) -> dict:
    return build_dashboard_payloads()[index]


def _panels(dashboard: dict, description: str) -> list[dict]:
    return [p for p in dashboard["panels"] if p.get("description") == description]


def test_page1_uses_full_30m_window_and_real_sample_count():
    page = _dashboard(0)
    assert page["time"] == {"from": "now-30m", "to": "now"}
    assert page["refresh"] == "5s"
    trends = _panels(page, "latest-dose-sparkline")
    assert len(trends) == 15
    for panel in trends:
        targets = panel["targets"]
        assert len(targets) == 1
        sql = targets[0]["rawSql"]
        assert "$__unixEpochFrom()" in sql and "$__unixEpochTo()" in sql
        assert "TIMESTAMPADD(SECOND" in sql
        assert "FROM recent" in sql
        assert "LIMIT 300" in sql
        assert re.search(r"ORDER\s+BY\s+time\s+ASC", sql, re.I)
        assert "$__unixEpochFrom() AS time" not in sql
        assert "$__unixEpochTo() AS time" not in sql
        assert panel["fieldConfig"]["defaults"]["decimals"] == 2
        assert panel["fieldConfig"]["defaults"]["noValue"] == "No recent trend"
        assert panel["fieldConfig"]["defaults"]["custom"]["spanNulls"] is False


def test_page2_uses_one_hour_actual_sorted_samples_only():
    page = _dashboard(1)
    assert page["time"] == {"from": "now-1h", "to": "now"}
    trends = _panels(page, "building-dose-trend")
    assert len(trends) == 5
    for panel in trends:
        assert len(panel["targets"]) == 1
        sql = panel["targets"][0]["rawSql"]
        assert "$__unixEpochFrom()" in sql and "$__unixEpochTo()" in sql
        assert "FROM recent" in sql and "GROUP BY" in sql
        assert "ORDER BY time ASC" in sql
        assert "$__unixEpochFrom() AS time" not in sql
        assert "$__unixEpochTo() AS time" not in sql
        assert panel["fieldConfig"]["defaults"]["decimals"] == 2
        assert panel["fieldConfig"]["defaults"]["noValue"] == "No recent trend"


def test_page1_card_layout_status_dose_then_full_width_trend():
    page = _dashboard(0)
    lamps = _panels(page, "central-status-lamp")
    doses = _panels(page, "latest-dose-value")
    trends = _panels(page, "latest-dose-sparkline")
    assert len(lamps) == len(doses) == len(trends) == 15
    for lamp, dose, trend in zip(lamps, doses, trends):
        assert lamp["gridPos"]["y"] < dose["gridPos"]["y"] < trend["gridPos"]["y"]
        assert lamp["gridPos"]["x"] == dose["gridPos"]["x"] == trend["gridPos"]["x"]
        assert lamp["gridPos"]["w"] == dose["gridPos"]["w"] == trend["gridPos"]["w"]
        assert trend["gridPos"]["h"] >= 3
        assert dose["fieldConfig"]["defaults"]["decimals"] == 2
        assert "FROM vrecent" in dose["targets"][0]["rawSql"]


def test_every_time_series_is_ascending_and_does_not_scan_measurement():
    checked = 0
    for dashboard in build_dashboard_payloads():
        for panel in dashboard["panels"]:
            for target in panel.get("targets") or []:
                sql = target.get("rawSql") or ""
                assert "FROM measurement" not in sql
                if target.get("format") == "time_series":
                    checked += 1
                    assert re.search(r"ORDER\s+BY\s+[^\n;]*\bASC\b", sql, re.I)
    assert checked >= 20
