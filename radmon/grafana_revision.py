"""Focused compatibility adjustments for generated Grafana TV payloads.

The legacy dashboard generator stays intact while this module applies small,
well-tested display fixes used by the deployed Grafana version.
"""
from __future__ import annotations

from typing import Any


def apply() -> None:
    from . import grafana_tv as tv

    def header_panels() -> list[dict[str, Any]]:
        title = tv._panel(1, "text", "", 0, 0, 24, 2)
        title["options"] = {
            "mode": "html",
            "content": (
                "<div style='height:100%;display:flex;align-items:center;justify-content:center;"
                "font-size:clamp(22px,1.7vw,32px);font-weight:800;letter-spacing:.2px'>"
                "REAL TIME DOSE RATE MONITORING SYSTEM</div>"
            ),
        }

        organization = tv._panel(2, "text", "", 6, 2, 12, 2)
        organization["description"] = "header-organization"
        organization["options"] = {
            "mode": "html",
            "content": (
                "<div style='height:100%;display:flex;align-items:center;justify-content:center;"
                "text-align:center;font-size:clamp(13px,.95vw,18px);font-weight:650'>"
                "Instalasi Pengelolaan Limbah Radioaktif<br>"
                "Direktorat Pengelolaan Fasilitas Ketenaganukliran</div>"
            ),
        }

        date_panel = tv._panel(3, "stat", "", 0, 2, 6, 2)
        date_panel["description"] = "header-date-wib"
        date_panel["targets"] = [tv._target("""
SELECT UNIX_TIMESTAMP() * 1000 AS value
""")]
        date_panel["fieldConfig"] = {
            "defaults": {"unit": "time:DD/MM/YYYY", "decimals": 0},
            "overrides": [],
        }
        date_panel["options"] = {
            "colorMode": "none",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "text": {"valueSize": 12},
            "textMode": "value",
            "wideLayout": True,
        }

        update_panel = tv._panel(4, "stat", "", 18, 2, 6, 2)
        update_panel["description"] = "header-update-wib"
        update_panel["targets"] = [tv._target("""
SELECT UNIX_TIMESTAMP() * 1000 AS value
""")]
        update_panel["fieldConfig"] = {
            "defaults": {"unit": "time:HH:mm:ss [WIB]", "decimals": 0},
            "overrides": [],
        }
        update_panel["options"] = {
            "colorMode": "none",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "text": {"valueSize": 12},
            "textMode": "value",
            "wideLayout": True,
        }
        return [title, organization, date_panel, update_panel]

    def time_stat(panel_id, station, x, y, w, h=1):
        panel = tv._panel(panel_id, "stat", "", x, y, w, h)
        panel["description"] = "latest-measurement-time"
        panel["targets"] = [tv._target(f"""
SELECT UNIX_TIMESTAMP(MAX(m.dtom)) * 1000 AS value
FROM measurement m
WHERE m.serid = {station.serid}
""")]
        panel["fieldConfig"] = {
            "defaults": {"unit": "time:DD/MM/YYYY HH:mm:ss", "decimals": 0},
            "overrides": [],
        }
        panel["options"] = {
            "colorMode": "none",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "text": {"valueSize": 12},
            "textMode": "value",
            "wideLayout": True,
        }
        return panel

    original_page_three = tv.build_page_three

    def build_page_three(page_number: int = 1) -> dict[str, Any]:
        dashboard = original_page_three(page_number)
        status_panel = next(
            panel for panel in dashboard["panels"]
            if panel.get("title") == "Status Detector"
        )
        operations_panel = next(
            panel for panel in dashboard["panels"]
            if panel.get("description") == "operational-condition"
        )

        # Give the donut and its bottom legend equal half-screen width so both
        # status names and integer counts remain visible at 1920x1080.
        status_panel["gridPos"]["w"] = 12
        operations_panel["gridPos"]["x"] = 12
        operations_panel["gridPos"]["w"] = 12
        status_panel["options"]["displayLabels"] = ["name", "value"]
        status_panel["options"]["legend"].update(
            {"displayMode": "table", "placement": "bottom", "showLegend": True, "values": ["value"]}
        )
        return dashboard

    tv._header_panels = header_panels
    tv._time_stat = time_stat
    tv.build_page_three = build_page_three
