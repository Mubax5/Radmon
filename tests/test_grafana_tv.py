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


def test_every_generated_dashboard_has_shared_header_and_fits_without_scroll():
    dashboards = build_dashboard_payloads()
    assert len(dashboards) == 7
    assert [dashboard["uid"] for dashboard in dashboards] == list(DASHBOARD_UIDS)
    for dashboard in dashboards:
        assert dashboard["refresh"] == "2s"
        assert dashboard["time"]["to"] == "now"
        assert dashboard["templating"]["list"] == []
        max_bottom = max(panel["gridPos"]["y"] + panel["gridPos"]["h"] for panel in dashboard["panels"])
        assert max_bottom <= 24
        payload = json.dumps(dashboard, ensure_ascii=False)
        assert "REAL TIME DOSE RATE MONITORING SYSTEM" in payload
        assert "Instalasi Pengelolaan Limbah Radioaktif" in payload


def test_page_one_live_values_and_times_use_vrecent_but_sparkline_keeps_measurement_history():
    page1 = build_dashboard_payloads()[0]
    dose = [panel for panel in page1["panels"] if panel.get("title", "").startswith("[")]
    spark = [panel for panel in page1["panels"] if panel.get("description") == "latest-dose-sparkline"]
    timestamp = [panel for panel in page1["panels"] if panel.get("description") == "latest-measurement-time"]
    assert len(dose) == len(spark) == len(timestamp) == 15
    for panel in dose:
        assert panel["type"] == "stat"
        assert "FROM vrecent" in panel["targets"][0]["rawSql"]
        assert panel["fieldConfig"]["defaults"]["unit"] == "suffix: µSv/h"
    for panel in spark:
        assert panel["type"] == "timeseries"
        sql = panel["targets"][0]["rawSql"]
        assert "FROM measurement" in sql
        assert "CONVERT_TZ(m.dtom, '+07:00', '+00:00')" in sql
        assert "$__unixEpochFrom()" in sql and "$__unixEpochTo()" in sql
    for panel in timestamp:
        sql = panel["targets"][0]["rawSql"]
        assert "FROM vrecent" in sql
        assert "TIMESTAMPDIFF" in sql
        assert "CONVERT_TZ(dtom, '+07:00', '+00:00')" in sql
        assert "DATE_FORMAT" not in sql
        assert panel["fieldConfig"]["defaults"]["unit"] == "time:DD/MM/YYYY HH:mm:ss"


def test_page_two_historical_trends_keep_measurement_and_live_summary_uses_vrecent():
    page2 = build_dashboard_payloads()[1]
    trends = [panel for panel in page2["panels"] if panel.get("description") == "building-dose-trend"]
    assert len(trends) == 5
    assert {panel["title"] for panel in trends} == {f"Dose Rate · Gedung {building} · 3 Jam" for building in BUILDING_PAGE_ORDER}
    for panel in trends:
        sql = panel["targets"][0]["rawSql"]
        assert "FROM measurement" in sql
        assert "CONVERT_TZ(m.dtom, '+07:00', '+00:00')" in sql
        assert "$__unixEpochFrom()" in sql and "$__unixEpochTo()" in sql
    summaries = {
        panel.get("title"): panel
        for panel in page2["panels"]
        if panel.get("title") in {"Dose Rate Tertinggi Saat Ini", "Rata-rata Saat Ini", "Detector Online", "Detector Offline"}
    }
    assert len(summaries) == 4
    assert all("vrecent" in panel["targets"][0]["rawSql"] for panel in summaries.values())


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


def test_operations_live_status_uses_vrecent_and_alarm_table_uses_legacy_schema():
    operations_dashboards = build_dashboard_payloads()[2:]
    assert len(operations_dashboards) == 5
    for page_number, dashboard in enumerate(operations_dashboards, start=1):
        operations = [panel for panel in dashboard["panels"] if panel.get("description") == "operational-condition"]
        assert len(operations) == 1
        assert f"Page {page_number}/5" in operations[0]["title"]
        assert "FROM vrecent" in operations[0]["targets"][0]["rawSql"]
        alarm = next(panel for panel in dashboard["panels"] if panel.get("title") == "Alarm Terbaru · 24 Jam")
        alarm_sql = alarm["targets"][0]["rawSql"]
        for column in ("dtoa", "lvl", "mvalue", "thvalue", "nhit", "i_op", "pic", "note"):
            assert column in alarm_sql

    chunks = [operation_page_stations(page_number) for page_number in range(1, 6)]
    flattened = [station.serid for chunk in chunks for station in chunk]
    expected = [station.serid for station in station_catalog()]
    assert flattened == expected
    assert len(flattened) == len(set(flattened)) == 15
    assert all(len(chunk) == 3 for chunk in chunks)


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
