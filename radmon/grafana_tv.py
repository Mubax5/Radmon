from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlencode

from .models import StationConfig
from .stations import station_catalog

DATASOURCE_UID = "ipradmon-mysql"
PLAYLIST_UID = "radmon-tv"
PLAYLIST_INTERVAL = "10s"
DASHBOARD_FILES = (
    "radmon-tv-page-1-realtime.json",
    "radmon-tv-page-2-trends.json",
    "radmon-tv-page-3-operations.json",
    "radmon-tv-page-4-building-50.json",
    "radmon-tv-page-5-building-38.json",
    "radmon-tv-page-6-building-52.json",
    "radmon-tv-page-7-building-55.json",
    "radmon-tv-page-8-building-57.json",
)
PAGE_UIDS = (
    "radmon-tv-page-1-realtime",
    "radmon-tv-page-2-trends",
    "radmon-tv-page-3-operations",
    "radmon-tv-page-4-building-50",
    "radmon-tv-page-5-building-38",
    "radmon-tv-page-6-building-52",
    "radmon-tv-page-7-building-55",
    "radmon-tv-page-8-building-57",
)
BUILDING_PAGE_ORDER = ("50", "38", "52", "55", "57")


def _datasource() -> dict[str, str]:
    return {"type": "mysql", "uid": DATASOURCE_UID}


def _target(sql: str, *, format_: str = "table", ref_id: str = "A") -> dict[str, Any]:
    return {
        "refId": ref_id,
        "format": format_,
        "editorMode": "code",
        "rawQuery": True,
        "rawSql": sql.strip(),
        "datasource": _datasource(),
    }


def _panel(panel_id: int, type_: str, title: str, x: int, y: int, w: int, h: int) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": type_,
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": _datasource() if type_ != "text" else None,
        "targets": [],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
        "transparent": False,
    }


def _header_panels() -> list[dict[str, Any]]:
    title = _panel(1, "text", "", 0, 0, 24, 2)
    title["options"] = {
        "mode": "html",
        "content": (
            "<div style='height:100%;display:flex;align-items:center;justify-content:center;"
            "font-size:clamp(22px,1.7vw,32px);font-weight:800;letter-spacing:.2px'>"
            "REAL TIME DOSE RATE MONITORING SYSTEM</div>"
        ),
    }
    organization = _panel(2, "text", "", 0, 2, 24, 2)
    organization["options"] = {
        "mode": "html",
        "content": (
            "<div style='height:100%;display:flex;align-items:center;justify-content:center;"
            "text-align:center;font-size:clamp(13px,.95vw,18px);font-weight:650'>"
            "Instalasi Pengelolaan Limbah Radioaktif<br>"
            "Direktorat Pengelolaan Fasilitas Ketenaganukliran</div>"
        ),
    }
    return [title, organization]


def _base_dashboard(title: str, uid: str, *, time_from: str) -> dict[str, Any]:
    return {
        "annotations": {"list": []},
        "editable": False,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": _header_panels(),
        "refresh": "2s",
        "schemaVersion": 42,
        "style": "dark",
        "tags": ["radmon-tv", "radiation", "monitoring", "dpfk"],
        "templating": {"list": []},
        "time": {"from": time_from, "to": "now"},
        "timepicker": {"hidden": True, "refresh_intervals": ["2s", "5s", "10s", "30s", "1m", "5m"]},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "monday",
    }


def _station_ids(stations: Sequence[StationConfig] | None = None) -> str:
    selected = list(stations) if stations is not None else station_catalog()
    return ",".join(str(station.serid) for station in selected)


def _stations_for_building(building: str) -> list[StationConfig]:
    return [station for station in station_catalog() if station.building == building]


def _latest_relation(stations: Sequence[StationConfig] | None = None) -> str:
    ids = _station_ids(stations)
    return f"""
SELECT m.serid, m.dtom, m.doserate
FROM measurement m
JOIN (
  SELECT serid, MAX(dtom) AS dtom
  FROM measurement
  WHERE serid IN ({ids})
  GROUP BY serid
) latest ON latest.serid = m.serid AND latest.dtom = m.dtom
""".strip()


def _status_relation(stations: Sequence[StationConfig] | None = None) -> str:
    ids = _station_ids(stations)
    latest = _latest_relation(stations)
    return f"""
SELECT
  d.serid,
  d.name,
  d.location,
  d.warnlevel,
  d.alarmlevel,
  COALESCE(d.maxidlemin, 30) AS maxidlemin,
  m.dtom,
  m.doserate,
  CASE
    WHEN m.dtom IS NULL OR m.doserate IS NULL THEN 'OFFLINE'
    WHEN TIMESTAMPDIFF(SECOND, m.dtom, NOW()) > COALESCE(d.maxidlemin, 30) * 60 THEN 'OFFLINE'
    WHEN m.doserate >= d.alarmlevel THEN 'ALARM'
    WHEN m.doserate >= d.warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END AS status
FROM device d
LEFT JOIN ({latest}) m ON m.serid = d.serid
WHERE d.serid IN ({ids})
""".strip()


def _latest_scalar_stat(
    panel_id: int,
    title: str,
    sql: str,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    unit: str = "none",
    color: str = "green",
    decimals: int = 2,
    value_size: int = 30,
) -> dict[str, Any]:
    panel = _panel(panel_id, "stat", title, x, y, w, h)
    panel["targets"] = [_target(sql)]
    panel["fieldConfig"] = {
        "defaults": {
            "unit": unit,
            "decimals": decimals,
            "color": {"mode": "fixed", "fixedColor": color},
            "thresholds": {"mode": "absolute", "steps": [{"color": color, "value": None}]},
        },
        "overrides": [],
    }
    panel["options"] = {
        "colorMode": "value",
        "graphMode": "none",
        "justifyMode": "center",
        "orientation": "horizontal",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "text": {"valueSize": value_size},
        "textMode": "value",
        "wideLayout": True,
    }
    return panel


def _dose_stat(panel_id: int, station: StationConfig, x: int, y: int, w: int, h: int = 2) -> dict[str, Any]:
    panel = _panel(panel_id, "stat", f"[{station.serid}] {station.room} ({station.location})", x, y, w, h)
    panel["targets"] = [_target(f"""
SELECT m.doserate AS value
FROM measurement m
WHERE m.serid = {station.serid}
ORDER BY m.dtom DESC LIMIT 1
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


def _dose_sparkline(panel_id: int, station: StationConfig, x: int, y: int, w: int, h: int = 1) -> dict[str, Any]:
    panel = _panel(panel_id, "timeseries", "", x, y, w, h)
    panel["description"] = "latest-dose-sparkline"
    panel["targets"] = [_target(f"""
SELECT UNIX_TIMESTAMP(m.dtom) AS time, m.doserate AS value
FROM measurement m
WHERE m.serid = {station.serid}
  AND $__timeFilter(m.dtom)
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


def _time_stat(panel_id: int, station: StationConfig, x: int, y: int, w: int, h: int = 1) -> dict[str, Any]:
    panel = _panel(panel_id, "stat", "", x, y, w, h)
    panel["description"] = "latest-measurement-time"
    panel["targets"] = [_target(f"""
SELECT UNIX_TIMESTAMP(MAX(m.dtom)) * 1000 AS value
FROM measurement m
WHERE m.serid = {station.serid}
""")]
    panel["fieldConfig"] = {"defaults": {"unit": "dateTimeAsLocal", "decimals": 0}, "overrides": []}
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


def _operation_table(
    panel_id: int,
    title: str,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    stations: Sequence[StationConfig] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    relation = _status_relation(stations)
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    table = _panel(panel_id, "table", title, x, y, w, h)
    table["description"] = "operational-condition"
    table["targets"] = [_target(f"""
SELECT
  s.serid AS `ID`,
  s.name AS `Ruangan`,
  s.location AS `Lokasi`,
  ROUND(s.doserate, 3) AS `Dose Rate`,
  s.dtom AS `Waktu`,
  s.status AS `Status`
FROM ({relation}) s
ORDER BY FIELD(s.status, 'ALARM', 'ALERT', 'OFFLINE', 'NORMAL'), s.serid
{limit_sql}
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


def _building_trend(panel_id: int, building: str, x: int, y: int, w: int, h: int) -> dict[str, Any]:
    stations = _stations_for_building(building)
    panel = _panel(panel_id, "timeseries", f"Dose Rate · Gedung {building} · 3 Jam", x, y, w, h)
    panel["description"] = "building-dose-trend"
    panel["targets"] = [_target(f"""
SELECT
  UNIX_TIMESTAMP(m.dtom) AS time,
  CONCAT('[', d.serid, '] ', d.name) AS metric,
  m.doserate AS value
FROM measurement m
JOIN device d ON d.serid = m.serid
WHERE m.serid IN ({_station_ids(stations)})
  AND $__timeFilter(m.dtom)
ORDER BY m.dtom, d.serid
""", format_="time_series")]
    panel["fieldConfig"] = {
        "defaults": {
            "unit": "suffix: µSv/h",
            "decimals": 3,
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


def build_page_one() -> dict[str, Any]:
    dashboard = _base_dashboard("RadMon TV · Realtime", PAGE_UIDS[0], time_from="now-10m")
    widths = [5, 5, 5, 5, 4]
    x_positions = [0, 5, 10, 15, 20]
    panel_id = 10
    for index, station in enumerate(station_catalog()):
        row, col = divmod(index, 5)
        x = x_positions[col]
        width = widths[col]
        y = 4 + row * 4
        dashboard["panels"].append(_dose_stat(panel_id, station, x, y, width, 2))
        panel_id += 1
        dashboard["panels"].append(_dose_sparkline(panel_id, station, x, y + 2, width, 1))
        panel_id += 1
        dashboard["panels"].append(_time_stat(panel_id, station, x, y + 3, width, 1))
        panel_id += 1
    dashboard["panels"].append(_operation_table(panel_id, "Kondisi Operasional Detector · Page 1/8", 0, 16, 24, 8, limit=8))
    return dashboard


def build_page_two() -> dict[str, Any]:
    dashboard = _base_dashboard("RadMon TV · Trends", PAGE_UIDS[1], time_from="now-3h")
    placements = [
        ("50", 0, 4, 12, 5),
        ("38", 12, 4, 12, 5),
        ("52", 0, 9, 8, 5),
        ("55", 8, 9, 8, 5),
        ("57", 16, 9, 8, 5),
    ]
    panel_id = 10
    for building, x, y, w, h in placements:
        dashboard["panels"].append(_building_trend(panel_id, building, x, y, w, h))
        panel_id += 1
    latest = _latest_relation()
    summaries = [
        ("Dose Rate Tertinggi Saat Ini", f"SELECT MAX(m.doserate) AS value FROM ({latest}) m", 0, "red", 2),
        ("Rata-rata Saat Ini", f"SELECT AVG(m.doserate) AS value FROM ({latest}) m", 6, "blue", 2),
        ("Detector Online", f"SELECT SUM(CASE WHEN s.status <> 'OFFLINE' THEN 1 ELSE 0 END) AS value FROM ({_status_relation()}) s", 12, "green", 0),
        ("Detector Offline", f"SELECT SUM(CASE WHEN s.status = 'OFFLINE' THEN 1 ELSE 0 END) AS value FROM ({_status_relation()}) s", 18, "purple", 0),
    ]
    for title, sql, x, color, decimals in summaries:
        dashboard["panels"].append(_latest_scalar_stat(
            panel_id, title, sql, x, 14, 6, 4,
            unit="suffix: µSv/h" if decimals else "none",
            color=color, decimals=decimals, value_size=28,
        ))
        panel_id += 1
    dashboard["panels"].append(_operation_table(panel_id, "Kondisi Operasional Detector · Page 2/8", 0, 18, 24, 6, limit=5))
    return dashboard


def build_page_three() -> dict[str, Any]:
    dashboard = _base_dashboard("RadMon TV · Operations", PAGE_UIDS[2], time_from="now-24h")
    status_relation = _status_relation()
    pie = _panel(10, "piechart", "Status Detector", 0, 4, 8, 7)
    pie["targets"] = [_target(f"""
SELECT s.status AS metric, COUNT(*) AS value
FROM ({status_relation}) s
GROUP BY s.status
ORDER BY FIELD(s.status, 'ALARM', 'ALERT', 'OFFLINE', 'NORMAL')
""")]
    pie["fieldConfig"] = {"defaults": {"unit": "none", "decimals": 0}, "overrides": []}
    pie["options"] = {
        "displayLabels": ["name", "percent", "value"],
        "legend": {"displayMode": "list", "placement": "right", "showLegend": True},
        "pieType": "donut",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    dashboard["panels"].append(pie)
    dashboard["panels"].append(_operation_table(11, "Kondisi Operasional Detector · Page 3/8", 8, 4, 16, 7, limit=8))
    stats = [(12, "NORMAL", "green", 0), (13, "ALERT", "orange", 6), (14, "ALARM", "red", 12), (15, "OFFLINE", "purple", 18)]
    for panel_id, status, color, x in stats:
        dashboard["panels"].append(_latest_scalar_stat(
            panel_id,
            status,
            f"SELECT COUNT(*) AS value FROM ({status_relation}) s WHERE s.status = '{status}'",
            x,
            11,
            6,
            4,
            color=color,
            decimals=0,
            value_size=30,
        ))
    alarms = _panel(16, "table", "Alarm Terbaru · 24 Jam", 0, 15, 24, 9)
    alarms["targets"] = [_target(f"""
SELECT
  a.dtom AS `Waktu`,
  a.serid AS `ID`,
  d.name AS `Ruangan`,
  d.location AS `Lokasi`,
  a.`type` AS `Status`,
  COALESCE(a.msg, '') AS `Pesan`
FROM alarm a
LEFT JOIN device d ON d.serid = a.serid
WHERE a.serid IN ({_station_ids()})
  AND a.dtom >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY a.dtom DESC, a.alarmid DESC
LIMIT 12
""")]
    alarms["fieldConfig"] = {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}}, "overrides": []}
    alarms["options"] = {"cellHeight": "sm", "enablePagination": False, "showHeader": True}
    dashboard["panels"].append(alarms)
    return dashboard


def _building_card_widths(count: int) -> list[int]:
    if count <= 1:
        return [24]
    if count == 2:
        return [12, 12]
    if count == 3:
        return [8, 8, 8]
    if count == 4:
        return [6, 6, 6, 6]
    return [5, 5, 5, 5, 4]


def build_building_page(page_number: int, building: str) -> dict[str, Any]:
    uid = PAGE_UIDS[page_number - 1]
    stations = _stations_for_building(building)
    dashboard = _base_dashboard(f"RadMon TV · Gedung {building}", uid, time_from="now-3h")
    widths = _building_card_widths(len(stations))
    x = 0
    panel_id = 10
    for station, width in zip(stations, widths):
        dashboard["panels"].append(_dose_stat(panel_id, station, x, 4, width, 3))
        panel_id += 1
        dashboard["panels"].append(_time_stat(panel_id, station, x, 7, width, 1))
        panel_id += 1
        x += width
    dashboard["panels"].append(_building_trend(panel_id, building, 0, 8, 24, 8))
    panel_id += 1
    dashboard["panels"].append(_operation_table(
        panel_id,
        f"Kondisi Operasional Detector · Page {page_number}/8 · Gedung {building}",
        0,
        16,
        24,
        8,
        stations=stations,
    ))
    return dashboard


def build_page_four() -> dict[str, Any]:
    return build_building_page(4, "50")


def build_page_five() -> dict[str, Any]:
    return build_building_page(5, "38")


def build_page_six() -> dict[str, Any]:
    return build_building_page(6, "52")


def build_page_seven() -> dict[str, Any]:
    return build_building_page(7, "55")


def build_page_eight() -> dict[str, Any]:
    return build_building_page(8, "57")


def build_dashboard_payloads() -> list[dict[str, Any]]:
    return [
        build_page_one(),
        build_page_two(),
        build_page_three(),
        build_page_four(),
        build_page_five(),
        build_page_six(),
        build_page_seven(),
        build_page_eight(),
    ]


def build_playlist_payload(*, resource_version: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": PLAYLIST_UID, "namespace": "default"}
    if resource_version:
        metadata["resourceVersion"] = resource_version
    return {
        "kind": "Playlist",
        "apiVersion": "playlist.grafana.app/v1",
        "metadata": metadata,
        "spec": {
            "title": "RadMon TV",
            "interval": PLAYLIST_INTERVAL,
            "items": [{"type": "dashboard_by_uid", "value": uid} for uid in PAGE_UIDS],
        },
    }


def playlist_url(base_url: str) -> str:
    params = [
        ("kiosk", "1"),
        ("autofitpanels", ""),
        ("_dash.hidePlaylistNav", "true"),
        ("_dash.hideTimePicker", "true"),
        ("_dash.hideVariables", "true"),
        ("_dash.hideLinks", "true"),
    ]
    query = urlencode(params)
    query = query.replace("autofitpanels=", "autofitpanels")
    return f"{base_url.rstrip('/')}/playlists/play/{PLAYLIST_UID}?{query}"


def write_dashboard_files(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, payload in zip(DASHBOARD_FILES, build_dashboard_payloads()):
        path = output_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
