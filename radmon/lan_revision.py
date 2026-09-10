"""Production LAN collector behavior for the deployed ipradmon schema."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


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
    mirrored_alarms: int = 0
    error: str | None = None


@dataclass(slots=True)
class BackfillPullResult:
    source_id: str
    backfill_serid: int | None = None
    inserted_measurements: int = 0
    checkpoint: datetime | None = None
    error: str | None = None


def apply() -> None:
    from . import lan

    def live_rows(self) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, name, location, warnlevel, alarmlevel, unit, audiopath,
       description, maxidlemin, dtom, doserate, dose, lastrate,
       minrate, maxrate, avgrate, lastdose, mindose, maxdose,
       avgdose, lastmea, lastmeasec, meacount, firstmea
FROM vrecent
ORDER BY serid
"""
                )
                rows = cursor.fetchall()
            return self._dict_rows(rows, LIVE_KEYS)
        finally:
            connection.close()

    def alarms_after(self, checkpoint: tuple[datetime, int] | None, limit: int = 500) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                if checkpoint is None:
                    cursor.execute(
                        """
SELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, i_flag, i_op, pic, note
FROM alarm
ORDER BY dtoa ASC, serid ASC
LIMIT ?
""",
                        (max(1, int(limit)),),
                    )
                else:
                    dtoa, serid = checkpoint
                    cursor.execute(
                        """
SELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, i_flag, i_op, pic, note
FROM alarm
WHERE dtoa > ? OR (dtoa = ? AND serid > ?)
ORDER BY dtoa ASC, serid ASC
LIMIT ?
""",
                        (dtoa, dtoa, int(serid), max(1, int(limit))),
                    )
                rows = cursor.fetchall()
            keys = ("serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "i_flag", "i_op", "pic", "note")
            return self._dict_rows(rows, keys)
        finally:
            connection.close()

    def _ensure_alarm_checkpoint_table(self) -> None:
        with self.store._connection() as connection:
            connection.execute(
                """
CREATE TABLE IF NOT EXISTS lan_alarm_checkpoints (
  source_id TEXT PRIMARY KEY,
  last_dtoa TEXT NOT NULL,
  last_serid INTEGER NOT NULL
)
"""
            )

    def load_alarm(self, source_id: str) -> tuple[datetime, int] | None:
        self._ensure_alarm_checkpoint_table()
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT last_dtoa, last_serid FROM lan_alarm_checkpoints WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(str(row[0])), int(row[1])

    def save_alarm(self, source_id: str, dtoa: datetime, serid: int) -> None:
        self._ensure_alarm_checkpoint_table()
        with self.store._connection() as connection:
            connection.execute(
                """
INSERT INTO lan_alarm_checkpoints (source_id, last_dtoa, last_serid)
VALUES (?, ?, ?)
ON CONFLICT(source_id) DO UPDATE SET
  last_dtoa = excluded.last_dtoa,
  last_serid = excluded.last_serid
""",
                (source_id, dtoa.isoformat(), int(serid)),
            )

    def upsert_live_rows(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
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
                    cursor.execute(
                        """
INSERT INTO recent
  (serid, dtom, doserate, dose, lastrate, minrate, maxrate, avgrate,
   lastdose, mindose, maxdose, avgdose, firstmea, lastmea, lastmeasec, meacount)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  dtom = VALUES(dtom), doserate = VALUES(doserate), dose = VALUES(dose),
  lastrate = VALUES(lastrate), minrate = VALUES(minrate), maxrate = VALUES(maxrate),
  avgrate = VALUES(avgrate), lastdose = VALUES(lastdose), mindose = VALUES(mindose),
  maxdose = VALUES(maxdose), avgdose = VALUES(avgdose), firstmea = VALUES(firstmea),
  lastmea = VALUES(lastmea), lastmeasec = VALUES(lastmeasec), meacount = VALUES(meacount)
""",
                        (
                            int(row["serid"]),
                            row.get("dtom"),
                            float(row["doserate"]) if row.get("doserate") is not None else 0.0,
                            row.get("dose"), row.get("lastrate"), row.get("minrate"), row.get("maxrate"),
                            row.get("avgrate"), row.get("lastdose"), row.get("mindose"), row.get("maxdose"),
                            row.get("avgdose"), row.get("firstmea"), row.get("lastmea"), row.get("lastmeasec"),
                            row.get("meacount"),
                        ),
                    )
                    changed += 1
            connection.commit()
            return changed
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
                    cursor.execute(
                        """
INSERT IGNORE INTO measurement (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)
""",
                        (
                            int(row["serid"]), row["dtom"], float(row["doserate"]),
                            row.get("dose"), int(row.get("previnterval") or 0), int(row.get("stat") or 0),
                        ),
                    )
                    if int(getattr(cursor, "rowcount", 0)) == 1:
                        inserted += 1
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mirror_alarm_events(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0
        connection = self._connection()
        changed = 0
        try:
            with connection.cursor() as cursor:
                for row in values:
                    cursor.execute(
                        """
INSERT INTO alarm
  (serid, dtoa, lvl, mvalue, thvalue, nhit, ack, pic, note, i_op, i_flag)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  lvl = VALUES(lvl), mvalue = VALUES(mvalue), thvalue = VALUES(thvalue),
  nhit = VALUES(nhit), ack = VALUES(ack), pic = VALUES(pic), note = VALUES(note),
  i_op = VALUES(i_op), i_flag = VALUES(i_flag)
""",
                        (
                            int(row["serid"]), row["dtoa"], int(row.get("lvl") or 0),
                            float(row.get("mvalue") or 0.0), float(row.get("thvalue") or 0.0),
                            int(row.get("nhit") or 0), int(row.get("ack") or 0), row.get("pic"),
                            row.get("note"), row.get("i_op"), int(row.get("i_flag") or 0),
                        ),
                    )
                    changed += 1
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def run_live_once(self, source):
        result = LivePullResult(source.source_id)
        try:
            remote = self.remote_factory(source)
            raw_live = remote.live_rows()
            mapped_live: list[dict[str, Any]] = []
            for row in raw_live:
                remote_serid = int(row["serid"])
                central_serid = self.checkpoints.store.resolve_station(source.source_id, remote_serid)
                item = dict(row)
                item["_remote_serid"] = remote_serid
                item["serid"] = central_serid
                mapped_live.append(item)
            if hasattr(self.central, "upsert_live_rows"):
                self.central.upsert_live_rows(source.source_id, mapped_live)
            result.live_stations = len(mapped_live)

            alarm_checkpoint = self.checkpoints.load_alarm(source.source_id)
            raw_alarms = remote.alarms_after(alarm_checkpoint, 500)
            historical_seed = alarm_checkpoint is None
            mapped_alarms: list[dict[str, Any]] = []
            for row in raw_alarms:
                item = dict(row)
                remote_serid = int(item["serid"])
                item["_remote_serid"] = remote_serid
                item["serid"] = self.checkpoints.store.resolve_station(source.source_id, remote_serid)
                if historical_seed:
                    item["_historical_seed"] = True
                mapped_alarms.append(item)
            if mapped_alarms and self.alarm_mirror is not None:
                result.mirrored_alarms += int(self.alarm_mirror.mirror(source.source_id, mapped_alarms))
            if mapped_alarms and hasattr(self.central, "mirror_alarm_events"):
                self.central.mirror_alarm_events(source.source_id, mapped_alarms)
            if raw_alarms:
                last_alarm = raw_alarms[-1]
                self.checkpoints.save_alarm(source.source_id, last_alarm["dtoa"], int(last_alarm["serid"]))
        except Exception as exc:
            result.error = str(exc)
        return result

    def run_backfill_once(self, source, station_index: int = 0):
        result = BackfillPullResult(source.source_id)
        try:
            remote = self.remote_factory(source)
            devices = sorted(remote.devices(), key=lambda row: int(row["serid"]))
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
            result.inserted_measurements = int(
                self.central.import_measurements(source.source_id, central_rows)
            )
            last_time = remote_rows[-1].get("dtom")
            if not isinstance(last_time, datetime):
                raise ValueError("remote measurement time tidak valid")
            self.checkpoints.save(source.source_id, remote_serid, last_time)
            result.checkpoint = last_time
        except Exception as exc:
            result.error = str(exc)
        return result

    def run_source_once(self, source):
        """Compatibility helper: one live/alarm poll plus one detector backfill step."""
        result = lan.PullResult(source.source_id)
        live_result = run_live_once(self, source)
        result.mirrored_alarms = live_result.mirrored_alarms
        if live_result.error:
            result.error = live_result.error
            return result
        backfill_result = run_backfill_once(self, source, 0)
        result.inserted_measurements = backfill_result.inserted_measurements
        result.error = backfill_result.error
        return result

    lan.RemoteMariaDBSource.live_rows = live_rows
    lan.RemoteMariaDBSource.alarms_after = alarms_after
    lan.LanCheckpointStore._ensure_alarm_checkpoint_table = _ensure_alarm_checkpoint_table
    lan.LanCheckpointStore.load_alarm = load_alarm
    lan.LanCheckpointStore.save_alarm = save_alarm
    lan.MariaCentralStore.upsert_live_rows = upsert_live_rows
    lan.MariaCentralStore.import_measurements = import_measurements
    lan.MariaCentralStore.mirror_alarm_events = mirror_alarm_events
    lan.LanAggregator.run_live_once = run_live_once
    lan.LanAggregator.run_backfill_once = run_backfill_once
    lan.LanAggregator.run_source_once = run_source_once
