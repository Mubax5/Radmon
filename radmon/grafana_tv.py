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
OPERATIONS_PAGE_COUNT = 5
PAGE_UIDS = (
    "radmon-tv-page-1-realtime",
    "radmon-tv-page-2-trends",
    "radmon-tv-page-3-operations",
)
OPERATIONS_PAGE_UIDS = tuple(
    f"{PAGE_UIDS[2]}-{page_number}" for page_number in range(1, OPERATIONS_PAGE_COUNT + 1)
)
DASHBOARD_UIDS = PAGE_UIDS[:2] + OPERATIONS_PAGE_UIDS
DASHBOARD_FILES = (
    "radmon-tv-page-1-realtime.json",
    "radmon-tv-page-2-trends.json",
    *(f"radmon-tv-page-3-operations-{page_number}.json" for page_number in range(1, OPERATIONS_PAGE_COUNT + 1)),
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
    title = _panel(1, 'text', '', 0, 0, 24, 2)
    title['options'] = {'mode': 'html', 'content': "<div style='height:100%;display:flex;align-items:center;justify-content:center;font-size:clamp(22px,1.7vw,32px);font-weight:800;letter-spacing:.2px'>REAL TIME DOSE RATE MONITORING SYSTEM</div>"}
    organization = _panel(2, 'text', '', 6, 2, 12, 2)
    organization['description'] = 'header-organization'
    organization['options'] = {'mode': 'html', 'content': "<div style='height:100%;display:flex;align-items:center;justify-content:center;text-align:center;font-size:clamp(13px,.95vw,18px);font-weight:650'>Instalasi Pengelolaan Limbah Radioaktif<br>Direktorat Pengelolaan Fasilitas Ketenaganukliran</div>"}
    date_panel = _panel(3, 'stat', '', 0, 2, 6, 2)
    date_panel['description'] = 'header-date-wib'
    date_panel['targets'] = [_target('SELECT UNIX_TIMESTAMP() * 1000 AS value')]
    date_panel['fieldConfig'] = {'defaults': {'unit': 'time:DD/MM/YYYY', 'decimals': 0}, 'overrides': []}
    date_panel['options'] = {'colorMode': 'none', 'graphMode': 'none', 'justifyMode': 'center', 'orientation': 'horizontal', 'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False}, 'text': {'valueSize': 12}, 'textMode': 'value', 'wideLayout': True}
    update_panel = _panel(4, 'stat', '', 18, 2, 6, 2)
    update_panel['description'] = 'header-update-wib'
    update_panel['targets'] = [_target('SELECT UNIX_TIMESTAMP() * 1000 AS value')]
    update_panel['fieldConfig'] = {'defaults': {'unit': 'time:HH:mm:ss [WIB]', 'decimals': 0}, 'overrides': []}
    update_panel['options'] = {'colorMode': 'none', 'graphMode': 'none', 'justifyMode': 'center', 'orientation': 'horizontal', 'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False}, 'text': {'valueSize': 12}, 'textMode': 'value', 'wideLayout': True}
    return [title, organization, date_panel, update_panel]


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


def operation_page_stations(page_number: int) -> list[StationConfig]:
    if not 1 <= page_number <= OPERATIONS_PAGE_COUNT:
        raise ValueError(f"operations page must be 1..{OPERATIONS_PAGE_COUNT}")
    stations = station_catalog()
    page_size = max(1, (len(stations) + OPERATIONS_PAGE_COUNT - 1) // OPERATIONS_PAGE_COUNT)
    start = (page_number - 1) * page_size
    return stations[start : start + page_size]


def _latest_relation(stations: Sequence | None=None) -> str:
    ids = _station_ids(stations)
    return f'\nSELECT serid, dtom, doserate\nFROM vrecent\nWHERE serid IN ({ids})\n'.strip()


def _status_relation(stations: Sequence | None=None) -> str:
    ids = _station_ids(stations)
    wib_now = "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')"
    return f"\nSELECT\n  v.serid,\n  v.name,\n  v.location,\n  v.warnlevel,\n  v.alarmlevel,\n  COALESCE(v.maxidlemin, 30) AS maxidlemin,\n  v.dtom,\n  v.doserate,\n  COALESCE(\n    r.underlying_dose_status,\n    CASE\n      WHEN v.doserate >= v.alarmlevel THEN 'ALARM'\n      WHEN v.doserate >= v.warnlevel THEN 'ALERT'\n      ELSE 'NORMAL'\n    END\n  ) AS underlying_status,\n  CASE\n    WHEN v.dtom IS NULL OR v.doserate IS NULL THEN 'OFFLINE'\n    WHEN TIMESTAMPDIFF(SECOND, v.dtom, {wib_now}) > COALESCE(v.maxidlemin, 30) * 60 THEN 'OFFLINE'\n    WHEN COALESCE(r.suppressed, 0) = 1 THEN 'SUPPRESSED'\n    WHEN v.doserate >= v.alarmlevel THEN 'ALARM'\n    WHEN v.doserate >= v.warnlevel THEN 'ALERT'\n    ELSE 'NORMAL'\n  END AS status,\n  COALESCE(r.trigger_count, 0) AS trigger_count,\n  COALESCE(r.retrigger_locked, 0) AS retrigger_locked,\n  r.suppression_expires_at,\n  r.suppression_pic,\n  r.suppression_reason\nFROM vrecent v\nLEFT JOIN radmon_runtime_status r ON r.serid = v.serid\nWHERE v.serid IN ({ids})\n".strip()


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


def _dose_stat(panel_id, station, x, y, w, h=2):
    panel = _panel(panel_id, 'stat', f'[{station.serid}] {station.room} ({station.location})', x, y, w, h)
    panel['targets'] = [_target(f'\nSELECT doserate AS value\nFROM vrecent\nWHERE serid = {station.serid}\nLIMIT 1\n')]
    panel['fieldConfig'] = {'defaults': {'unit': 'suffix: µSv/h', 'decimals': 2, 'color': {'mode': 'fixed', 'fixedColor': 'green'}, 'thresholds': {'mode': 'absolute', 'steps': [{'color': 'green', 'value': None}]}}, 'overrides': []}
    panel['options'] = {'colorMode': 'value', 'graphMode': 'none', 'justifyMode': 'center', 'orientation': 'horizontal', 'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False}, 'text': {'valueSize': 28}, 'textMode': 'value', 'wideLayout': True}
    return panel


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


def _dose_sparkline(panel_id, station, x, y, w, h=1):
    panel = _panel(panel_id, 'timeseries', '', x, y, w, h)
    panel['description'] = 'latest-dose-sparkline'
    epoch = _utc_epoch_sql('m.dtom')
    panel['targets'] = [_target(f'\nSELECT {epoch} AS time, m.doserate AS value\nFROM measurement m\nWHERE m.serid = {station.serid}\n  AND {epoch} BETWEEN $__unixEpochFrom() AND $__unixEpochTo()\nORDER BY m.dtom\n', format_='time_series')]
    panel['fieldConfig'] = {'defaults': {'unit': 'suffix: µSv/h', 'decimals': 2, 'color': {'mode': 'fixed', 'fixedColor': 'green'}, 'custom': {'axisPlacement': 'hidden', 'drawStyle': 'line', 'fillOpacity': 18, 'lineWidth': 1, 'showPoints': 'never', 'spanNulls': 4000}}, 'overrides': []}
    panel['options'] = {'legend': {'displayMode': 'hidden', 'placement': 'bottom', 'showLegend': False}, 'tooltip': {'mode': 'single', 'sort': 'none'}}
    return panel


def _time_stat(panel_id, station, x, y, w, h=1):
    panel = _panel(panel_id, 'stat', '', x, y, w, h)
    panel['description'] = 'latest-measurement-time'
    epoch_ms = _utc_epoch_ms_sql('dtom')
    panel['targets'] = [_target(f'\nSELECT {epoch_ms} AS value\nFROM vrecent\nWHERE serid = {station.serid}\nLIMIT 1\n')]
    panel['fieldConfig'] = {'defaults': {'unit': 'time:DD/MM/YYYY HH:mm:ss', 'decimals': 0}, 'overrides': []}
    panel['options'] = {'colorMode': 'none', 'graphMode': 'none', 'justifyMode': 'center', 'orientation': 'horizontal', 'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False}, 'text': {'valueSize': 12}, 'textMode': 'value', 'wideLayout': True}
    return panel


def _operation_table(panel_id: int, title: str, x: int, y: int, w: int, h: int, *, stations: Sequence | None=None) -> dict[str, Any]:
    relation = status_relation(stations)
    table = _panel(panel_id, 'table', title, x, y, w, h)
    table['description'] = 'operational-condition'
    table['targets'] = [_target(f"\nSELECT\n  s.serid AS `ID`,\n  s.name AS `Ruangan`,\n  s.location AS `Lokasi`,\n  ROUND(s.doserate, 3) AS `Dose Rate`,\n  DATE_FORMAT(s.dtom, '%Y-%m-%d %H:%i:%s') AS `Waktu`,\n  s.status AS `Status`,\n  s.underlying_status AS `Underlying`,\n  s.trigger_count AS `Trigger`,\n  CASE WHEN s.retrigger_locked = 1 THEN 'LOCKED' ELSE '' END AS `Retrigger`,\n  DATE_FORMAT(s.suppression_expires_at, '%Y-%m-%d %H:%i:%s') AS `Suppression Until`,\n  COALESCE(s.suppression_pic, '') AS `PIC`,\n  COALESCE(s.suppression_reason, '') AS `Reason`\nFROM ({relation}) s\nORDER BY FIELD(s.status, 'OFFLINE', 'SUPPRESSED', 'ALARM', 'ALERT', 'NORMAL'), s.serid\n")]
    table['fieldConfig'] = {'defaults': {'custom': {'align': 'auto', 'cellOptions': {'type': 'auto'}}}, 'overrides': [{'matcher': {'id': 'byName', 'options': 'Dose Rate'}, 'properties': [{'id': 'unit', 'value': 'suffix: µSv/h'}, {'id': 'decimals', 'value': 3}]}, {'matcher': {'id': 'byName', 'options': 'Status'}, 'properties': [{'id': 'mappings', 'value': [{'type': 'value', 'options': {'NORMAL': {'color': 'green', 'text': 'NORMAL'}, 'ALERT': {'color': 'orange', 'text': 'ALERT'}, 'ALARM': {'color': 'red', 'text': 'ALARM'}, 'OFFLINE': {'color': 'purple', 'text': 'OFFLINE'}, 'SUPPRESSED': {'color': 'blue', 'text': 'SUPPRESSED'}}}]}, {'id': 'custom.cellOptions', 'value': {'type': 'color-background'}}]}]}
    table['options'] = {'cellHeight': 'sm', 'enablePagination': False, 'showHeader': True}
    return table


def _building_trend(panel_id: int, building: str, x: int, y: int, w: int, h: int):
    stations = _stations_for_building(building)
    panel = _panel(panel_id, 'timeseries', f'Dose Rate · Gedung {building} · 3 Jam', x, y, w, h)
    panel['description'] = 'building-dose-trend'
    epoch = _utc_epoch_sql('m.dtom')
    panel['targets'] = [_target(f"\nSELECT\n  {epoch} AS time,\n  CONCAT('[', d.serid, '] ', d.name) AS metric,\n  m.doserate AS value\nFROM measurement m\nJOIN device d ON d.serid = m.serid\nWHERE m.serid IN ({_station_ids(stations)})\n  AND {epoch} BETWEEN $__unixEpochFrom() AND $__unixEpochTo()\nORDER BY m.dtom, d.serid\n", format_='time_series')]
    panel['fieldConfig'] = {'defaults': {'unit': 'suffix: µSv/h', 'decimals': 3, 'min': 0, 'color': {'mode': 'palette-classic'}, 'custom': {'drawStyle': 'line', 'fillOpacity': 0, 'lineWidth': 1, 'showPoints': 'never', 'spanNulls': 4000}}, 'overrides': []}
    panel['options'] = {'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True, 'calcs': []}, 'tooltip': {'mode': 'multi', 'sort': 'desc'}}
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
            panel_id,
            title,
            sql,
            x,
            14,
            6,
            4,
            unit="suffix: µSv/h" if decimals else "none",
            color=color,
            decimals=decimals,
            value_size=42,
        ))
        panel_id += 1
    return dashboard


def _build_page_three_base(page_number: int = 1) -> dict[str, Any]:
    if not 1 <= page_number <= OPERATIONS_PAGE_COUNT:
        raise ValueError(f"operations page must be 1..{OPERATIONS_PAGE_COUNT}")
    dashboard = _base_dashboard(
        "RadMon TV · Operations",
        OPERATIONS_PAGE_UIDS[page_number - 1],
        time_from="now-24h",
    )
    status_relation = _status_relation()
    pie = _panel(10, "piechart", "Status Detector", 0, 4, 10, 7)
    pie["targets"] = [_target(f"""
SELECT s.status AS metric, COUNT(*) AS value
FROM ({status_relation}) s
GROUP BY s.status
ORDER BY FIELD(s.status, 'ALARM', 'ALERT', 'OFFLINE', 'NORMAL')
""")]
    pie["fieldConfig"] = {"defaults": {"unit": "none", "decimals": 0}, "overrides": []}
    pie["options"] = {
        "displayLabels": ["name", "value"],
        "legend": {
            "displayMode": "table",
            "placement": "bottom",
            "showLegend": True,
            "values": ["value"],
        },
        "pieType": "donut",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    dashboard["panels"].append(pie)
    dashboard["panels"].append(
        _operation_table(
            11,
            f"Kondisi Operasional Detector · Page {page_number}/{OPERATIONS_PAGE_COUNT}",
            10,
            4,
            14,
            7,
            stations=operation_page_stations(page_number),
        )
    )
    stats = [
        (12, "NORMAL", "green", 0),
        (13, "ALERT", "orange", 6),
        (14, "ALARM", "red", 12),
        (15, "OFFLINE", "purple", 18),
    ]
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
            value_size=42,
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
    alarms["fieldConfig"] = {
        "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
        "overrides": [],
    }
    alarms["options"] = {"cellHeight": "sm", "enablePagination": False, "showHeader": True}
    dashboard["panels"].append(alarms)
    return dashboard

def build_page_three(page_number: int = 1) -> dict[str, Any]:
    dashboard = _build_page_three_base(page_number)
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
    wib_now = "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')"
    alarms["targets"] = [_target(f"""
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
WHERE a.serid IN ({_station_ids()})
  AND a.dtoa >= DATE_SUB({wib_now}, INTERVAL 24 HOUR)
ORDER BY a.dtoa DESC, a.serid
LIMIT 12
""")]
    return dashboard


def build_dashboard_payloads() -> list[dict[str, Any]]:
    return [
        build_page_one(),
        build_page_two(),
        *(build_page_three(page_number) for page_number in range(1, OPERATIONS_PAGE_COUNT + 1)),
    ]


def build_playlist_payload(*, resource_version: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": PLAYLIST_UID, "namespace": "default"}
    if resource_version:
        metadata["resourceVersion"] = resource_version

    items: list[dict[str, str]] = []
    for operations_uid in OPERATIONS_PAGE_UIDS:
        items.extend(
            [
                {"type": "dashboard_by_uid", "value": PAGE_UIDS[0]},
                {"type": "dashboard_by_uid", "value": PAGE_UIDS[1]},
                {"type": "dashboard_by_uid", "value": operations_uid},
            ]
        )

    return {
        "kind": "Playlist",
        "apiVersion": "playlist.grafana.app/v1",
        "metadata": metadata,
        "spec": {
            "title": "RadMon TV",
            "interval": PLAYLIST_INTERVAL,
            "items": items,
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
