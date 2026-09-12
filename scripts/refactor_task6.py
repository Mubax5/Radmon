from __future__ import annotations

import ast
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def replace_assignment(path: Path, name: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.Assign, ast.AnnAssign))
        and ((isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in item.targets))
             or (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == name))
    )
    lines = source.splitlines()
    lines[node.lineno - 1:node.end_lineno] = textwrap.dedent(replacement).strip().splitlines()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def replace_class_method(path: Path, class_name: str, method_name: str, method_source: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == class_name)
    method = next((item for item in cls.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name), None)
    replacement = textwrap.dedent(method_source).strip("\n").splitlines()
    replacement = ["    " + line if line else "" for line in replacement]
    lines = source.splitlines()
    if method is None:
        insert_at = cls.end_lineno
        lines[insert_at:insert_at] = [""] + replacement
    else:
        lines[method.lineno - 1:method.end_lineno] = replacement
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


repo_path = ROOT / "radmon/repository.py"
replace_assignment(repo_path, "REQUIRED_SCHEMA", '''
REQUIRED_SCHEMA = {
    "device": {"serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel", "unit", "audiopath", "hwaddress", "hwtype", "description"},
    "measurement": {"serid", "dtom", "doserate", "dose", "previnterval", "stat"},
    "recent": {"serid", "dtom", "doserate", "dose", "lastrate", "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose", "avgdose", "firstmea", "lastmea", "lastmeasec", "meacount"},
    "vrecent": {"serid", "name", "location", "warnlevel", "alarmlevel", "unit", "audiopath", "description", "maxidlemin", "dtom", "doserate", "dose", "lastrate", "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose", "avgdose", "lastmea", "lastmeasec", "meacount", "firstmea"},
    "alarm": {"serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag"},
    "applog": {"ts", "id", "msg"},
    "news": {"ts", "code", "content"},
    "rawdata": {"serid", "dtom", "val"},
}
''')

repo_methods = {
"validate_schema": '''
def validate_schema(self) -> list[str]:
    names = tuple(REQUIRED_SCHEMA)
    placeholders = ",".join("?" for _ in names)
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME IN ({placeholders})",
                (self.settings.db_name, *names),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    actual: dict[str, set[str]] = {}
    for row in rows:
        table = str(_row_get(row, "TABLE_NAME", 0)).lower()
        column = str(_row_get(row, "COLUMN_NAME", 1)).lower()
        actual.setdefault(table, set()).add(column)
    missing: list[str] = []
    for table, expected in REQUIRED_SCHEMA.items():
        if table not in actual:
            missing.append(f"table {table}")
            continue
        for column in sorted(expected - actual[table]):
            missing.append(f"{table}.{column}")
    return missing
''',
"live_rows": '''
def live_rows(self) -> list[dict[str, Any]]:
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
SELECT serid, name, location, warnlevel, alarmlevel, unit, description,
       maxidlemin, dtom, doserate, dose, lastrate, minrate, maxrate,
       avgrate, lastdose, mindose, maxdose, avgdose, lastmea,
       lastmeasec, meacount, firstmea
FROM vrecent ORDER BY serid
""")
            rows = cursor.fetchall()
    finally:
        connection.close()
    keys = (
        "serid", "name", "location", "warnlevel", "alarmlevel", "unit", "description",
        "maxidlemin", "dtom", "doserate", "dose", "lastrate", "minrate", "maxrate",
        "avgrate", "lastdose", "mindose", "maxdose", "avgdose", "lastmea",
        "lastmeasec", "meacount", "firstmea",
    )
    return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
''',
"latest_reading": '''
def latest_reading(self, serid: int | None = None) -> LatestReading:
    station = self.station_config(serid)
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT dtom, doserate, lastrate FROM vrecent WHERE serid = ? LIMIT 1", (station.serid,))
            row = cursor.fetchone()
        if row is None:
            return LatestReading(station=station, measured_at=None, dose_rate=None)
        return LatestReading(
            station=station,
            measured_at=_row_get(row, "dtom", 0),
            dose_rate=float(_row_get(row, "doserate", 1)) if _row_get(row, "doserate", 1) is not None else None,
            previous_dose_rate=float(_row_get(row, "lastrate", 2)) if _row_get(row, "lastrate", 2) is not None else None,
        )
    finally:
        connection.close()
''',
"insert_measurement": '''
def insert_measurement(self, measurement: Measurement, *, raw: str | None = None) -> float:
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            previous = self._previous_measurement(cursor, measurement.serid, measurement.measured_at)
            previous_time = _row_get(previous, "dtom", 0)
            previous_rate = _row_get(previous, "doserate", 1)
            previous_dose = _row_get(previous, "dose", 2)
            interval = measurement.previnterval
            if isinstance(previous_time, datetime):
                measured = int(round((measurement.measured_at - previous_time).total_seconds()))
                if measured > 0:
                    interval = measured
            dose = 0.0
            if previous_rate is not None and interval > 0:
                dose = ((float(previous_rate) + float(measurement.dose_rate)) / 2.0) * (interval / 3600.0)
            if raw is not None:
                cursor.execute("INSERT INTO rawdata (serid, dtom, val) VALUES (?, ?, ?)", (measurement.serid, measurement.measured_at, raw))
            cursor.execute(
                "INSERT INTO measurement (serid, dtom, doserate, dose, previnterval, stat) VALUES (?, ?, ?, ?, ?, ?)",
                (measurement.serid, measurement.measured_at, measurement.dose_rate, dose, interval, measurement.stat),
            )
            upsert_recent(
                cursor, measurement, dose=dose,
                previous_time=previous_time if isinstance(previous_time, datetime) else None,
                previous_rate=float(previous_rate) if previous_rate is not None else None,
                previous_dose=float(previous_dose) if previous_dose is not None else None,
                interval=interval,
            )
        connection.commit()
        return dose
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
''',
"alarm_history": '''
def alarm_history(self, start: datetime | None = None, end: datetime | None = None, *, serid: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    station_id = serid or self.settings.serid
    clauses = ["serid = ?"]
    params: list[Any] = [station_id]
    if start is not None:
        clauses.append("dtoa >= ?")
        params.append(start)
    if end is not None:
        clauses.append("dtoa <= ?")
        params.append(end)
    params.append(max(1, int(limit)))
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, pic, note, i_op, i_flag FROM alarm WHERE {' AND '.join(clauses)} ORDER BY dtoa DESC, serid DESC LIMIT ?",
                tuple(params),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    keys = ("serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag")
    result = []
    for raw in rows:
        item = dict(raw) if isinstance(raw, dict) else dict(zip(keys, raw))
        level = "ALARM" if int(item.get("lvl") or 0) >= 2 else "ALERT"
        item["alarmid"] = 0
        item["dtom"] = item.get("dtoa")
        item["type"] = level
        item["msg"] = f"dose={item.get('mvalue')} threshold={item.get('thvalue')} hit={item.get('nhit') or 0}"
        result.append(item)
    return result
''',
"last_alarm": '''
def last_alarm(self, serid: int | None = None) -> dict[str, Any] | None:
    rows = self.alarm_history(serid=serid, limit=1)
    return rows[0] if rows else None
''',
"record_alarm": '''
def record_alarm(self, serid: int, alarm_type: str, message: str, *, at: datetime | None = None) -> int:
    when = at or datetime.now()
    level = 2 if str(alarm_type).upper() == "ALARM" else 1
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO alarm (serid, dtoa, lvl, mvalue, thvalue, nhit, ack, pic, note, i_op, i_flag) VALUES (?, ?, ?, 0, 0, 1, 0, NULL, ?, NULL, 0)",
                (int(serid), when, level, str(message)[:1000]),
            )
        connection.commit()
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
''',
"append_log": '''
def append_log(self, message: str, *, at: datetime | None = None) -> None:
    connection = self._connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO applog (ts, id, msg) VALUES (?, ?, ?)", (at or datetime.now(), 0, str(message)[:4000]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
''',
}
for name, body in repo_methods.items():
    replace_class_method(repo_path, "MariaDBRepository", name, body)

archive_store = ROOT / "radmon/archive_store.py"
replace_assignment(archive_store, "TABLE_COLUMNS", '''
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "device": ("serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel", "unit", "audiopath", "hwaddress", "hwtype", "description"),
    "measurement": ("serid", "dtom", "doserate", "dose", "previnterval", "stat"),
    "alarm": ("serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag"),
    "rawdata": ("serid", "dtom", "val"),
    "applog": ("ts", "id", "msg"),
    "news": ("ts", "code", "content"),
}
''')
replace_assignment(archive_store, "TIME_COLUMNS", '''
TIME_COLUMNS: dict[str, str] = {
    "measurement": "dtom",
    "alarm": "dtoa",
    "rawdata": "dtom",
    "applog": "ts",
    "news": "ts",
}
''')
replace_class_method(archive_store, "CentralArchiveStore", "monthly_recap_rows", '''
def monthly_recap_rows(self, quarter: Quarter) -> list[dict[str, Any]]:
    devices = {int(row["serid"]): row for row in self.table_rows("device", quarter)}
    months = range((quarter.number - 1) * 3 + 1, (quarter.number - 1) * 3 + 4)
    recap: dict[tuple[int, int], dict[str, Any]] = {}
    for month in months:
        for serid, device in devices.items():
            recap[(month, serid)] = {
                "year": quarter.year, "month": month, "serid": serid,
                "name": str(device.get("name") or ""), "location": str(device.get("location") or ""),
                "first_measurement": None, "last_measurement": None, "sample_count": 0,
                "minimum": None, "average": None, "maximum": None,
                "dose_sum": 0.0, "rate_sum": 0.0, "alert_count": 0, "alarm_count": 0,
            }
    for row in self.table_rows("measurement", quarter):
        serid = int(row["serid"])
        measured_at = row.get("dtom")
        if not isinstance(measured_at, datetime):
            continue
        key = (measured_at.month, serid)
        if key not in recap:
            device = devices.get(serid, {})
            recap[key] = {
                "year": measured_at.year, "month": measured_at.month, "serid": serid,
                "name": str(device.get("name") or ""), "location": str(device.get("location") or ""),
                "first_measurement": None, "last_measurement": None, "sample_count": 0,
                "minimum": None, "average": None, "maximum": None,
                "dose_sum": 0.0, "rate_sum": 0.0, "alert_count": 0, "alarm_count": 0,
            }
        item = recap[key]
        rate = row.get("doserate")
        if rate is None:
            continue
        rate_value = float(rate)
        item["sample_count"] += 1
        item["rate_sum"] += rate_value
        item["dose_sum"] += float(row.get("dose") or 0.0)
        item["minimum"] = rate_value if item["minimum"] is None else min(float(item["minimum"]), rate_value)
        item["maximum"] = rate_value if item["maximum"] is None else max(float(item["maximum"]), rate_value)
        first = item["first_measurement"]
        last = item["last_measurement"]
        item["first_measurement"] = measured_at if first is None or measured_at < first else first
        item["last_measurement"] = measured_at if last is None or measured_at > last else last
    for row in self.table_rows("alarm", quarter):
        serid = int(row["serid"])
        event_time = row.get("dtoa") or row.get("dtom")
        if not isinstance(event_time, datetime):
            continue
        key = (event_time.month, serid)
        if key not in recap:
            continue
        if row.get("lvl") is not None:
            level = "ALARM" if int(row.get("lvl") or 0) >= 2 else "ALERT"
        else:
            level = str(row.get("type") or "").upper()
        if level == "ALERT":
            recap[key]["alert_count"] += 1
        elif level == "ALARM":
            recap[key]["alarm_count"] += 1
    rows = []
    for key in sorted(recap):
        item = dict(recap[key])
        count = int(item["sample_count"])
        item["average"] = float(item["rate_sum"]) / count if count else None
        rows.append(item)
    return rows
''')

archive_reports = ROOT / "radmon/archive_reports.py"
replace_class_method(archive_reports, "ArchiveReportRepository", "alarm_history", '''
def alarm_history(self, start: datetime | None = None, end: datetime | None = None, *, serid: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    if start is None or end is None:
        items = self.catalog.list_archives(limit=1000)
        complete = [item for item in items if item.get("state") in {"COMPLETE", "SEALED", "PURGING"}]
        if not complete:
            return []
        start = min(_parse_datetime(str(item["start_at"])) for item in complete)
        end = max(_parse_datetime(str(item["end_at"])) for item in complete)
        if start is None or end is None:
            return []
    start_value = _as_local_naive(start, self.timezone_name)
    end_value = _as_local_naive(end, self.timezone_name)
    station_id = int(serid) if serid is not None else None
    rows = []
    for item in self._items(start, end):
        for raw in self._stream_csv(item, "alarm.csv"):
            event_time = _parse_datetime(raw.get("dtoa") or raw.get("dtom"))
            if event_time is None:
                continue
            event_n = _as_local_naive(event_time, self.timezone_name)
            row_serid = int(raw.get("serid") or 0)
            if station_id is not None and row_serid != station_id:
                continue
            if not (start_value <= event_n < end_value):
                continue
            level = int(raw.get("lvl") or 0)
            alarm_type = str(raw.get("type") or ("ALARM" if level >= 2 else "ALERT"))
            measured = raw.get("mvalue")
            threshold = raw.get("thvalue")
            message = str(raw.get("msg") or "")
            if not message:
                message = f"dose={measured or '-'} threshold={threshold or '-'} hit={raw.get('nhit') or 0}"
            rows.append({
                "alarmid": int(raw.get("alarmid") or 0), "serid": row_serid,
                "dtom": event_n, "dtoa": event_n, "type": alarm_type, "lvl": level,
                "msg": message,
                "mvalue": float(measured) if measured not in (None, "") else None,
                "thvalue": float(threshold) if threshold not in (None, "") else None,
                "nhit": int(raw.get("nhit") or 0), "ack": int(raw.get("ack") or 0),
                "pic": raw.get("pic"), "note": raw.get("note"),
                "i_op": _parse_datetime(raw.get("i_op")), "i_flag": int(raw.get("i_flag") or 0),
            })
            if len(rows) >= max(1, int(limit)):
                return rows
    rows.sort(key=lambda row: row["dtom"])
    return rows[: max(1, int(limit))]
''')

init_path = ROOT / "radmon/__init__.py"
init_text = init_path.read_text(encoding="utf-8")
for revision in ("repository_revision", "archive_store_revision", "archive_reports_revision"):
    pattern = rf"\nfrom \.{revision} import apply as _apply_{revision}\n_apply_{revision}\(\)\ndel _apply_{revision}\n"
    init_text, count = re.subn(pattern, "\n", init_text)
    if count != 1:
        raise RuntimeError(f"apply block not found: {revision}")
init_path.write_text(init_text, encoding="utf-8")

for name in ("repository_revision.py", "archive_store_revision.py", "archive_reports_revision.py"):
    (ROOT / "radmon" / name).unlink()

# Remove one-shot migration artifacts before the resulting commit.
Path(__file__).unlink()
(ROOT / ".github/workflows/refactor-task6.yml").unlink()
