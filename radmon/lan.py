from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import importlib
import os
from typing import Any, Callable, Iterable

from .repository import upsert_recent
from .security import SecurityStore


@dataclass(frozen=True, slots=True)
class LanSource:
    source_id: str
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(slots=True)
class PullResult:
    source_id: str
    inserted_measurements: int = 0
    mirrored_alarms: int = 0
    error: str | None = None


LIVE_KEYS = (
    "serid", "name", "location", "warnlevel", "alarmlevel", "unit", "audiopath",
    "description", "maxidlemin", "dtom", "doserate", "dose", "lastrate",
    "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose",
    "avgdose", "lastmea", "lastmeasec", "meacount", "firstmea",
)


@dataclass(slots=True)
class LivePullResult:
    source_id: str
    live_stations: int = 0
    inserted_measurements: int = 0
    mirrored_alarms: int = 0
    error: str | None = None


@dataclass(slots=True)
class BackfillPullResult:
    source_id: str
    backfill_serid: int | None = None
    inserted_measurements: int = 0
    checkpoint: datetime | None = None
    error: str | None = None

def parse_lan_sources() -> list[LanSource]:
    raw = os.getenv("RADMON_LAN_SOURCES", "").strip()
    if not raw:
        return []
    user = os.getenv("RADMON_LAN_DB_USER", "").strip()
    password = os.getenv("RADMON_LAN_DB_PASSWORD", "")
    database = os.getenv("RADMON_LAN_DB_NAME", "ipradmon").strip() or "ipradmon"
    port = int(os.getenv("RADMON_LAN_DB_PORT", "3306"))
    result: list[LanSource] = []
    seen: set[str] = set()
    for raw_item in raw.split(";"):
        item = raw_item.strip()
        if not item:
            continue
        if item.count("@") != 1:
            raise ValueError("RADMON_LAN_SOURCES harus source@host;source@host")
        source_id, host = (part.strip() for part in item.split("@", 1))
        if not source_id or not host or source_id in seen:
            raise ValueError(f"LAN source tidak valid: {item!r}")
        seen.add(source_id)
        result.append(LanSource(source_id, host, port, user, password, database))
    return result


def _shared_serids() -> set[int]:
    raw = os.getenv("RADMON_SHARED_SERIDS", "").strip()
    if not raw:
        return set()
    result: set[int] = set()
    for item in raw.split(","):
        text = item.strip()
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("RADMON_SHARED_SERIDS harus daftar SERID numerik dipisahkan koma")
        result.add(int(text))
    return result


class LanCheckpointStore:
    def __init__(self, security_store: SecurityStore) -> None:
        self.store = security_store

    def load(self, source_id: str, serid: int) -> datetime | None:
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT last_dtom FROM lan_checkpoints WHERE source_id = ? AND serid = ?",
                (source_id, int(serid)),
            ).fetchone()
        return datetime.fromisoformat(str(row[0])) if row else None

    def save(self, source_id: str, serid: int, value: datetime) -> None:
        with self.store._connection() as connection:
            connection.execute(
                """
INSERT INTO lan_checkpoints (source_id, serid, last_dtom)
VALUES (?, ?, ?)
ON CONFLICT(source_id, serid) DO UPDATE SET last_dtom = excluded.last_dtom
""",
                (source_id, int(serid), value.isoformat()),
            )

    def _ensure_alarm_checkpoint_table(self) -> None:
        with self.store._connection() as connection:
            connection.execute('\nCREATE TABLE IF NOT EXISTS lan_alarm_checkpoints (\n  source_id TEXT PRIMARY KEY,\n  last_dtoa TEXT NOT NULL,\n  last_serid INTEGER NOT NULL\n)\n')

    def load_alarm(self, source_id: str) -> tuple[datetime, int] | None:
        self._ensure_alarm_checkpoint_table()
        with self.store._connection() as connection:
            row = connection.execute('SELECT last_dtoa, last_serid FROM lan_alarm_checkpoints WHERE source_id = ?', (source_id,)).fetchone()
        if not row:
            return None
        return (datetime.fromisoformat(str(row[0])), int(row[1]))

    def save_alarm(self, source_id: str, dtoa: datetime, serid: int) -> None:
        self._ensure_alarm_checkpoint_table()
        with self.store._connection() as connection:
            connection.execute('\nINSERT INTO lan_alarm_checkpoints (source_id, last_dtoa, last_serid)\nVALUES (?, ?, ?)\nON CONFLICT(source_id) DO UPDATE SET\n  last_dtoa = excluded.last_dtoa,\n  last_serid = excluded.last_serid\n', (source_id, dtoa.isoformat(), int(serid)))


class RemoteMariaDBSource:
    """Production source adapter. Collector methods are read-only; ACK is explicit."""

    def __init__(self, source: LanSource, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self.source = source
        self._connection_factory = connection_factory or self._connect

    def _connect(self):
        mariadb = importlib.import_module("mariadb")
        return mariadb.connect(
            host=self.source.host,
            port=self.source.port,
            user=self.source.user,
            password=self.source.password,
            database=self.source.database,
            autocommit=False,
            connect_timeout=5,
        )

    def _connection(self):
        return self._connection_factory()

    @staticmethod
    def _dict_rows(rows, keys):
        return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]

    def devices(self) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT serid, name, location, warnlevel, alarmlevel, maxidlemin, unit, description
FROM device ORDER BY serid"""
                )
                rows = cursor.fetchall()
            return self._dict_rows(rows, ("serid", "name", "location", "warnlevel", "alarmlevel", "maxidlemin", "unit", "description"))
        finally:
            connection.close()

    def measurements_after(self, serid: int, after: datetime | None, limit: int) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                if after is None:
                    cursor.execute(
                        """SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement WHERE serid = ? ORDER BY dtom ASC LIMIT ?""",
                        (int(serid), max(1, int(limit))),
                    )
                else:
                    cursor.execute(
                        """SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement WHERE serid = ? AND dtom > ? ORDER BY dtom ASC LIMIT ?""",
                        (int(serid), after, max(1, int(limit))),
                    )
                rows = cursor.fetchall()
            return self._dict_rows(rows, ("serid", "dtom", "doserate", "dose", "previnterval", "stat"))
        finally:
            connection.close()

    def latest_measurement_at_or_before(self, serid: int, cutoff: datetime) -> datetime | None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT MAX(dtom) FROM measurement WHERE serid = ? AND dtom < ?",
                    (int(serid), cutoff),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            value = row.get("MAX(dtom)") if isinstance(row, dict) else row[0]
            return value if isinstance(value, datetime) else None
        finally:
            connection.close()

    def alarm_columns(self) -> set[str]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'alarm'""",
                    (self.source.database,),
                )
                rows = cursor.fetchall()
            return {str(row.get("COLUMN_NAME") if isinstance(row, dict) else row[0]).lower() for row in rows}
        finally:
            connection.close()

    def alarms(self, limit: int = 500) -> list[dict[str, Any]]:
        columns = self.alarm_columns()
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                if {"dtoa", "lvl", "mvalue", "thvalue", "nhit", "i_op", "pic", "note"}.issubset(columns):
                    cursor.execute(
                        """SELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, i_flag, i_op, pic, note
FROM alarm ORDER BY dtoa DESC LIMIT ?""",
                        (max(1, int(limit)),),
                    )
                    keys = ("serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "i_flag", "i_op", "pic", "note")
                else:
                    cursor.execute(
                        """SELECT alarmid, serid, dtom, type, msg
FROM alarm ORDER BY dtom DESC LIMIT ?""",
                        (max(1, int(limit)),),
                    )
                    keys = ("alarmid", "serid", "dtom", "type", "msg")
                return self._dict_rows(cursor.fetchall(), keys)
        finally:
            connection.close()

    def ack_legacy(self, serid: int, dtoa: datetime, *, action: str, pic: str, note: str, at: datetime) -> bool:
        columns = self.alarm_columns()
        if "dtoa" not in columns or "i_op" not in columns:
            raise RuntimeError("source alarm schema tidak mendukung ACK legacy")
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE alarm
SET ack = 1, i_op = ?, pic = ?, note = ?
WHERE serid = ? AND dtoa = ? AND i_op IS NULL""",
                    (at, pic, f"[{action}] {note}".strip(), int(serid), dtoa),
                )
                changed = int(getattr(cursor, "rowcount", 0))
            connection.commit()
            return changed == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def live_rows(self) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute('\nSELECT serid, name, location, warnlevel, alarmlevel, unit, audiopath,\n       description, maxidlemin, dtom, doserate, dose, lastrate,\n       minrate, maxrate, avgrate, lastdose, mindose, maxdose,\n       avgdose, lastmea, lastmeasec, meacount, firstmea\nFROM vrecent\nORDER BY serid\n')
                rows = cursor.fetchall()
            return self._dict_rows(rows, LIVE_KEYS)
        finally:
            connection.close()

    def alarms_after(self, checkpoint: tuple[datetime, int] | None, limit: int=500) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                if checkpoint is None:
                    cursor.execute('\nSELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, i_flag, i_op, pic, note\nFROM alarm\nORDER BY dtoa ASC, serid ASC\nLIMIT ?\n', (max(1, int(limit)),))
                else:
                    dtoa, serid = checkpoint
                    cursor.execute('\nSELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, i_flag, i_op, pic, note\nFROM alarm\nWHERE dtoa > ? OR (dtoa = ? AND serid > ?)\nORDER BY dtoa ASC, serid ASC\nLIMIT ?\n', (dtoa, dtoa, int(serid), max(1, int(limit))))
                rows = cursor.fetchall()
            keys = ('serid', 'dtoa', 'lvl', 'mvalue', 'thvalue', 'nhit', 'ack', 'i_flag', 'i_op', 'pic', 'note')
            return self._dict_rows(rows, keys)
        finally:
            connection.close()

    def active_alarm_keys(self) -> list[tuple[int, datetime]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute('\nSELECT serid, dtoa\nFROM alarm\nWHERE i_flag = 0\nORDER BY dtoa ASC, serid ASC\n')
                rows = cursor.fetchall()
            result: list[tuple[int, datetime]] = []
            for row in rows:
                if isinstance(row, dict):
                    serid = row.get('serid')
                    dtoa = row.get('dtoa')
                else:
                    serid, dtoa = (row[0], row[1])
                if serid is not None and isinstance(dtoa, datetime):
                    result.append((int(serid), dtoa))
            return result
        finally:
            connection.close()


class MariaCentralStore:
    """Import remote samples/events into the existing central ipradmon schema."""

    def __init__(self, settings, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self._connection_factory = connection_factory

    def _connection(self):
        if self._connection_factory is not None:
            return self._connection_factory()
        from .db import connect_mariadb
        return connect_mariadb(self.settings)

    def ensure_remote_device(self, source_id: str, row: dict[str, Any]) -> None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                serid = int(row["serid"])
                cursor.execute(
                    "SELECT name, location, hwaddress, hwtype FROM device WHERE serid = ?",
                    (serid,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if isinstance(existing, dict):
                        old_name = str(existing.get("name") or "")
                        old_location = str(existing.get("location") or "")
                        old_source = str(existing.get("hwaddress") or "")
                        old_type = str(existing.get("hwtype") or "")
                    else:
                        old_name, old_location, old_source, old_type = (str(value or "") for value in existing[:4])
                    if old_type == "remote" and old_source and old_source != source_id:
                        compatible = (
                            old_name == str(row.get("name") or "")
                            and old_location == str(row.get("location") or "")
                        )
                        if serid not in _shared_serids() or not compatible:
                            raise RuntimeError(
                                f"SERID conflict {serid}: source {old_source} vs {source_id}"
                            )
                        return
                cursor.execute(
                    """INSERT INTO device
  (serid, name, location, maxidlemin, warnlevel, alarmlevel, unit,
   audiopath, hwaddress, hwtype, description)
VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'remote', ?)
ON DUPLICATE KEY UPDATE
  name = VALUES(name), location = VALUES(location), maxidlemin = VALUES(maxidlemin),
  warnlevel = VALUES(warnlevel), alarmlevel = VALUES(alarmlevel), unit = VALUES(unit),
  hwaddress = VALUES(hwaddress), hwtype = 'remote', description = VALUES(description)""",
                    (
                        serid,
                        str(row.get("name") or f"Remote {serid}"),
                        str(row.get("location") or source_id),
                        int(row.get("maxidlemin") or 30),
                        float(row.get("warnlevel") or 0),
                        float(row.get("alarmlevel") or 0),
                        str(row.get("unit") or "µSv/h"),
                        source_id[:50],
                        str(row.get("description") or f"Synced from {source_id}")[:255],
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_measurements(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0
        connection = self._connection()
        inserted = 0
        try:
            with connection.cursor() as cursor:
                for row in values:
                    cursor.execute('\nINSERT IGNORE INTO measurement (serid, dtom, doserate, dose, previnterval, stat)\nVALUES (?, ?, ?, ?, ?, ?)\n', (int(row['serid']), row['dtom'], float(row['doserate']), row.get('dose'), int(row.get('previnterval') or 0), int(row.get('stat') or 0)))
                    if int(getattr(cursor, 'rowcount', 0)) == 1:
                        inserted += 1
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _alarm_values(source_id: str, row: dict[str, Any]) -> tuple[int, datetime, str, str]:
        serid = int(row["serid"])
        event_time = row.get("dtoa", row.get("dtom"))
        if not isinstance(event_time, datetime):
            raise ValueError("remote alarm time tidak valid")
        if "lvl" in row:
            level = "ALARM" if int(row.get("lvl") or 0) >= 2 else "ALERT"
            measured = row.get("mvalue")
            threshold = row.get("thvalue")
            hit = int(row.get("nhit") or 0)
            measured_text = "-" if measured is None else f"{float(measured):.3f} µSv/h"
            threshold_text = "-" if threshold is None else f"{float(threshold):.3f} µSv/h"
            msg = f"[{source_id}] {level}: dose rate {measured_text}; threshold {threshold_text}; hit {hit}"
        else:
            level = str(row.get("type") or "ALERT").upper()
            msg = f"[{source_id}] {str(row.get('msg') or level)}"
        return serid, event_time, level, msg[:4000]

    def mirror_alarm_events(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0
        connection = self._connection()
        changed = 0
        try:
            with connection.cursor() as cursor:
                for row in values:
                    cursor.execute('\nINSERT INTO alarm\n  (serid, dtoa, lvl, mvalue, thvalue, nhit, ack, pic, note, i_op, i_flag)\nVALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\nON DUPLICATE KEY UPDATE\n  lvl = VALUES(lvl), mvalue = VALUES(mvalue), thvalue = VALUES(thvalue),\n  nhit = VALUES(nhit), ack = VALUES(ack), pic = VALUES(pic), note = VALUES(note),\n  i_op = VALUES(i_op), i_flag = VALUES(i_flag)\n', (int(row['serid']), row['dtoa'], int(row.get('lvl') or 0), float(row.get('mvalue') or 0.0), float(row.get('thvalue') or 0.0), int(row.get('nhit') or 0), int(row.get('ack') or 0), row.get('pic'), row.get('note'), row.get('i_op'), int(row.get('i_flag') or 0)))
                    changed += 1
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _upsert_live_rows_base(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0
        for row in values:
            self.ensure_remote_device(source_id, row)
        connection = self._connection()
        changed = 0
        try:
            with connection.cursor() as cursor:
                for row in values:
                    cursor.execute('\nINSERT INTO recent\n  (serid, dtom, doserate, dose, lastrate, minrate, maxrate, avgrate,\n   lastdose, mindose, maxdose, avgdose, firstmea, lastmea, lastmeasec, meacount)\nVALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\nON DUPLICATE KEY UPDATE\n  dtom = VALUES(dtom), doserate = VALUES(doserate), dose = VALUES(dose),\n  lastrate = VALUES(lastrate), minrate = VALUES(minrate), maxrate = VALUES(maxrate),\n  avgrate = VALUES(avgrate), lastdose = VALUES(lastdose), mindose = VALUES(mindose),\n  maxdose = VALUES(maxdose), avgdose = VALUES(avgdose), firstmea = VALUES(firstmea),\n  lastmea = VALUES(lastmea), lastmeasec = VALUES(lastmeasec), meacount = VALUES(meacount)\n', (int(row['serid']), row.get('dtom'), float(row['doserate']) if row.get('doserate') is not None else 0.0, row.get('dose'), row.get('lastrate'), row.get('minrate'), row.get('maxrate'), row.get('avgrate'), row.get('lastdose'), row.get('mindose'), row.get('maxdose'), row.get('avgdose'), row.get('firstmea'), row.get('lastmea'), row.get('lastmeasec'), row.get('meacount')))
                    changed += 1
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_live_rows(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        changed = self._upsert_live_rows_base(source_id, values)
        if not values:
            return changed
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                for row in values:
                    measured_at = row.get("dtom")
                    rate = row.get("doserate")
                    if not isinstance(measured_at, datetime) or rate is None:
                        continue
                    try:
                        interval = int(row.get("lastmeasec") or 2)
                    except (TypeError, ValueError):
                        interval = 2
                    if interval < 1 or interval > 3600:
                        interval = 2
                    cursor.execute(
                        """
    INSERT IGNORE INTO measurement
      (serid, dtom, doserate, dose, previnterval, stat)
    VALUES (?, ?, ?, ?, ?, 0)
    """,
                        (
                            int(row["serid"]), measured_at, float(rate),
                            float(row.get("dose") or 0.0), interval,
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return changed

    def mark_alarm_handled(self, keys: Iterable[tuple[int, datetime]]) -> int:
        values = list(keys)
        if not values:
            return 0
        connection = self._connection()
        changed = 0
        try:
            with connection.cursor() as cursor:
                for serid, event_time in values:
                    cursor.execute('\nUPDATE alarm\nSET i_flag = 1\nWHERE serid = ? AND dtoa = ? AND i_flag = 0\n', (int(serid), event_time))
                    changed += max(0, int(getattr(cursor, 'rowcount', 0)))
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class LanAggregator:
    def __init__(
        self,
        central_store: Any,
        checkpoints: LanCheckpointStore,
        *,
        remote_factory: Callable[[LanSource], Any] | None = None,
        alarm_mirror: Any | None = None,
        batch_size: int = 1000,
    ) -> None:
        self.central = central_store
        self.checkpoints = checkpoints
        self.remote_factory = remote_factory or (lambda source: RemoteMariaDBSource(source))
        self.alarm_mirror = alarm_mirror
        self.batch_size = max(1, int(batch_size))

    def _mapped_alarm_rows(self, source_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            remote_serid = int(item["serid"])
            item["_remote_serid"] = remote_serid
            item["serid"] = self.checkpoints.store.resolve_station(source_id, remote_serid)
            mapped.append(item)
        return mapped

    def _ensure_device(self, source: LanSource, remote_device: dict[str, Any]) -> tuple[int, int]:
        remote_serid = int(remote_device["serid"])
        central_serid = self.checkpoints.store.resolve_station(source.source_id, remote_serid)
        central_device = dict(remote_device)
        central_device["serid"] = central_serid
        self.central.ensure_remote_device(source.source_id, central_device)
        return remote_serid, central_serid

    def run_source_once(self, source):
        """Compatibility helper: one live/alarm poll plus one detector backfill step."""
        result = PullResult(source.source_id)
        live_result = run_live_once(self, source)
        result.mirrored_alarms = live_result.mirrored_alarms
        if live_result.error:
            result.error = live_result.error
            return result
        backfill_result = run_backfill_once(self, source, 0)
        result.inserted_measurements = backfill_result.inserted_measurements
        result.error = backfill_result.error
        return result

    def drain_source_until(self, source: LanSource, cutoff: datetime) -> dict[int, datetime | None]:
        remote = self.remote_factory(source)
        drained: dict[int, datetime | None] = {}
        for remote_device in remote.devices():
            remote_serid, central_serid = self._ensure_device(source, remote_device)
            watermark = remote.latest_measurement_at_or_before(remote_serid, cutoff)
            if watermark is None:
                drained[remote_serid] = self.checkpoints.load(source.source_id, remote_serid)
                continue
            while True:
                after = self.checkpoints.load(source.source_id, remote_serid)
                if after is not None and after >= watermark:
                    drained[remote_serid] = after
                    break
                remote_rows = remote.measurements_after(remote_serid, after, self.batch_size)
                bounded = [
                    row for row in remote_rows
                    if isinstance(row.get("dtom"), datetime) and row["dtom"] < cutoff
                ]
                if not bounded:
                    raise RuntimeError(
                        f"drain incomplete source={source.source_id} serid={remote_serid} watermark={watermark}"
                    )
                central_rows = [dict(row, serid=central_serid) for row in bounded]
                self.central.import_measurements(source.source_id, central_rows)
                last_time = bounded[-1]["dtom"]
                self.checkpoints.save(source.source_id, remote_serid, last_time)
        return drained

    def run_sources_once(self, sources: Iterable[LanSource]) -> list[PullResult]:
        return [self.run_source_once(source) for source in sources]

    def _run_live_core_once(self, source):
        result = LivePullResult(source.source_id)
        try:
            remote = self.remote_factory(source)
            raw_live = remote.live_rows()
            mapped_live: list[dict[str, Any]] = []
            for row in raw_live:
                remote_serid = int(row['serid'])
                central_serid = self.checkpoints.store.resolve_station(source.source_id, remote_serid)
                item = dict(row)
                item['_remote_serid'] = remote_serid
                item['serid'] = central_serid
                mapped_live.append(item)
            if hasattr(self.central, 'upsert_live_rows'):
                self.central.upsert_live_rows(source.source_id, mapped_live)
            result.live_stations = len(mapped_live)
            alarm_checkpoint = self.checkpoints.load_alarm(source.source_id)
            raw_alarms = remote.alarms_after(alarm_checkpoint, 500)
            historical_seed = alarm_checkpoint is None
            mapped_alarms: list[dict[str, Any]] = []
            for row in raw_alarms:
                item = dict(row)
                remote_serid = int(item['serid'])
                item['_remote_serid'] = remote_serid
                item['serid'] = self.checkpoints.store.resolve_station(source.source_id, remote_serid)
                if historical_seed:
                    item['_historical_seed'] = True
                mapped_alarms.append(item)
            if mapped_alarms and self.alarm_mirror is not None:
                result.mirrored_alarms += int(self.alarm_mirror.mirror(source.source_id, mapped_alarms))
            if mapped_alarms and hasattr(self.central, 'mirror_alarm_events'):
                self.central.mirror_alarm_events(source.source_id, mapped_alarms)
            if raw_alarms:
                last_alarm = raw_alarms[-1]
                self.checkpoints.save_alarm(source.source_id, last_alarm['dtoa'], int(last_alarm['serid']))
        except Exception as exc:
            result.error = str(exc)
        return result

    def run_live_once(self, source):
        historical_seed = self.checkpoints.load_alarm(source.source_id) is None
        result = self._run_live_core_once(source)
        if result.error:
            return result
        try:
            remote = self.remote_factory(source)
            state_rows = remote.alarm_states(2000)
            mapped: list[dict[str, Any]] = []
            for row in state_rows:
                item = dict(row)
                remote_serid = int(item["serid"])
                item["_remote_serid"] = remote_serid
                item["serid"] = self.checkpoints.store.resolve_station(
                    source.source_id, remote_serid
                )
                if historical_seed:
                    item["_historical_seed"] = True
                mapped.append(item)
            if mapped and self.alarm_mirror is not None:
                self.alarm_mirror.mirror(source.source_id, mapped)
            if mapped and hasattr(self.central, "mirror_alarm_events"):
                self.central.mirror_alarm_events(source.source_id, mapped)

            if self.alarm_mirror is not None:
                key_reader = getattr(remote, "active_alarm_keys", None)
                if callable(key_reader):
                    active_keys: set[tuple[int, datetime]] = set()
                    for remote_serid, event_time in key_reader():
                        central_serid = self.checkpoints.store.resolve_station(
                            source.source_id, int(remote_serid)
                        )
                        active_keys.add((int(central_serid), event_time))
                    handled = self.alarm_mirror.reconcile_source_active_keys(
                        source.source_id, active_keys
                    )
                    if handled and hasattr(self.central, "mark_alarm_handled"):
                        self.central.mark_alarm_handled(handled)
        except Exception as exc:
            result.error = str(exc)
        return result

    def run_backfill_once(self, source, station_index: int=0):
        result = BackfillPullResult(source.source_id)
        try:
            remote = self.remote_factory(source)
            devices = sorted(remote.devices(), key=lambda row: int(row['serid']))
            if not devices:
                return result
            selected = devices[int(station_index) % len(devices)]
            remote_serid, central_serid = self._ensure_device(source, selected)
            result.backfill_serid = remote_serid
            after = self.checkpoints.load(source.source_id, remote_serid)
            result.checkpoint = after
            remote_rows = remote.measurements_after(remote_serid, after, self.batch_size)
            if not remote_rows:
                return result
            central_rows = [dict(row, serid=central_serid) for row in remote_rows]
            result.inserted_measurements = int(self.central.import_measurements(source.source_id, central_rows))
            last_time = remote_rows[-1].get('dtom')
            if not isinstance(last_time, datetime):
                raise ValueError('remote measurement time tidak valid')
            self.checkpoints.save(source.source_id, remote_serid, last_time)
            result.checkpoint = last_time
        except Exception as exc:
            result.error = str(exc)
        return result
