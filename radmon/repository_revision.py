"""Production-schema compatibility for the deployed ipradmon database."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def apply() -> None:
    from . import repository as repo
    from .models import LatestReading, Measurement

    production_schema = {
        "device": {"serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel", "unit", "audiopath", "hwaddress", "hwtype", "description"},
        "measurement": {"serid", "dtom", "doserate", "dose", "previnterval", "stat"},
        "recent": {"serid", "dtom", "doserate", "dose", "lastrate", "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose", "avgdose", "firstmea", "lastmea", "lastmeasec", "meacount"},
        "vrecent": {"serid", "name", "location", "warnlevel", "alarmlevel", "unit", "audiopath", "description", "maxidlemin", "dtom", "doserate", "dose", "lastrate", "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose", "avgdose", "lastmea", "lastmeasec", "meacount", "firstmea"},
        "alarm": {"serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag"},
        "applog": {"ts", "id", "msg"},
        "news": {"ts", "code", "content"},
        "rawdata": {"serid", "dtom", "val"},
    }
    repo.REQUIRED_SCHEMA = production_schema

    def validate_schema(self) -> list[str]:
        names = tuple(production_schema)
        placeholders = ",".join("?" for _ in names)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
SELECT TABLE_NAME, COLUMN_NAME
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = ? AND TABLE_NAME IN ({placeholders})
""",
                    (self.settings.db_name, *names),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        actual: dict[str, set[str]] = {}
        for row in rows:
            table = str(repo._row_get(row, "TABLE_NAME", 0)).lower()
            column = str(repo._row_get(row, "COLUMN_NAME", 1)).lower()
            actual.setdefault(table, set()).add(column)
        missing: list[str] = []
        for table, expected in production_schema.items():
            if table not in actual:
                missing.append(f"table {table}")
                continue
            for column in sorted(expected - actual[table]):
                missing.append(f"{table}.{column}")
        return missing

    def live_rows(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, name, location, warnlevel, alarmlevel, unit, description,
       maxidlemin, dtom, doserate, dose, lastrate, minrate, maxrate,
       avgrate, lastdose, mindose, maxdose, avgdose, lastmea,
       lastmeasec, meacount, firstmea
FROM vrecent
ORDER BY serid
"""
                )
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

    def latest_reading(self, serid: int | None = None) -> LatestReading:
        station = self.station_config(serid)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT dtom, doserate, lastrate
FROM vrecent
WHERE serid = ?
LIMIT 1
""",
                    (station.serid,),
                )
                row = cursor.fetchone()
            if row is None:
                return LatestReading(station=station, measured_at=None, dose_rate=None)
            return LatestReading(
                station=station,
                measured_at=repo._row_get(row, "dtom", 0),
                dose_rate=float(repo._row_get(row, "doserate", 1)) if repo._row_get(row, "doserate", 1) is not None else None,
                previous_dose_rate=float(repo._row_get(row, "lastrate", 2)) if repo._row_get(row, "lastrate", 2) is not None else None,
            )
        finally:
            connection.close()

    def insert_measurement(self, measurement: Measurement, *, raw: str | None = None) -> float:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                previous = self._previous_measurement(cursor, measurement.serid, measurement.measured_at)
                previous_time = repo._row_get(previous, "dtom", 0)
                previous_rate = repo._row_get(previous, "doserate", 1)
                previous_dose = repo._row_get(previous, "dose", 2)
                interval = measurement.previnterval
                if isinstance(previous_time, datetime):
                    measured = int(round((measurement.measured_at - previous_time).total_seconds()))
                    if measured > 0:
                        interval = measured
                dose = 0.0
                if previous_rate is not None and interval > 0:
                    dose = ((float(previous_rate) + float(measurement.dose_rate)) / 2.0) * (interval / 3600.0)
                if raw is not None:
                    cursor.execute(
                        "INSERT INTO rawdata (serid, dtom, val) VALUES (?, ?, ?)",
                        (measurement.serid, measurement.measured_at, raw),
                    )
                cursor.execute(
                    """
INSERT INTO measurement (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)
""",
                    (measurement.serid, measurement.measured_at, measurement.dose_rate, dose, interval, measurement.stat),
                )
                repo.upsert_recent(
                    cursor,
                    measurement,
                    dose=dose,
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
                    f"""
SELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, pic, note, i_op, i_flag
FROM alarm
WHERE {' AND '.join(clauses)}
ORDER BY dtoa DESC, serid DESC
LIMIT ?
""",
                    tuple(params),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        keys = ("serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag")
        return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]

    def last_alarm(self, serid: int | None = None) -> dict[str, Any] | None:
        rows = alarm_history(self, serid=serid, limit=1)
        if not rows:
            return None
        row = rows[0]
        row["type"] = "ALARM" if int(row.get("lvl") or 0) >= 2 else "ALERT"
        return row

    repo.MariaDBRepository.validate_schema = validate_schema
    repo.MariaDBRepository.live_rows = live_rows
    repo.MariaDBRepository.latest_reading = latest_reading
    repo.MariaDBRepository.insert_measurement = insert_measurement
    repo.MariaDBRepository.alarm_history = alarm_history
    repo.MariaDBRepository.last_alarm = last_alarm
