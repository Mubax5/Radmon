from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Callable, Iterable

from .config import Settings
from .db import connect_mariadb
from .models import LatestReading, Measurement, StationConfig


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

    def station_config(self, serid: int | None = None) -> StationConfig:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
SELECT serid, name, location, warnlevel, alarmlevel, maxidlemin, unit
FROM device
WHERE serid = ?
""", (station_id,))
                row = cursor.fetchone()
            if row is None:
                return StationConfig(serid=station_id, building=self.settings.building, room=self.settings.room, location=self.settings.location, warnlevel=self.settings.warnlevel, alarmlevel=self.settings.alarmlevel, maxidlemin=self.settings.maxidlemin, unit=self.settings.unit)
            location = str(_row_get(row, "location", 2) or self.settings.location)
            return StationConfig(serid=int(_row_get(row, "serid", 0)), building=self.settings.building, room=str(_row_get(row, "name", 1) or self.settings.room), location=location, warnlevel=float(_row_get(row, "warnlevel", 3) or self.settings.warnlevel), alarmlevel=float(_row_get(row, "alarmlevel", 4) or self.settings.alarmlevel), maxidlemin=int(_row_get(row, "maxidlemin", 5) or self.settings.maxidlemin), unit=str(_row_get(row, "unit", 6) or self.settings.unit))
        finally:
            connection.close()

    def insert_measurement(self, measurement: Measurement, *, raw: str | None = None, queue_sync: bool = True) -> str:
        connection = self._connect()
        sample_key = make_sample_key(measurement)
        try:
            with connection.cursor() as cursor:
                if raw is not None:
                    cursor.execute("INSERT INTO rawdata (serid, dtom, raw) VALUES (?, ?, ?)", (measurement.serid, measurement.measured_at, raw))
                cursor.execute("""
INSERT INTO measurement (serid, dtom, doserate, previnterval, stat)
VALUES (?, ?, ?, ?, ?)
""", (measurement.serid, measurement.measured_at, measurement.dose_rate, measurement.previnterval, measurement.stat))
                if queue_sync:
                    cursor.execute("""
INSERT IGNORE INTO radmon_sync_queue
  (sample_key, serid, dtom, doserate, previnterval, stat, attempts, created_at)
VALUES (?, ?, ?, ?, ?, ?, 0, ?)
""", (sample_key, measurement.serid, measurement.measured_at, measurement.dose_rate, measurement.previnterval, measurement.stat, datetime.now()))
            connection.commit()
            return sample_key
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
                cursor.execute("""
SELECT m.dtom, m.doserate,
       (SELECT p.doserate FROM measurement p
        WHERE p.serid = m.serid AND p.dtom < m.dtom
        ORDER BY p.dtom DESC LIMIT 1) AS previous_doserate
FROM measurement m
WHERE m.serid = ?
ORDER BY m.dtom DESC
LIMIT 1
""", (station.serid,))
                row = cursor.fetchone()
            if row is None:
                return LatestReading(station=station, measured_at=None, dose_rate=None)
            return LatestReading(station=station, measured_at=_row_get(row, "dtom", 0), dose_rate=float(_row_get(row, "doserate", 1)) if _row_get(row, "doserate", 1) is not None else None, previous_dose_rate=float(_row_get(row, "previous_doserate", 2)) if _row_get(row, "previous_doserate", 2) is not None else None)
        finally:
            connection.close()

    def measurement_history(self, start: datetime, end: datetime, *, serid: int | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE serid = ? AND dtom >= ? AND dtom <= ?
ORDER BY dtom ASC
LIMIT ?
""", (station_id, start, end, max(1, int(limit))))
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
            clauses.append("started_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("started_at <= ?")
            params.append(end)
        params.append(max(1, int(limit)))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"""
SELECT eventid, serid, state, severity, started_at, ended_at,
       last_value, threshold_value, acknowledged_at, acknowledged_by,
       acknowledgement_note, updated_at
FROM radmon_alarm_event
WHERE {' AND '.join(clauses)}
ORDER BY started_at DESC
LIMIT ?
""", tuple(params))
                rows = cursor.fetchall()
            keys = ("eventid", "serid", "state", "severity", "started_at", "ended_at", "last_value", "threshold_value", "acknowledged_at", "acknowledged_by", "acknowledgement_note", "updated_at")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def active_alarm(self, serid: int | None = None) -> dict[str, Any] | None:
        station_id = serid or self.settings.serid
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
SELECT eventid, serid, state, severity, started_at, ended_at,
       last_value, threshold_value, acknowledged_at, acknowledged_by,
       acknowledgement_note, updated_at
FROM radmon_alarm_event
WHERE serid = ? AND ended_at IS NULL
ORDER BY started_at DESC
LIMIT 1
""", (station_id,))
                row = cursor.fetchone()
            if row is None:
                return None
            keys = ("eventid", "serid", "state", "severity", "started_at", "ended_at", "last_value", "threshold_value", "acknowledged_at", "acknowledged_by", "acknowledgement_note", "updated_at")
            return dict(row) if isinstance(row, dict) else dict(zip(keys, row))
        finally:
            connection.close()

    def open_alarm(self, serid: int, state: str, severity: str, started_at: datetime, last_value: float | None, threshold_value: float | None) -> int:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
INSERT INTO radmon_alarm_event
  (serid, state, severity, started_at, last_value, threshold_value, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
""", (serid, state, severity, started_at, last_value, threshold_value, started_at))
                event_id = int(cursor.lastrowid)
            connection.commit()
            return event_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_alarm(self, event_id: int, state: str, severity: str, value: float | None, threshold: float | None, at: datetime) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
UPDATE radmon_alarm_event
SET state = ?, severity = ?, last_value = ?, threshold_value = ?, updated_at = ?
WHERE eventid = ? AND ended_at IS NULL
""", (state, severity, value, threshold, at, event_id))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close_alarm(self, event_id: int, ended_at: datetime, last_value: float | None = None) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
UPDATE radmon_alarm_event
SET ended_at = ?, last_value = COALESCE(?, last_value), updated_at = ?
WHERE eventid = ? AND ended_at IS NULL
""", (ended_at, last_value, ended_at, event_id))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acknowledge_alarm(self, event_id: int, operator: str, note: str, at: datetime | None = None) -> None:
        when = at or datetime.now()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
UPDATE radmon_alarm_event
SET acknowledged_at = ?, acknowledged_by = ?, acknowledgement_note = ?, updated_at = ?
WHERE eventid = ?
""", (when, operator.strip(), note.strip(), when, event_id))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def pending_sync(self, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
SELECT queueid, sample_key, serid, dtom, doserate, previnterval, stat, attempts
FROM radmon_sync_queue
WHERE sent_at IS NULL
ORDER BY queueid ASC
LIMIT ?
""", (max(1, int(limit)),))
                rows = cursor.fetchall()
            keys = ("queueid", "sample_key", "serid", "dtom", "doserate", "previnterval", "stat", "attempts")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def mark_sync_sent(self, queue_ids: Iterable[int], at: datetime | None = None) -> None:
        ids = tuple(int(value) for value in queue_ids)
        if not ids:
            return
        when = at or datetime.now()
        placeholders = ",".join("?" for _ in ids)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE radmon_sync_queue SET sent_at = ?, last_error = NULL WHERE queueid IN ({placeholders})", (when, *ids))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_sync_failed(self, queue_ids: Iterable[int], error: str) -> None:
        ids = tuple(int(value) for value in queue_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"""
UPDATE radmon_sync_queue
SET attempts = attempts + 1, last_error = ?
WHERE queueid IN ({placeholders})
""", (error[:1000], *ids))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
