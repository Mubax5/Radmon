from radmon.grafana_tv import build_page_one, build_page_three


def test_playlist_one_measurement_time_is_explicit_24_hour_format():
    dashboard = build_page_one()
    time_panels = [
        panel for panel in dashboard["panels"]
        if panel.get("description") == "latest-measurement-time"
    ]
    assert len(time_panels) == 15
    for panel in time_panels:
        assert panel["fieldConfig"]["defaults"]["unit"] == "time:DD/MM/YYYY HH:mm:ss"
        assert panel["options"]["text"]["valueSize"] <= 12


def test_operations_status_detector_has_room_for_labels_and_values():
    dashboard = build_page_three(1)
    status_panel = next(
        panel for panel in dashboard["panels"]
        if panel.get("title") == "Status Detector"
    )
    assert status_panel["gridPos"]["w"] >= 12
    assert status_panel["options"]["displayLabels"] == ["name", "value"]
    assert status_panel["options"]["legend"]["showLegend"] is True
    assert status_panel["options"]["legend"]["placement"] == "bottom"

    operations_panel = next(
        panel for panel in dashboard["panels"]
        if panel.get("description") == "operational-condition"
    )
    assert operations_panel["gridPos"]["w"] <= 12
