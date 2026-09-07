import json
from pathlib import Path

from radmon.grafana_tv import (
    BUILDING_PAGE_ORDER,
    DASHBOARD_FILES,
    PAGE_UIDS,
    PLAYLIST_INTERVAL,
    PLAYLIST_UID,
    build_dashboard_payloads,
    build_playlist_payload,
    playlist_url,
)


def _panel_by_title(dashboard, title):
    return next(panel for panel in dashboard["panels"] if panel.get("title") == title)


def test_playlist_cycles_eight_pages_every_ten_seconds_in_kiosk_autofit():
    payload = build_playlist_payload()
    assert PLAYLIST_INTERVAL == "10s"
    assert len(PAGE_UIDS) == 8
    assert payload["metadata"]["name"] == PLAYLIST_UID
    assert payload["spec"]["interval"] == "10s"
    assert [item["value"] for item in payload["spec"]["items"]] == list(PAGE_UIDS)
    url = playlist_url("http://localhost:3000")
    assert f"/playlists/play/{PLAYLIST_UID}" in url
    assert "kiosk=1" in url
    assert "autofitpanels" in url
    assert "_dash.hidePlaylistNav=true" in url
    assert "_dash.hideTimePicker=true" in url
    assert "_dash.hideVariables=true" in url


def test_every_tv_page_has_identical_two_panel_header_and_fits_without_scroll():
    dashboards = build_dashboard_payloads()
    assert len(dashboards) == 8
    headers = []
    for dashboard in dashboards:
        assert dashboard["refresh"] == "2s"
        assert dashboard["timezone"] == "browser"
        assert dashboard["time"]["to"] == "now"
        assert dashboard["templating"]["list"] == []
        max_bottom = max(panel["gridPos"]["y"] + panel["gridPos"]["h"] for panel in dashboard["panels"])
        assert max_bottom <= 24
        first, second = dashboard["panels"][:2]
        headers.append((first["options"]["content"], second["options"]["content"]))
    assert len(set(headers)) == 1
    assert "REAL TIME DOSE RATE MONITORING SYSTEM" in headers[0][0]
    assert "Instalasi Pengelolaan Limbah Radioaktif" in headers[0][1]


def test_page_one_keeps_dose_as_main_focus_with_separate_short_sparkline_and_small_time():
    page1 = build_dashboard_payloads()[0]
    dose = [panel for panel in page1["panels"] if panel.get("title", "").startswith("[")]
    spark = [panel for panel in page1["panels"] if panel.get("description") == "latest-dose-sparkline"]
    timestamp = [panel for panel in page1["panels"] if panel.get("description") == "latest-measurement-time"]
    assert len(dose) == 15
    assert len(spark) == 15
    assert len(timestamp) == 15
    for panel in dose:
        assert panel["type"] == "stat"
        assert panel["gridPos"]["h"] == 2
        assert panel["options"]["graphMode"] == "none"
        assert panel["options"]["text"]["valueSize"] >= 28
        assert panel["fieldConfig"]["defaults"]["unit"] == "suffix: µSv/h"
        assert "FROM measurement" in panel["targets"][0]["rawSql"]
    for panel in spark:
        assert panel["type"] == "timeseries"
        assert panel["gridPos"]["h"] == 1
        custom = panel["fieldConfig"]["defaults"]["custom"]
        assert custom["fillOpacity"] <= 20
        assert custom["lineWidth"] == 1
        assert panel["options"]["legend"]["showLegend"] is False
    for panel in timestamp:
        assert panel["gridPos"]["h"] == 1
        assert panel["options"]["text"]["valueSize"] <= 12
        sql = panel["targets"][0]["rawSql"]
        assert "UNIX_TIMESTAMP(MAX(m.dtom)) * 1000" in sql
        assert "DATE_FORMAT" not in sql
        assert panel["fieldConfig"]["defaults"]["unit"] == "dateTimeAsLocal"


def test_page_two_uses_readable_building_small_multiples_instead_of_one_fifteen_series_wall():
    page2 = build_dashboard_payloads()[1]
    trends = [panel for panel in page2["panels"] if panel.get("description") == "building-dose-trend"]
    assert len(trends) == 5
    assert {panel["title"] for panel in trends} == {f"Dose Rate · Gedung {building} · 3 Jam" for building in BUILDING_PAGE_ORDER}
    for panel in trends:
        assert panel["gridPos"]["h"] <= 5
        custom = panel["fieldConfig"]["defaults"]["custom"]
        assert custom["fillOpacity"] == 0
        assert custom["lineWidth"] == 1
        assert panel["fieldConfig"]["defaults"]["unit"] == "suffix: µSv/h"
        assert "$__timeFilter(m.dtom)" in panel["targets"][0]["rawSql"]


def test_integer_summary_stats_have_no_trailing_decimal_places():
    dashboards = build_dashboard_payloads()
    wanted = {"Detector Online", "Detector Offline", "NORMAL", "ALERT", "ALARM", "OFFLINE"}
    seen = set()
    for dashboard in dashboards:
        for panel in dashboard["panels"]:
            if panel.get("title") in wanted:
                seen.add(panel["title"])
                assert panel["fieldConfig"]["defaults"]["decimals"] == 0
    assert seen == wanted


def test_operational_condition_rotates_across_all_eight_pages():
    dashboards = build_dashboard_payloads()
    assert len(dashboards) == 8
    for page_number, dashboard in enumerate(dashboards, start=1):
        operations = [panel for panel in dashboard["panels"] if panel.get("description") == "operational-condition"]
        assert operations, f"page {page_number} is missing operational condition"
        assert any(f"Page {page_number}/8" in panel["title"] for panel in operations)
        for panel in operations:
            assert "FROM measurement" in panel["targets"][0]["rawSql"]
            assert " recent " not in panel["targets"][0]["rawSql"].lower()


def test_building_detail_pages_cover_all_five_buildings_with_current_value_trend_and_condition():
    dashboards = build_dashboard_payloads()[3:]
    assert len(dashboards) == 5
    for building, dashboard in zip(BUILDING_PAGE_ORDER, dashboards):
        payload = json.dumps(dashboard, ensure_ascii=False)
        assert f"Gedung {building}" in dashboard["title"]
        assert "latest-measurement-time" in payload
        assert "building-dose-trend" in payload
        assert "operational-condition" in payload


def test_page_three_status_is_derived_from_latest_measurement_not_recent_table():
    page3 = build_dashboard_payloads()[2]
    payload = json.dumps(page3, ensure_ascii=False)
    assert "Status Detector" in payload
    assert "Kondisi Operasional Detector · Page 3/8" in payload
    assert "FROM measurement" in payload
    assert " recent " not in payload.lower()
    assert "OFFLINE" in payload and "ALARM" in payload and "ALERT" in payload and "NORMAL" in payload
    assert "piechart" in payload


def test_dashboard_file_contract_has_eight_distinct_page_names():
    assert set(DASHBOARD_FILES) == {
        "radmon-tv-page-1-realtime.json",
        "radmon-tv-page-2-trends.json",
        "radmon-tv-page-3-operations.json",
        "radmon-tv-page-4-building-50.json",
        "radmon-tv-page-5-building-38.json",
        "radmon-tv-page-6-building-52.json",
        "radmon-tv-page-7-building-55.json",
        "radmon-tv-page-8-building-57.json",
    }


def test_dashboard_payloads_are_generated_at_runtime_not_duplicated_as_static_json():
    root = Path(__file__).resolve().parents[1]
    assert len(build_dashboard_payloads()) == 8
    for filename in DASHBOARD_FILES:
        assert not (root / "grafana" / "dashboards" / filename).exists()
    assert not (root / "grafana" / "dashboards" / "radiation-monitoring.json").exists()
