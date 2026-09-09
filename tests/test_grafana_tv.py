import json
from pathlib import Path

from radmon.grafana_tv import (
    BUILDING_PAGE_ORDER,
    DASHBOARD_FILES,
    DASHBOARD_UIDS,
    OPERATIONS_PAGE_COUNT,
    OPERATIONS_PAGE_UIDS,
    PAGE_UIDS,
    PLAYLIST_INTERVAL,
    PLAYLIST_UID,
    build_dashboard_payloads,
    build_playlist_payload,
    operation_page_stations,
    playlist_url,
)
from radmon.stations import station_catalog


def _panel_by_title(dashboard, title):
    return next(panel for panel in dashboard["panels"] if panel.get("title") == title)


def test_playlist_keeps_three_logical_pages_and_advances_operations_subpage_each_rotation():
    payload = build_playlist_payload()
    assert PLAYLIST_INTERVAL == "10s"
    assert len(PAGE_UIDS) == 3
    assert OPERATIONS_PAGE_COUNT == 5
    assert len(OPERATIONS_PAGE_UIDS) == 5
    assert payload["metadata"]["name"] == PLAYLIST_UID
    assert payload["spec"]["interval"] == "10s"

    values = [item["value"] for item in payload["spec"]["items"]]
    assert len(values) == 15
    for index, operations_uid in enumerate(OPERATIONS_PAGE_UIDS):
        assert values[index * 3 : index * 3 + 3] == [PAGE_UIDS[0], PAGE_UIDS[1], operations_uid]

    url = playlist_url("http://localhost:3000")
    assert f"/playlists/play/{PLAYLIST_UID}" in url
    assert "kiosk=1" in url
    assert "autofitpanels" in url
    assert "_dash.hidePlaylistNav=true" in url
    assert "_dash.hideTimePicker=true" in url
    assert "_dash.hideVariables=true" in url


def test_every_generated_dashboard_has_identical_two_panel_header_and_fits_without_scroll():
    dashboards = build_dashboard_payloads()
    assert len(dashboards) == 7
    assert [dashboard["uid"] for dashboard in dashboards] == list(DASHBOARD_UIDS)
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
    operations = [panel for panel in page1["panels"] if panel.get("description") == "operational-condition"]
    assert len(dose) == 15
    assert len(spark) == 15
    assert len(timestamp) == 15
    assert operations == []
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
        assert panel["fieldConfig"]["defaults"]["unit"] == "time:DD/MM/YYYY HH:mm:ss"


def test_page_two_uses_readable_building_small_multiples_and_has_no_operations_table():
    page2 = build_dashboard_payloads()[1]
    trends = [panel for panel in page2["panels"] if panel.get("description") == "building-dose-trend"]
    operations = [panel for panel in page2["panels"] if panel.get("description") == "operational-condition"]
    assert operations == []
    assert len(trends) == 5
    assert {panel["title"] for panel in trends} == {f"Dose Rate · Gedung {building} · 3 Jam" for building in BUILDING_PAGE_ORDER}
    for panel in trends:
        assert panel["gridPos"]["h"] <= 5
        custom = panel["fieldConfig"]["defaults"]["custom"]
        defaults = panel["fieldConfig"]["defaults"]
        assert custom["fillOpacity"] == 0
        assert custom["lineWidth"] == 1
        assert defaults["unit"] == "suffix: µSv/h"
        assert defaults["min"] == 0
        assert defaults["max"] == 1
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
                assert panel["options"]["text"]["valueSize"] >= 40
    assert seen == wanted


def test_only_operations_logical_page_rotates_five_detector_subpages_with_three_rows_each():
    dashboards = build_dashboard_payloads()
    assert all(panel.get("description") != "operational-condition" for dashboard in dashboards[:2] for panel in dashboard["panels"])

    operations_dashboards = dashboards[2:]
    assert len(operations_dashboards) == 5
    for page_number, dashboard in enumerate(operations_dashboards, start=1):
        operations = [panel for panel in dashboard["panels"] if panel.get("description") == "operational-condition"]
        assert len(operations) == 1
        assert f"Page {page_number}/5" in operations[0]["title"]
        sql = operations[0]["targets"][0]["rawSql"]
        assert "FROM measurement" in sql
        assert " recent " not in sql.lower()

    chunks = [operation_page_stations(page_number) for page_number in range(1, 6)]
    flattened = [station.serid for chunk in chunks for station in chunk]
    expected = [station.serid for station in station_catalog()]
    assert flattened == expected
    assert len(flattened) == len(set(flattened)) == 15
    assert all(len(chunk) == 3 for chunk in chunks)


def test_operations_variants_keep_same_page_three_content_except_detector_table_slice():
    operations_dashboards = build_dashboard_payloads()[2:]
    for page_number, dashboard in enumerate(operations_dashboards, start=1):
        payload = json.dumps(dashboard, ensure_ascii=False)
        assert dashboard["title"] == "RadMon TV · Operations"
        assert "Status Detector" in payload
        assert f"Kondisi Operasional Detector · Page {page_number}/5" in payload
        assert "Alarm Terbaru · 24 Jam" in payload
        assert "OFFLINE" in payload and "ALARM" in payload and "ALERT" in payload and "NORMAL" in payload
        assert "piechart" in payload


def test_dashboard_file_contract_has_two_shared_pages_and_five_operations_variants():
    assert DASHBOARD_FILES[:2] == (
        "radmon-tv-page-1-realtime.json",
        "radmon-tv-page-2-trends.json",
    )
    assert len(DASHBOARD_FILES) == 7
    assert len(set(DASHBOARD_FILES)) == 7
    assert all(name.startswith("radmon-tv-page-3-operations-") for name in DASHBOARD_FILES[2:])


def test_dashboard_payloads_are_generated_at_runtime_not_duplicated_as_static_json():
    root = Path(__file__).resolve().parents[1]
    assert len(build_dashboard_payloads()) == 7
    for filename in DASHBOARD_FILES:
        assert not (root / "grafana" / "dashboards" / filename).exists()
    assert not (root / "grafana" / "dashboards" / "radiation-monitoring.json").exists()
