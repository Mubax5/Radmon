import json
from pathlib import Path

import pytest

from radmon.grafana_tv import (
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


def test_playlist_cycles_three_pages_every_ten_seconds_in_kiosk_autofit():
    payload = build_playlist_payload()
    assert PLAYLIST_INTERVAL == "10s"
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
    assert len(dashboards) == 3
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


def test_page_one_has_fifteen_latest_dose_cards_and_timestamp_panels_from_measurement_only():
    page1 = build_dashboard_payloads()[0]
    dose = [panel for panel in page1["panels"] if panel.get("title", "").startswith("[")]
    timestamp = [panel for panel in page1["panels"] if panel.get("description") == "latest-measurement-time"]
    assert len(dose) == 15
    assert len(timestamp) == 15
    for panel in dose:
        sql = panel["targets"][0]["rawSql"]
        assert "FROM measurement" in sql
        assert "ORDER BY m.dtom DESC LIMIT 1" in sql
        assert "recent" not in sql.lower()
        assert panel["fieldConfig"]["defaults"]["unit"] == "suffix: µSv/h"
    for panel in timestamp:
        sql = panel["targets"][0]["rawSql"]
        assert "UNIX_TIMESTAMP(MAX(m.dtom)) * 1000" in sql
        assert "DATE_FORMAT" not in sql
        assert panel["title"] == ""
        assert panel["fieldConfig"]["defaults"]["unit"] == "dateTimeAsLocal"


def test_page_two_is_trend_dashboard_with_useful_current_summary():
    page2 = build_dashboard_payloads()[1]
    titles = {panel.get("title") for panel in page2["panels"]}
    assert "Dose Rate Monitoring · 3 Jam Terakhir" in titles
    assert "Dose Rate Tertinggi Saat Ini" in titles
    assert "Rata-rata Saat Ini" in titles
    assert "Detector Online" in titles
    assert "Detector Offline" in titles
    trend = _panel_by_title(page2, "Dose Rate Monitoring · 3 Jam Terakhir")
    sql = trend["targets"][0]["rawSql"]
    assert "$__timeFilter(m.dtom)" in sql
    assert "m.doserate" in sql
    assert "suffix: µSv/h" == trend["fieldConfig"]["defaults"]["unit"]


def test_page_three_status_is_derived_from_latest_measurement_not_recent_table():
    page3 = build_dashboard_payloads()[2]
    payload = json.dumps(page3, ensure_ascii=False)
    assert "Status Detector" in payload
    assert "Kondisi Operasional Detector" in payload
    assert "FROM measurement" in payload
    assert " recent " not in payload.lower()
    assert "OFFLINE" in payload and "ALARM" in payload and "ALERT" in payload and "NORMAL" in payload
    assert "piechart" in payload


def test_dashboard_file_contract_has_three_distinct_page_names():
    assert set(DASHBOARD_FILES) == {
        "radmon-tv-page-1-realtime.json",
        "radmon-tv-page-2-trends.json",
        "radmon-tv-page-3-operations.json",
    }


def test_dashboard_payloads_are_generated_at_runtime_not_duplicated_as_static_json():
    root = Path(__file__).resolve().parents[1]
    assert len(build_dashboard_payloads()) == 3
    for filename in DASHBOARD_FILES:
        assert not (root / "grafana" / "dashboards" / filename).exists()
    assert not (root / "grafana" / "dashboards" / "radiation-monitoring.json").exists()
