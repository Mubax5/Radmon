from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Callable

from .config import Settings
from .db import connect_mariadb
from .models import LatestReading, Measurement, StationConfig
from .stations import station_by_id, station_catalog


REQUIRED_SCHEMA = {
    "device": {"serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel", "unit", "audiopath", "hwaddress", "hwtype", "description"},
    "measurement": {"serid", "dtom", "doserate", "dose", "previnterval", "stat"},
    "recent": {"serid", "dtom", "doserate", "dose", "lastrate", "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose", "avgdose", "firstmea", "lastmea", "lastmeasec", "meacount"},
    "alarm": {"alarmid", "serid", "dtom", "type", "msg"},
    "applog": {"logid", "dtom", "msg"},
    "news": {"newsid", "dtom", "title", "content"},
    "rawdata": {"rawid", "serid", "dtom", "raw"},
}


def make_sample_key(measurement: Measurement) -> str:
    canonical = (
        f"{measurement.serid}|{measurement.measured_at.isoformat(timespec='microseconds')}|"
        f"{measurement.dose_rate:.12g}|{measurement.previnterval}|{measurement.stat}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_get(row: Any, key: str, index: int) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _display_unit(value: Any) -> str:
    text = str(value or "µSv/h").strip().replace("μ", "µ")
    if text.lower() == "usv/h":
        return "µSv/h"
    return text


def _building_from_location(location: str, fallback: str) -> str:
    digits = "".join(ch for ch in location if ch.isdigit())
    return digits or fallback


def upsert_recent(
    cursor: Any,
    measurement: Measurement,
    *,
    dose: float,
    previous_time: datetime | None,
    previous_rate: float | None,
    previous_dose: float | None,
    interval: int,
) -> None:
    cursor.execute(
        """
INSERT INTO recent
  (serid, dtom, doserate, dose, lastrate, minrate, maxrate, avgrate,
   lastdose, mindose, maxdose, avgdose, firstmea, lastmea, lastmeasec, meacount)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
ON DUPLICATE KEY UPDATE
  lastrate = doserate,
  lastdose = dose,
  dtom = VALUES(dtom),
  doserate = VALUES(doserate),
  dose = VALUES(dose),
  minrate = LEAST(COALESCE(minrate, VALUES(doserate)), VALUES(doserate)),
  maxrate = GREATEST(COALESCE(maxrate, VALUES(doserate)), VALUES(doserate)),
  avgrate = ((COALESCE(avgrate, 0) * COALESCE(meacount, 0)) + VALUES(doserate)) / (COALESCE(meacount, 0) + 1),
  mindose = LEAST(COALESCE(mindose, VALUES(dose)), VALUES(dose)),
  maxdose = GREATEST(COALESCE(maxdose, VALUES(dose)), VALUES(dose)),
  avgdose = ((COALESCE(avgdose, 0) * COALESCE(meacount, 0)) + VALUES(dose)) / (COALESCE(meacount, 0) + 1),
  firstmea = COALESCE(firstmea, VALUES(firstmea)),
  lastmea = VALUES(lastmea),
  lastmeasec = VALUES(lastmeasec),
  meacount = COALESCE(meacount, 0) + 1
""",
        (
            measurement.serid,
            measurement.measured_at,
            measurement.dose_rate,
            dose,
            float(previous_rate) if previous_rate is not None else measurement.dose_rate,
            measurement.dose_rate,
            measurement.dose_rate,
            measurement.dose_rate,
            float(previous_dose) if previous_dose is not None else 0.0,
            dose,
            dose,
            dose,
            previous_time if isinstance(previous_time, datetime) else measurement.measured_at,
            measurement.measured_at,
            interval,
        ),
    )


class MariaDBRepository:
    def __init__(self, settings: Settings, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self._connection_factory = connection_factory or (lambda: connect_mariadb(settings))

    def _connect(self) -> Any:
        return self._connection_factory()

    def ping(self) -> bool:
        try:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                return True
            finally:
                connection.close()
        except Exception:
            return False

    def validate_schema(self) -> list[str]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT TABLE_NAME, COLUMN_NAME
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = ?
  AND TABLE_NAME IN ('device','measurement','recent','alarm','applog','news','rawdata')
""",
                    (self.settings.db_name,),
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

    def require_schema(self) -> None:
        missing = self.validate_schema()
        if missing:
            raise RuntimeError("Schema ipradmon tidak sesuai. Missing: " + ", ".join(missing))

    def _station_from_row(self, row: Any) -> StationConfig:
        location = str(_row_get(row, "location", 2) or self.settings.location)
        return StationConfig(
            serid=int(_row_get(row, "serid", 0)),
            building=_building_from_location(location, self.settings.building),
            room=str(_row_get(row, "name", 1) or self.settings.room),
            location=location,
            warnlevel=float(_row_get(row, "warnlevel", 3) if _row_get(row, "warnlevel", 3) is not None else self.settings.warnlevel),
            alarmlevel=float(_row_get(row, "alarmlevel", 4) if _row_get(row, "alarmlevel", 4) is not None else self.settings.alarmlevel),
            maxidlemin=int(_row_get(row, "maxidlemin", 5) if _row_get(row, "maxidlemin", 5) is not None else self.settings.maxidlemin),
            unit=_display_unit(_row_get(row, "unit", 6) or self.settings.unit),
        )

    def station_config(self, serid: int | None = None) -> StationConfig:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, name, location, warnlevel, alarmlevel, maxidlemin, unit
FROM device
WHERE serid = ?
""",
                    (station_id,),
                )
                row = cursor.fetchone()
            if row is not None:
                return self._station_from_row(row)
        finally:
            connection.close()
        catalog_station = station_by_id(station_id)
        if catalog_station is not None:
            return catalog_station
        return StationConfig(
            serid=station_id,
            building=self.settings.building,
            room=self.settings.room,
            location=self.settings.location,
            warnlevel=self.settings.warnlevel,
            alarmlevel=self.settings.alarmlevel,
            maxidlemin=self.settings.maxidlemin,
            unit=_display_unit(self.settings.unit),
        )

    def station_configs(self) -> list[StationConfig]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, name, location, warnlevel, alarmlevel, maxidlemin, unit
FROM device
ORDER BY serid
"""
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        if not rows:
            return station_catalog()
        return [self._station_from_row(row) for row in rows]

    def ensure_station_catalog(self) -> None:
        """Insert missing detector metadata without overwriting deployed rows."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for station in station_catalog():
                    cursor.execute(
                        """
INSERT IGNORE INTO device
  (serid, name, location, maxidlemin, warnlevel, alarmlevel, unit,
   audiopath, hwaddress, hwtype, description)
VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'detector', ?)
""",
                        (
                            station.serid,
                            station.room,
                            station.location,
                            station.maxidlemin,
                            station.warnlevel,
                            station.alarmlevel,
                            station.unit,
                            f"CATALOG-{station.serid}",
                            f"Radiation monitor {station.room}",
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_dummy_station(self) -> None:
        self.ensure_station_catalog()

    def _previous_measurement(self, cursor: Any, serid: int, before: datetime) -> Any:
        cursor.execute(
            """
SELECT dtom, doserate, dose
FROM measurement
WHERE serid = ? AND dtom < ?
ORDER BY dtom DESC
LIMIT 1
""",
            (serid, before),
        )
        return cursor.fetchone()

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
                    cursor.execute(
                        "INSERT INTO rawdata (serid, dtom, raw) VALUES (?, ?, ?)",
                        (measurement.serid, measurement.measured_at, raw),
                    )
                cursor.execute(
                    """
INSERT INTO measurement (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)
""",
                    (
                        measurement.serid,
                        measurement.measured_at,
                        measurement.dose_rate,
                        dose,
                        interval,
                        measurement.stat,
                    ),
                )
                upsert_recent(
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

    def latest_reading(self, serid: int | None = None) -> LatestReading:
        station = self.station_config(serid)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT m.dtom, m.doserate,
       (SELECT p.doserate FROM measurement p
        WHERE p.serid = m.serid AND p.dtom < m.dtom
        ORDER BY p.dtom DESC LIMIT 1) AS previous_doserate
FROM measurement m
WHERE m.serid = ?
ORDER BY m.dtom DESC
LIMIT 1
""",
                    (station.serid,),
                )
                row = cursor.fetchone()
            if row is None:
                return LatestReading(station=station, measured_at=None, dose_rate=None)
            return LatestReading(
                station=station,
                measured_at=_row_get(row, "dtom", 0),
                dose_rate=float(_row_get(row, "doserate", 1)) if _row_get(row, "doserate", 1) is not None else None,
                previous_dose_rate=float(_row_get(row, "previous_doserate", 2)) if _row_get(row, "previous_doserate", 2) is not None else None,
            )
        finally:
            connection.close()

    def measurement_history(self, start: datetime, end: datetime, *, serid: int | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE serid = ? AND dtom >= ? AND dtom <= ?
ORDER BY dtom ASC
LIMIT ?
""",
                    (station_id, start, end, max(1, int(limit))),
                )
                rows = cursor.fetchall()
            keys = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def measurements_after(self, after: datetime, *, serid: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE serid = ? AND dtom > ?
ORDER BY dtom ASC
LIMIT ?
""",
                    (station_id, after, max(1, int(limit))),
                )
                rows = cursor.fetchall()
            keys = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def alarm_history(self, start: datetime | None = None, end: datetime | None = None, *, serid: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        station_id = serid or self.settings.serid
        clauses = ["serid = ?"]
        params: list[Any] = [station_id]
        if start is not None:
            clauses.append("dtom >= ?")
            params.append(start)
        if end is not None:
            clauses.append("dtom <= ?")
            params.append(end)
        params.append(max(1, int(limit)))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
SELECT alarmid, serid, dtom, `type`, msg
FROM alarm
WHERE {' AND '.join(clauses)}
ORDER BY dtom DESC, alarmid DESC
LIMIT ?
""",
                    tuple(params),
                )
                rows = cursor.fetchall()
            keys = ("alarmid", "serid", "dtom", "type", "msg")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def last_alarm(self, serid: int | None = None) -> dict[str, Any] | None:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT alarmid, serid, dtom, `type`, msg FROM alarm WHERE serid = ? ORDER BY dtom DESC, alarmid DESC LIMIT 1",
                    (station_id,),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            keys = ("alarmid", "serid", "dtom", "type", "msg")
            return dict(row) if isinstance(row, dict) else dict(zip(keys, row))
        finally:
            connection.close()

    def record_alarm(self, serid: int, alarm_type: str, message: str, *, at: datetime | None = None) -> int:
        when = at or datetime.now()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO alarm (serid, dtom, `type`, msg) VALUES (?, ?, ?, ?)",
                    (serid, when, alarm_type[:50], message[:255]),
                )
                alarm_id = int(cursor.lastrowid)
            connection.commit()
            return alarm_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_log(self, message: str, *, at: datetime | None = None) -> None:
        when = at or datetime.now()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO applog (dtom, msg) VALUES (?, ?)", (when, message))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
