"""Focused compatibility adjustments for generated Grafana TV payloads.

Realtime/status panels read the lightweight production ``vrecent`` view while
historical sparklines and trends continue to use ``measurement``.
"""
from __future__ import annotations

from typing import Any, Sequence


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
        date_panel["targets"] = [tv._target("SELECT UNIX_TIMESTAMP() * 1000 AS value")]
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
        update_panel["targets"] = [tv._target("SELECT UNIX_TIMESTAMP() * 1000 AS value")]
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

    def latest_relation(stations: Sequence | None = None) -> str:
        ids = tv._station_ids(stations)
        return f"""
SELECT serid, dtom, doserate
FROM vrecent
WHERE serid IN ({ids})
""".strip()

    def status_relation(stations: Sequence | None = None) -> str:
        ids = tv._station_ids(stations)
        return f"""
SELECT
  serid,
  name,
  location,
  warnlevel,
  alarmlevel,
  COALESCE(maxidlemin, 30) AS maxidlemin,
  dtom,
  doserate,
  CASE
    WHEN dtom IS NULL OR doserate IS NULL THEN 'OFFLINE'
    WHEN TIMESTAMPDIFF(SECOND, dtom, NOW()) > COALESCE(maxidlemin, 30) * 60 THEN 'OFFLINE'
    WHEN doserate >= alarmlevel THEN 'ALARM'
    WHEN doserate >= warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END AS status
FROM vrecent
WHERE serid IN ({ids})
""".strip()

    def dose_stat(panel_id, station, x, y, w, h=2):
        panel = tv._panel(panel_id, "stat", f"[{station.serid}] {station.room} ({station.location})", x, y, w, h)
        panel["targets"] = [tv._target(f"""
SELECT doserate AS value
FROM vrecent
WHERE serid = {station.serid}
LIMIT 1
""")]
        panel["fieldConfig"] = {
            "defaults": {
                "unit": "suffix: µSv/h",
                "decimals": 2,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": station.warnlevel},
                        {"color": "red", "value": station.alarmlevel},
                    ],
                },
            },
            "overrides": [],
        }
        panel["options"] = {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "text": {"valueSize": 28},
            "textMode": "value",
            "wideLayout": True,
        }
        return panel

    def time_stat(panel_id, station, x, y, w, h=1):
        panel = tv._panel(panel_id, "stat", "", x, y, w, h)
        panel["description"] = "latest-measurement-time"
        panel["targets"] = [tv._target(f"""
SELECT UNIX_TIMESTAMP(dtom) * 1000 AS value
FROM vrecent
WHERE serid = {station.serid}
LIMIT 1
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

        status_panel["gridPos"]["w"] = 12
        operations_panel["gridPos"]["x"] = 12
        operations_panel["gridPos"]["w"] = 12
        status_panel["options"]["displayLabels"] = ["name", "value"]
        status_panel["options"]["legend"].update(
            {"displayMode": "table", "placement": "bottom", "showLegend": True, "values": ["value"]}
        )

        alarms = next(
            panel for panel in dashboard["panels"]
            if panel.get("title") == "Alarm Terbaru · 24 Jam"
        )
        alarms["targets"] = [tv._target(f"""
SELECT
  a.dtoa AS `Waktu`,
  a.serid AS `ID`,
  d.name AS `Ruangan`,
  d.location AS `Lokasi`,
  CASE WHEN a.lvl >= 2 THEN 'ALARM' ELSE 'ALERT' END AS `Status`,
  ROUND(a.mvalue, 3) AS `Dose Rate`,
  ROUND(a.thvalue, 3) AS `Threshold`,
  a.nhit AS `Hit Count`,
  a.i_op AS `Action Time`,
  COALESCE(a.pic, '') AS `PIC`,
  COALESCE(a.note, '') AS `Note`
FROM alarm a
LEFT JOIN device d ON d.serid = a.serid
WHERE a.serid IN ({tv._station_ids()})
  AND a.dtoa >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY a.dtoa DESC, a.serid
LIMIT 12
""")]
        return dashboard

    tv._header_panels = header_panels
    tv._latest_relation = latest_relation
    tv._status_relation = status_relation
    tv._dose_stat = dose_stat
    tv._time_stat = time_stat
    tv.build_page_three = build_page_three
