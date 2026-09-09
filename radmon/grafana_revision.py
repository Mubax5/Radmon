"""Compatibility patch for the generated Grafana TV payloads.

Kept separate from the large dashboard generator so the timestamp regression and
shared header can be tested independently. ``apply()`` replaces only the two
small generator helpers involved in this revision.
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

        # Grafana Stat reliably reduces numeric fields, while the deployed
        # version renders the previous string-only CONCAT/DATE_FORMAT query as
        # "No data". Use one numeric Unix epoch scalar for both header panels
        # and let Grafana format it in the browser-local (WIB on the deployment PC) timezone.
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
        # Keep title + organization first for compatibility with existing
        # payload tests, while grid positions render date-left/org-center/time-right.
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
            "defaults": {"unit": "dateTimeAsLocal", "decimals": 0},
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

    tv._header_panels = header_panels
    tv._time_stat = time_stat