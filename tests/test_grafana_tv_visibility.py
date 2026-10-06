from radmon.grafana_tv import build_page_one, build_page_three


def test_page_one_uses_trend_space_instead_of_timestamp_only_row():
    dashboard = build_page_one()
    time_panels = [
        panel for panel in dashboard["panels"]
        if panel.get("description") == "latest-measurement-time"
    ]
    assert not time_panels
    trends = [panel for panel in dashboard["panels"] if panel.get("description") == "latest-dose-sparkline"]
    assert len(trends) == 15
    assert all(panel["gridPos"]["h"] >= 3 for panel in trends)


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
