from radmon.grafana_tv import build_dashboard_payloads


def test_measurement_time_stat_uses_numeric_epoch_from_vrecent():
    page1 = build_dashboard_payloads()[0]
    timestamp = [
        panel for panel in page1["panels"]
        if panel.get("description") == "latest-measurement-time"
    ]
    assert len(timestamp) == 15
    for panel in timestamp:
        sql = panel["targets"][0]["rawSql"]
        assert "TIMESTAMPDIFF" in sql
        assert "CONVERT_TZ(dtom, '+07:00', '+00:00')" in sql
        assert "FROM vrecent" in sql
        assert "DATE_FORMAT" not in sql
        assert panel["fieldConfig"]["defaults"]["unit"] == "time:DD/MM/YYYY HH:mm:ss"


def test_every_dashboard_has_date_organization_and_wib_update_header():
    dashboards = build_dashboard_payloads()
    assert len(dashboards) == 7
    for dashboard in dashboards:
        header = dashboard["panels"][:4]
        assert len(header) == 4
        title, organization, date_panel, update_panel = header
        assert "REAL TIME DOSE RATE MONITORING SYSTEM" in title["options"]["content"]
        assert date_panel.get("description") == "header-date-wib"
        assert organization.get("description") == "header-organization"
        assert update_panel.get("description") == "header-update-wib"
        center_html = organization["options"]["content"]
        assert "font-size:clamp(13px,.95vw,18px);font-weight:650" in center_html
        assert "Instalasi Pengelolaan Limbah Radioaktif" in center_html
        assert "Direktorat Pengelolaan Fasilitas Ketenaganukliran" in center_html
        assert date_panel["gridPos"] == {"x": 0, "y": 2, "w": 6, "h": 2}
        assert organization["gridPos"] == {"x": 6, "y": 2, "w": 12, "h": 2}
        assert update_panel["gridPos"] == {"x": 18, "y": 2, "w": 6, "h": 2}
        assert date_panel["options"]["text"]["valueSize"] < 18
        assert update_panel["options"]["text"]["valueSize"] < 18

        for panel in (date_panel, update_panel):
            sql = panel["targets"][0]["rawSql"]
            assert "UNIX_TIMESTAMP() * 1000" in sql
            assert "DATE_FORMAT" not in sql
            assert "CONCAT" not in sql
            assert panel["options"]["reduceOptions"]["calcs"] == ["lastNotNull"]
            assert panel["options"]["reduceOptions"]["values"] is False

        assert date_panel["fieldConfig"]["defaults"]["unit"] == "time:DD/MM/YYYY"
        assert update_panel["fieldConfig"]["defaults"]["unit"] == "time:HH:mm:ss [WIB]"
        assert dashboard["timezone"] == "browser"

        max_bottom = max(
            panel["gridPos"]["y"] + panel["gridPos"]["h"]
            for panel in dashboard["panels"]
        )
        assert max_bottom <= 24
