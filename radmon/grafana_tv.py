from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .stations import station_catalog

DATASOURCE_UID = "ipradmon-mysql"
PLAYLIST_UID = "radmon-tv"
PLAYLIST_INTERVAL = "10s"
DASHBOARD_FILES = (
    "radmon-tv-page-1-realtime.json",
    "radmon-tv-page-2-trends.json",
    "radmon-tv-page-3-operations.json",
)
PAGE_UIDS = (
    "radmon-tv-page-1-realtime",
    "radmon-tv-page-2-trends",
    "radmon-tv-page-3-operations",
)


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
            "font-size:clamp(22px,1.8vw,34px);font-weight:800;letter-spacing:.2px'>"
            "REAL TIME DOSE RATE MONITORING SYSTEM</div>"
        ),
    }
    organization = _panel(2, "text", "", 0, 2, 24, 2)
    organization["options"] = {
        "mode": "html",
        "content": (
            "<div style='height:100%;display:flex;align-items:center;justify-content:center;"
            "text-align:center;font-size:clamp(14px,1.05vw,20px);font-weight:650'>"
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


def _station_ids() -> str:
    return ",".join(str(station.serid) for station in station_catalog())


def _latest_relation(alias: str = "m") -> str:
    ids = _station_ids()
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


def _status_relation() -> str:
    ids = _station_ids()
    latest = _latest_relation()
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


def _latest_scalar_stat(panel_id: int, title: str, sql: str, x: int, y: int, w: int, h: int, *, unit: str = "none", color: str = "green") -> dict[str, Any]:
    panel = _panel(panel_id, "stat", title, x, y, w, h)
    panel["targets"] = [_target(sql)]
    panel["fieldConfig"] = {
        "defaults": {
            "unit": unit,
            "decimals": 2,
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
        "textMode": "value",
        "wideLayout": True,
    }
    return panel


def build_page_one() -> dict[str, Any]:
    dashboard = _base_dashboard("RadMon TV · Realtime", PAGE_UIDS[0], time_from="now-5m")
    widths = [5, 5, 5, 5, 4]
    x_positions = [0, 5, 10, 15, 20]
    panel_id = 10
    for index, station in enumerate(station_catalog()):
        row, col = divmod(index, 5)
        x = x_positions[col]
        width = widths[col]
        y = 4 + row * 6
        dose = _panel(
            panel_id,
            "stat",
            f"[{station.serid}] {station.room} ({station.location})",
            x,
            y,
            width,
            4,
        )
        panel_id += 1
        dose["targets"] = [
            _target(
                f"""
SELECT m.doserate AS value
FROM measurement m
WHERE m.serid = {station.serid}
ORDER BY m.dtom DESC LIMIT 1
"""
            )
        ]
        dose["fieldConfig"] = {
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
        dose["options"] = {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value",
            "wideLayout": True,
        }
        dashboard["panels"].append(dose)

        timestamp = _panel(panel_id, "stat", "", x, y + 4, width, 2)
        panel_id += 1
        timestamp["description"] = "latest-measurement-time"
        timestamp["targets"] = [
            _target(
                f"""
SELECT UNIX_TIMESTAMP(MAX(m.dtom)) * 1000 AS value
FROM measurement m
WHERE m.serid = {station.serid}
"""
            )
        ]
        timestamp["fieldConfig"] = {
            "defaults": {"unit": "dateTimeAsLocal", "decimals": 0},
            "overrides": [],
        }
        timestamp["options"] = {
            "colorMode": "none",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value",
            "wideLayout": True,
        }
        dashboard["panels"].append(timestamp)
    return dashboard


def build_page_two() -> dict[str, Any]:
    dashboard = _base_dashboard("RadMon TV · Trends", PAGE_UIDS[1], time_from="now-3h")
    trend = _panel(10, "timeseries", "Dose Rate Monitoring · 3 Jam Terakhir", 0, 4, 24, 12)
    trend["targets"] = [
        _target(
            f"""
SELECT
  UNIX_TIMESTAMP(m.dtom) AS time,
  CONCAT('[', d.serid, '] ', d.name, ' (', d.location, ')') AS metric,
  m.doserate AS value
FROM measurement m
JOIN device d ON d.serid = m.serid
WHERE m.serid IN ({_station_ids()})
  AND $__timeFilter(m.dtom)
ORDER BY m.dtom, d.serid
""",
            format_="time_series",
        )
    ]
    trend["fieldConfig"] = {
        "defaults": {
            "unit": "suffix: µSv/h",
            "decimals": 3,
            "color": {"mode": "palette-classic"},
            "custom": {
                "drawStyle": "line",
                "fillOpacity": 10,
                "lineWidth": 2,
                "showPoints": "never",
                "spanNulls": 4000,
            },
        },
        "overrides": [],
    }
    trend["options"] = {
        "legend": {"displayMode": "table", "placement": "bottom", "showLegend": True, "calcs": ["lastNotNull", "max"]},
        "tooltip": {"mode": "multi", "sort": "desc"},
    }
    dashboard["panels"].append(trend)

    latest = _latest_relation()
    dashboard["panels"].extend(
        [
            _latest_scalar_stat(
                11,
                "Dose Rate Tertinggi Saat Ini",
                f"SELECT MAX(m.doserate) AS value FROM ({latest}) m",
                0,
                16,
                6,
                6,
                unit="suffix: µSv/h",
                color="red",
            ),
            _latest_scalar_stat(
                12,
                "Rata-rata Saat Ini",
                f"SELECT AVG(m.doserate) AS value FROM ({latest}) m",
                6,
                16,
                6,
                6,
                unit="suffix: µSv/h",
                color="blue",
            ),
            _latest_scalar_stat(
                13,
                "Detector Online",
                f"SELECT SUM(CASE WHEN s.status <> 'OFFLINE' THEN 1 ELSE 0 END) AS value FROM ({_status_relation()}) s",
                12,
                16,
                6,
                6,
                color="green",
            ),
            _latest_scalar_stat(
                14,
                "Detector Offline",
                f"SELECT SUM(CASE WHEN s.status = 'OFFLINE' THEN 1 ELSE 0 END) AS value FROM ({_status_relation()}) s",
                18,
                16,
                6,
                6,
                color="purple",
            ),
        ]
    )
    return dashboard


def build_page_three() -> dict[str, Any]:
    dashboard = _base_dashboard("RadMon TV · Operations", PAGE_UIDS[2], time_from="now-24h")
    status_relation = _status_relation()

    pie = _panel(10, "piechart", "Status Detector", 0, 4, 8, 8)
    pie["targets"] = [
        _target(
            f"""
SELECT s.status AS metric, COUNT(*) AS value
FROM ({status_relation}) s
GROUP BY s.status
ORDER BY FIELD(s.status, 'ALARM', 'ALERT', 'OFFLINE', 'NORMAL')
"""
        )
    ]
    pie["fieldConfig"] = {
        "defaults": {"unit": "none"},
        "overrides": [
            {"matcher": {"id": "byValue", "options": {"options": {"ALARM": {}}}}, "properties": []}
        ],
    }
    pie["options"] = {
        "displayLabels": ["name", "percent", "value"],
        "legend": {"displayMode": "list", "placement": "right", "showLegend": True},
        "pieType": "donut",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    dashboard["panels"].append(pie)

    table = _panel(11, "table", "Kondisi Operasional Detector", 8, 4, 16, 8)
    table["targets"] = [
        _target(
            f"""
SELECT
  s.serid AS `ID`,
  s.name AS `Ruangan`,
  s.location AS `Lokasi`,
  ROUND(s.doserate, 3) AS `Dose Rate`,
  s.dtom AS `Waktu`,
  s.status AS `Status`
FROM ({status_relation}) s
ORDER BY FIELD(s.status, 'ALARM', 'ALERT', 'OFFLINE', 'NORMAL'), s.serid
"""
        )
    ]
    table["fieldConfig"] = {
        "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
        "overrides": [
            {"matcher": {"id": "byName", "options": "Dose Rate"}, "properties": [{"id": "unit", "value": "suffix: µSv/h"}, {"id": "decimals", "value": 3}]},
            {"matcher": {"id": "byName", "options": "Status"}, "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}}]},
        ],
    }
    table["options"] = {"cellHeight": "sm", "enablePagination": True, "showHeader": True}
    dashboard["panels"].append(table)

    stats = [
        (12, "NORMAL", "green", 0),
        (13, "ALERT", "orange", 6),
        (14, "ALARM", "red", 12),
        (15, "OFFLINE", "purple", 18),
    ]
    for panel_id, status, color, x in stats:
        dashboard["panels"].append(
            _latest_scalar_stat(
                panel_id,
                status,
                f"SELECT COUNT(*) AS value FROM ({status_relation}) s WHERE s.status = '{status}'",
                x,
                12,
                6,
                4,
                color=color,
            )
        )

    alarms = _panel(16, "table", "Alarm Terbaru · 24 Jam", 0, 16, 24, 8)
    alarms["targets"] = [
        _target(
            f"""
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
"""
        )
    ]
    alarms["fieldConfig"] = {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}}, "overrides": []}
    alarms["options"] = {"cellHeight": "sm", "enablePagination": False, "showHeader": True}
    dashboard["panels"].append(alarms)
    return dashboard


def build_dashboard_payloads() -> list[dict[str, Any]]:
    return [build_page_one(), build_page_two(), build_page_three()]


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
