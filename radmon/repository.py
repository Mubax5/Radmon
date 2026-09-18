from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Callable

from .config import Settings
from .db import connect_mariadb
from .models import LatestReading, Measurement, StationConfig
from .recent_read_model import RollingRecentManager
from .stations import station_by_id, station_catalog


LOG = logging.getLogger(__name__)

BASE_REQUIRED_SCHEMA = {
    "device": {"serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel", "unit", "audiopath", "hwaddress", "hwtype", "description"},
    "measurement": {"serid", "dtom", "doserate", "dose", "previnterval", "stat"},
    "alarm": {"serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag"},
    "applog": {"ts", "id", "msg"},
    "news": {"ts", "code", "content"},
    "rawdata": {"serid", "dtom", "val"},
}

REQUIRED_SCHEMA = {
    **BASE_REQUIRED_SCHEMA,
    "recent": {"serid", "dtom", "doserate", "dose", "previnterval", "stat"},
    "vrecent": {
        "serid", "name", "location", "warnlevel", "alarmlevel", "unit", "audiopath",
        "description", "maxidlemin", "dtom", "doserate", "dose", "previnterval", "stat",
        "underlying_status", "status", "suppressed", "trigger_count", "retrigger_locked",
        "suppression_expires_at", "suppression_pic", "suppression_reason",
    },
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
    previous_time: datetime | None = None,
    previous_rate: float | None = None,
    previous_dose: float | None = None,
    interval: int,
) -> None:
    """Compatibility helper: mirror one real sample into the rolling table only."""
    del previous_time, previous_rate, previous_dose
    RollingRecentManager.mirror_sample(
        cursor,
        serid=measurement.serid,
        dtom=measurement.measured_at,
        doserate=measurement.dose_rate,
        dose=dose,
        previnterval=interval,
        stat=measurement.stat,
    )


class MariaDBRepository:
    def __init__(self, settings: Settings, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self._connection_factory = connection_factory or (lambda: connect_mariadb(settings))
        self._recent_manager = RollingRecentManager(
            settings,
            connection_factory=self._connection_factory,
        )

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

    def validate_schema(self, required_schema: dict[str, set[str]] | None = None) -> list[str]:
        required = required_schema or REQUIRED_SCHEMA
        names = tuple(required)
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
        for table, expected in required.items():
            if table not in actual:
                missing.append(f"table {table}")
                continue
            for column in sorted(expected - actual[table]):
                missing.append(f"{table}.{column}")
        return missing

    def require_base_schema(self) -> None:
        missing = self.validate_schema(BASE_REQUIRED_SCHEMA)
        if missing:
            raise RuntimeError("Schema ipradmon tidak sesuai. Missing: " + ", ".join(missing))

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

    def has_station(self, serid: int) -> bool:
        """Check persisted station ownership without catalog fallback metadata."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM device WHERE serid = ?", (int(serid),))
                return cursor.fetchone() is not None
        finally:
            connection.close()

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
        dose = 0.0
        interval = measurement.previnterval
        try:
            with connection.cursor() as cursor:
                previous = self._previous_measurement(cursor, measurement.serid, measurement.measured_at)
                previous_time = _row_get(previous, "dtom", 0)
                previous_rate = _row_get(previous, "doserate", 1)
                if isinstance(previous_time, datetime):
                    measured = int(round((measurement.measured_at - previous_time).total_seconds()))
                    if measured > 0:
                        interval = measured
                if previous_rate is not None and interval > 0:
                    dose = ((float(previous_rate) + float(measurement.dose_rate)) / 2.0) * (interval / 3600.0)
                if raw is not None:
                    cursor.execute(
                        "INSERT INTO rawdata (serid, dtom, val) VALUES (?, ?, ?)",
                        (measurement.serid, measurement.measured_at, raw),
                    )
                cursor.execute(
                    "INSERT INTO measurement (serid, dtom, doserate, dose, previnterval, stat) VALUES (?, ?, ?, ?, ?, ?)",
                    (measurement.serid, measurement.measured_at, measurement.dose_rate, dose, interval, measurement.stat),
                )
            # Historical data is authoritative: persist it before touching disposable recent.
            connection.commit()

            try:
                with connection.cursor() as cursor:
                    upsert_recent(cursor, measurement, dose=dose, interval=interval)
                connection.commit()
            except Exception:
                connection.rollback()
                LOG.exception(
                    "measurement tersimpan tetapi mirror recent gagal serid=%s dtom=%s",
                    measurement.serid,
                    measurement.measured_at,
                )
            try:
                self._recent_manager.cleanup()
            except Exception:
                # Cleanup failure may leave a slightly wider window; it must not undo history.
                pass
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
                    "SELECT dtom, doserate FROM vrecent "
                    "WHERE serid = ? AND dtom IS NOT NULL ORDER BY dtom DESC LIMIT 2",
                    (station.serid,),
                )
                rows = cursor.fetchall()
            if not rows:
                return LatestReading(station=station, measured_at=None, dose_rate=None)
            current = rows[0]
            previous = rows[1] if len(rows) > 1 else None
            current_rate = _row_get(current, "doserate", 1)
            previous_rate = _row_get(previous, "doserate", 1) if previous is not None else None
            return LatestReading(
                station=station,
                measured_at=_row_get(current, "dtom", 0),
                dose_rate=float(current_rate) if current_rate is not None else None,
                previous_dose_rate=float(previous_rate) if previous_rate is not None else None,
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

    def last_alarm(self, serid: int | None = None) -> dict[str, Any] | None:
        rows = self.alarm_history(serid=serid, limit=1)
        return rows[0] if rows else None

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

    def append_log(self, message: str, *, at: datetime | None = None) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO applog (ts, id, msg) VALUES (?, ?, ?)",
                    (at or datetime.now(), 0, str(message)[:4000]),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def live_rows(self) -> list[dict[str, Any]]:
        """Return one newest bounded monitoring row per detector.

        Fully-offline detectors (no recent rows left) keep their NULL
        vrecent row via LEFT JOIN so the admin panel renders last-known /
        OFFLINE state instead of dropping the detector entirely. The
        newest-dtom lookup hits indexed ``recent``, while status columns
        keep coming from ``vrecent`` (single source of offline truth).
        """
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT v.serid, v.name, v.location, v.warnlevel, v.alarmlevel, v.unit,
       v.description, v.maxidlemin, v.dtom, v.doserate, v.dose,
       v.previnterval, v.stat, v.underlying_status, v.status,
       v.suppressed, v.trigger_count, v.retrigger_locked,
       v.suppression_expires_at, v.suppression_pic, v.suppression_reason
FROM vrecent v
LEFT JOIN (
  SELECT serid, MAX(dtom) AS dtom
  FROM recent
  WHERE dtom IS NOT NULL
  GROUP BY serid
) newest ON newest.serid = v.serid
WHERE newest.dtom IS NULL OR v.dtom = newest.dtom
ORDER BY v.serid
"""
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        keys = (
            "serid", "name", "location", "warnlevel", "alarmlevel", "unit", "description",
            "maxidlemin", "dtom", "doserate", "dose", "previnterval", "stat",
            "underlying_status", "status", "suppressed", "trigger_count", "retrigger_locked",
            "suppression_expires_at", "suppression_pic", "suppression_reason",
        )
        return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
