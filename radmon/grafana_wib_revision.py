"""Make Grafana queries explicit about production DATETIME semantics.

Production RadMon stores naive MariaDB DATETIME values as WIB wall-clock time.
Grafana/MySQL sessions may run in UTC, so raw $__timeFilter() and
UNIX_TIMESTAMP(dtom) can shift timestamps by seven hours or exclude current
rows. Convert stored WIB values to UTC numeric epoch explicitly and compare
idle age against an explicit WIB current time.
"""
from __future__ import annotations

from typing import Any, Sequence


def _utc_epoch_sql(column: str) -> str:
    return (
        "TIMESTAMPDIFF(SECOND, '1970-01-01 00:00:00', "
        f"CONVERT_TZ({column}, '+07:00', '+00:00'))"
    )


def _utc_epoch_ms_sql(column: str) -> str:
    return (
        "TIMESTAMPDIFF(MICROSECOND, '1970-01-01 00:00:00', "
        f"CONVERT_TZ({column}, '+07:00', '+00:00')) / 1000"
    )


def apply() -> None:
    from . import grafana_tv as tv

    def dose_sparkline(panel_id, station, x, y, w, h=1):
        panel = tv._panel(panel_id, "timeseries", "", x, y, w, h)
        panel["description"] = "latest-dose-sparkline"
        epoch = _utc_epoch_sql("m.dtom")
        panel["targets"] = [tv._target(f"""
SELECT {epoch} AS time, m.doserate AS value
FROM measurement m
WHERE m.serid = {station.serid}
  AND {epoch} BETWEEN $__unixEpochFrom() AND $__unixEpochTo()
ORDER BY m.dtom
""", format_="time_series")]
        panel["fieldConfig"] = {
            "defaults": {
                "unit": "suffix: µSv/h",
                "decimals": 2,
                "color": {"mode": "fixed", "fixedColor": "green"},
                "custom": {
                    "axisPlacement": "hidden",
                    "drawStyle": "line",
                    "fillOpacity": 18,
                    "lineWidth": 1,
                    "showPoints": "never",
                    "spanNulls": 4000,
                },
            },
            "overrides": [],
        }
        panel["options"] = {
            "legend": {"displayMode": "hidden", "placement": "bottom", "showLegend": False},
            "tooltip": {"mode": "single", "sort": "none"},
        }
        return panel

    def time_stat(panel_id, station, x, y, w, h=1):
        panel = tv._panel(panel_id, "stat", "", x, y, w, h)
        panel["description"] = "latest-measurement-time"
        epoch_ms = _utc_epoch_ms_sql("dtom")
        panel["targets"] = [tv._target(f"""
SELECT {epoch_ms} AS value
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

    def status_relation(stations: Sequence | None = None) -> str:
        ids = tv._station_ids(stations)
        wib_now = "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')"
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
    WHEN TIMESTAMPDIFF(SECOND, dtom, {wib_now}) > COALESCE(maxidlemin, 30) * 60 THEN 'OFFLINE'
    WHEN doserate >= alarmlevel THEN 'ALARM'
    WHEN doserate >= warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END AS status
FROM vrecent
WHERE serid IN ({ids})
""".strip()

    def operation_table(
        panel_id: int,
        title: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        stations: Sequence | None = None,
    ) -> dict[str, Any]:
        relation = status_relation(stations)
        table = tv._panel(panel_id, "table", title, x, y, w, h)
        table["description"] = "operational-condition"
        table["targets"] = [tv._target(f"""
SELECT
  s.serid AS `ID`,
  s.name AS `Ruangan`,
  s.location AS `Lokasi`,
  ROUND(s.doserate, 3) AS `Dose Rate`,
  DATE_FORMAT(s.dtom, '%Y-%m-%d %H:%i:%s') AS `Waktu`,
  s.status AS `Status`
FROM ({relation}) s
ORDER BY FIELD(s.status, 'ALARM', 'ALERT', 'OFFLINE', 'NORMAL'), s.serid
""")]
        table["fieldConfig"] = {
            "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Dose Rate"},
                    "properties": [
                        {"id": "unit", "value": "suffix: µSv/h"},
                        {"id": "decimals", "value": 3},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": "Status"},
                    "properties": [
                        {
                            "id": "mappings",
                            "value": [{
                                "type": "value",
                                "options": {
                                    "NORMAL": {"color": "green", "text": "NORMAL"},
                                    "ALERT": {"color": "orange", "text": "ALERT"},
                                    "ALARM": {"color": "red", "text": "ALARM"},
                                    "OFFLINE": {"color": "purple", "text": "OFFLINE"},
                                },
                            }],
                        },
                        {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                    ],
                },
            ],
        }
        table["options"] = {"cellHeight": "sm", "enablePagination": False, "showHeader": True}
        return table

    def building_trend(panel_id: int, building: str, x: int, y: int, w: int, h: int):
        stations = tv._stations_for_building(building)
        panel = tv._panel(
            panel_id,
            "timeseries",
            f"Dose Rate · Gedung {building} · 3 Jam",
            x, y, w, h,
        )
        panel["description"] = "building-dose-trend"
        epoch = _utc_epoch_sql("m.dtom")
        panel["targets"] = [tv._target(f"""
SELECT
  {epoch} AS time,
  CONCAT('[', d.serid, '] ', d.name) AS metric,
  m.doserate AS value
FROM measurement m
JOIN device d ON d.serid = m.serid
WHERE m.serid IN ({tv._station_ids(stations)})
  AND {epoch} BETWEEN $__unixEpochFrom() AND $__unixEpochTo()
ORDER BY m.dtom, d.serid
""", format_="time_series")]
        panel["fieldConfig"] = {
            "defaults": {
                "unit": "suffix: µSv/h",
                "decimals": 3,
                "min": 0,
                "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "line",
                    "fillOpacity": 0,
                    "lineWidth": 1,
                    "showPoints": "never",
                    "spanNulls": 4000,
                },
            },
            "overrides": [],
        }
        panel["options"] = {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"},
        }
        return panel

    previous_page_three = tv.build_page_three

    def build_page_three(page_number: int = 1) -> dict[str, Any]:
        dashboard = previous_page_three(page_number)
        alarms = next(
            panel for panel in dashboard["panels"]
            if panel.get("title") == "Alarm Terbaru · 24 Jam"
        )
        wib_now = "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')"
        alarms["targets"] = [tv._target(f"""
SELECT
  DATE_FORMAT(a.dtoa, '%Y-%m-%d %H:%i:%s') AS `Waktu`,
  a.serid AS `ID`,
  d.name AS `Ruangan`,
  d.location AS `Lokasi`,
  CASE WHEN a.lvl >= 2 THEN 'ALARM' ELSE 'ALERT' END AS `Status`,
  ROUND(a.mvalue, 3) AS `Dose Rate`,
  ROUND(a.thvalue, 3) AS `Threshold`,
  a.nhit AS `Hit Count`,
  DATE_FORMAT(a.i_op, '%Y-%m-%d %H:%i:%s') AS `Action Time`,
  COALESCE(a.pic, '') AS `PIC`,
  COALESCE(a.note, '') AS `Note`
FROM alarm a
LEFT JOIN device d ON d.serid = a.serid
WHERE a.serid IN ({tv._station_ids()})
  AND a.dtoa >= DATE_SUB({wib_now}, INTERVAL 24 HOUR)
ORDER BY a.dtoa DESC, a.serid
LIMIT 12
""")]
        return dashboard

    tv._dose_sparkline = dose_sparkline
    tv._time_stat = time_stat
    tv._status_relation = status_relation
    tv._operation_table = operation_table
    tv._building_trend = building_trend
    tv.build_page_three = build_page_three
