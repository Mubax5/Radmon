from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Any, Iterator
import uuid


SCHEMA = """
CREATE TABLE IF NOT EXISTS alarm_policy_state (
  serid INTEGER PRIMARY KEY,
  window_started_at TEXT,
  trigger_count INTEGER NOT NULL DEFAULT 0 CHECK(trigger_count BETWEEN 0 AND 3),
  retrigger_locked INTEGER NOT NULL DEFAULT 0 CHECK(retrigger_locked IN (0, 1)),
  active_event_id TEXT,
  last_trigger_at TEXT,
  last_normal_at TEXT,
  updated_at TEXT NOT NULL,
  CHECK(retrigger_locked = 0 OR trigger_count = 3)
);
CREATE TABLE IF NOT EXISTS alarm_suppression (
  suppression_id TEXT PRIMARY KEY,
  serid INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  auto_resume_on_normal INTEGER NOT NULL CHECK(auto_resume_on_normal IN (0, 1)),
  pic TEXT NOT NULL,
  reason TEXT NOT NULL,
  started_by TEXT NOT NULL,
  ended_at TEXT,
  ended_reason TEXT,
  first_suppressed_alarm_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alarm_suppression_active_serid
ON alarm_suppression(serid) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS alarm_policy_event (
  event_id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  serid INTEGER NOT NULL,
  source_id TEXT,
  remote_serid INTEGER,
  remote_event_time TEXT,
  origin TEXT NOT NULL,
  kind TEXT NOT NULL,
  trigger_index INTEGER,
  surfaced_at TEXT NOT NULL,
  measured_value REAL,
  threshold REAL,
  status TEXT NOT NULL,
  suppression_id TEXT,
  responded_at TEXT,
  pic TEXT,
  action TEXT,
  reason TEXT,
  notification_sent_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alarm_policy_one_suppressed_per_session
ON alarm_policy_event(suppression_id)
WHERE kind = 'SUPPRESSED' AND suppression_id IS NOT NULL;
"""


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _event_id(event_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"radmon:{event_key}"))


@dataclass(slots=True)
class PolicyState:
    serid: int
    window_started_at: datetime | None = None
    trigger_count: int = 0
    retrigger_locked: bool = False
    active_event_id: str | None = None
    last_trigger_at: datetime | None = None
    last_normal_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class SuppressionRecord:
    suppression_id: str
    serid: int
    started_at: datetime
    expires_at: datetime
    auto_resume_on_normal: bool
    pic: str
    reason: str
    started_by: str
    ended_at: datetime | None = None
    ended_reason: str | None = None
    first_suppressed_alarm_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class PolicyEvent:
    event_id: str
    event_key: str
    serid: int
    source_id: str | None
    remote_serid: int | None
    remote_event_time: datetime | None
    origin: str
    kind: str
    trigger_index: int | None
    surfaced_at: datetime
    measured_value: float | None
    threshold: float | None
    status: str
    suppression_id: str | None
    responded_at: datetime | None
    pic: str | None
    action: str | None
    reason: str | None
    notification_sent_at: datetime | None


class AlarmPolicyStore:
    def __init__(self, security_store) -> None:
        self.security = security_store
        self.ensure_schema()

    @staticmethod
    def _state_from_row(row: tuple[Any, ...] | None, serid: int) -> PolicyState:
        if row is None:
            return PolicyState(int(serid))
        return PolicyState(
            serid=int(row[0]),
            window_started_at=_dt(row[1]),
            trigger_count=int(row[2] or 0),
            retrigger_locked=bool(row[3]),
            active_event_id=row[4],
            last_trigger_at=_dt(row[5]),
            last_normal_at=_dt(row[6]),
            updated_at=_dt(row[7]),
        )

    @staticmethod
    def _suppression_from_row(row: tuple[Any, ...] | None) -> SuppressionRecord | None:
        if row is None:
            return None
        return SuppressionRecord(
            suppression_id=str(row[0]), serid=int(row[1]),
            started_at=_dt(row[2]), expires_at=_dt(row[3]),
            auto_resume_on_normal=bool(row[4]), pic=str(row[5]), reason=str(row[6]),
            started_by=str(row[7]), ended_at=_dt(row[8]), ended_reason=row[9],
            first_suppressed_alarm_at=_dt(row[10]), created_at=_dt(row[11]), updated_at=_dt(row[12]),
        )

    @staticmethod
    def _event_from_row(row: tuple[Any, ...] | None) -> PolicyEvent | None:
        if row is None:
            return None
        return PolicyEvent(
            event_id=str(row[0]), event_key=str(row[1]), serid=int(row[2]), source_id=row[3],
            remote_serid=int(row[4]) if row[4] is not None else None,
            remote_event_time=_dt(row[5]), origin=str(row[6]), kind=str(row[7]),
            trigger_index=int(row[8]) if row[8] is not None else None,
            surfaced_at=_dt(row[9]), measured_value=float(row[10]) if row[10] is not None else None,
            threshold=float(row[11]) if row[11] is not None else None, status=str(row[12]),
            suppression_id=row[13], responded_at=_dt(row[14]), pic=row[15], action=row[16],
            reason=row[17], notification_sent_at=_dt(row[18]),
        )

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def ensure_schema(self) -> None:
        with self.security._connection() as db:
            db.executescript(SCHEMA)
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(remote_alarm_state)")}
            additions = {
                "policy_decision": "TEXT",
                "suppression_id": "TEXT",
                "operator_visible": "INTEGER NOT NULL DEFAULT 0",
                "policy_event_id": "TEXT",
                "source_silence_state": "TEXT",
                "source_silence_retry_at": "TEXT",
            }
            for name, ddl in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE remote_alarm_state ADD COLUMN {name} {ddl}")

    def get_state(self, serid: int) -> PolicyState:
        with self.security._connection() as db:
            row = db.execute(
                "SELECT serid, window_started_at, trigger_count, retrigger_locked, active_event_id, last_trigger_at, last_normal_at, updated_at FROM alarm_policy_state WHERE serid = ?",
                (int(serid),),
            ).fetchone()
        return self._state_from_row(row, int(serid))

    def save_state(self, state: PolicyState, *, connection: sqlite3.Connection | None = None) -> PolicyState:
        own = connection is None
        db = connection or self.security._connection()
        try:
            if own:
                self._begin(db)
            updated = state.updated_at or datetime.now()
            db.execute(
                """
INSERT INTO alarm_policy_state
  (serid, window_started_at, trigger_count, retrigger_locked, active_event_id, last_trigger_at, last_normal_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(serid) DO UPDATE SET
  window_started_at=excluded.window_started_at,
  trigger_count=excluded.trigger_count,
  retrigger_locked=excluded.retrigger_locked,
  active_event_id=excluded.active_event_id,
  last_trigger_at=excluded.last_trigger_at,
  last_normal_at=excluded.last_normal_at,
  updated_at=excluded.updated_at
""",
                (int(state.serid), _iso(state.window_started_at), int(state.trigger_count), 1 if state.retrigger_locked else 0,
                 state.active_event_id, _iso(state.last_trigger_at), _iso(state.last_normal_at), _iso(updated)),
            )
            state.updated_at = updated
            if own:
                db.commit()
            return state
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()

    def active_suppression(self, serid: int) -> SuppressionRecord | None:
        with self.security._connection() as db:
            row = db.execute(
                """
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression WHERE serid = ? AND ended_at IS NULL
ORDER BY started_at DESC LIMIT 1
""", (int(serid),),
            ).fetchone()
        return self._suppression_from_row(row)

    def start_suppression(self, serid, started_at, expires_at, auto_resume_on_normal, pic, reason, started_by, *, connection=None):
        suppression_id = str(uuid.uuid4())
        own = connection is None
        db = connection or self.security._connection()
        row = None
        try:
            if own:
                self._begin(db)
            db.execute('\nINSERT INTO alarm_suppression\n  (suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,\n   started_by, created_at, updated_at)\nVALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n', (suppression_id, int(serid), _iso(started_at), _iso(expires_at), 1 if auto_resume_on_normal else 0, str(pic), str(reason), str(started_by), _iso(started_at), _iso(started_at)))
            row = db.execute('\nSELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,\n       started_by, ended_at, ended_reason, first_suppressed_alarm_at, created_at, updated_at\nFROM alarm_suppression WHERE suppression_id = ?\n', (suppression_id,)).fetchone()
            if own:
                db.commit()
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()
        item = self._suppression_from_row(row)
        if item is None:
            raise RuntimeError('suppression gagal dibuat')
        return item

    def get_suppression(self, suppression_id: str) -> SuppressionRecord | None:
        with self.security._connection() as db:
            row = db.execute(
                """
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression WHERE suppression_id = ?
""", (str(suppression_id),),
            ).fetchone()
        return self._suppression_from_row(row)

    def list_suppressions(self, *, active_only: bool = False, limit: int = 500) -> list[SuppressionRecord]:
        clause = "WHERE ended_at IS NULL" if active_only else ""
        with self.security._connection() as db:
            rows = db.execute(
                f"""
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression {clause}
ORDER BY started_at DESC LIMIT ?
""", (max(1, int(limit)),),
            ).fetchall()
        return [item for row in rows if (item := self._suppression_from_row(row)) is not None]

    def end_suppression(self, suppression_id: str, ended_at: datetime, ended_reason: str,
                        *, connection: sqlite3.Connection | None = None) -> SuppressionRecord | None:
        own = connection is None
        db = connection or self.security._connection()
        try:
            if own:
                self._begin(db)
            db.execute(
                "UPDATE alarm_suppression SET ended_at=?, ended_reason=?, updated_at=? WHERE suppression_id=? AND ended_at IS NULL",
                (_iso(ended_at), str(ended_reason), _iso(ended_at), str(suppression_id)),
            )
            if own:
                db.commit()
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()
        return self.get_suppression(suppression_id)

    def mark_first_suppressed_alarm(self, suppression_id: str, at: datetime,
                                    *, connection: sqlite3.Connection | None = None) -> None:
        own = connection is None
        db = connection or self.security._connection()
        try:
            if own:
                self._begin(db)
            db.execute(
                """UPDATE alarm_suppression
                   SET first_suppressed_alarm_at=COALESCE(first_suppressed_alarm_at, ?), updated_at=?
                   WHERE suppression_id=?""",
                (_iso(at), _iso(at), str(suppression_id)),
            )
            if own:
                db.commit()
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()

    def create_policy_event(self, *, event_key: str, serid: int, kind: str, origin: str,
                            surfaced_at: datetime, measured_value: float | None = None,
                            threshold: float | None = None, status: str = "ACTIVE",
                            suppression_id: str | None = None, source_id: str | None = None,
                            remote_serid: int | None = None, remote_event_time: datetime | None = None,
                            trigger_index: int | None = None,
                            connection: sqlite3.Connection | None = None) -> PolicyEvent:
        event_id = _event_id(str(event_key))
        own = connection is None
        db = connection or self.security._connection()
        try:
            if own:
                self._begin(db)
            db.execute(
                """
INSERT INTO alarm_policy_event
  (event_id, event_key, serid, source_id, remote_serid, remote_event_time, origin, kind,
   trigger_index, surfaced_at, measured_value, threshold, status, suppression_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(event_key) DO NOTHING
""",
                (event_id, str(event_key), int(serid), source_id,
                 int(remote_serid) if remote_serid is not None else None, _iso(remote_event_time),
                 str(origin), str(kind), int(trigger_index) if trigger_index is not None else None,
                 _iso(surfaced_at), measured_value, threshold, str(status), suppression_id),
            )
            row = db.execute(
                """SELECT event_id, event_key, serid, source_id, remote_serid, remote_event_time,
                          origin, kind, trigger_index, surfaced_at, measured_value, threshold, status,
                          suppression_id, responded_at, pic, action, reason, notification_sent_at
                   FROM alarm_policy_event WHERE event_key=?""",
                (str(event_key),),
            ).fetchone()
            if own:
                db.commit()
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()
        item = self._event_from_row(row)
        if item is None:
            raise RuntimeError("policy event gagal dibuat")
        return item

    def get_event(self, event_id: str) -> PolicyEvent | None:
        with self.security._connection() as db:
            row = db.execute(
                """SELECT event_id, event_key, serid, source_id, remote_serid, remote_event_time,
                          origin, kind, trigger_index, surfaced_at, measured_value, threshold, status,
                          suppression_id, responded_at, pic, action, reason, notification_sent_at
                   FROM alarm_policy_event WHERE event_id=?""", (str(event_id),),
            ).fetchone()
        return self._event_from_row(row)

    def list_policy_events(self, *, serid: int | None = None, active_only: bool = False,
                           notify_pending_only: bool = False, limit: int = 500) -> list[PolicyEvent]:
        where: list[str] = []
        params: list[Any] = []
        if serid is not None:
            where.append("serid=?")
            params.append(int(serid))
        if active_only:
            where.append("status='ACTIVE'")
        if notify_pending_only:
            where.extend(["kind='ALARM'", "status='ACTIVE'", "notification_sent_at IS NULL"])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, int(limit)))
        with self.security._connection() as db:
            rows = db.execute(
                f"""SELECT event_id, event_key, serid, source_id, remote_serid, remote_event_time,
                           origin, kind, trigger_index, surfaced_at, measured_value, threshold, status,
                           suppression_id, responded_at, pic, action, reason, notification_sent_at
                    FROM alarm_policy_event {clause}
                    ORDER BY surfaced_at DESC LIMIT ?""", tuple(params),
            ).fetchall()
        return [item for row in rows if (item := self._event_from_row(row)) is not None]

    def respond_event(self, event_id: str, responded_at: datetime, pic: str, action: str, reason: str,
                      *, connection: sqlite3.Connection | None = None) -> PolicyEvent:
        own = connection is None
        db = connection or self.security._connection()
        try:
            if own:
                self._begin(db)
            cursor = db.execute(
                """UPDATE alarm_policy_event
                   SET status='RESPONDED', responded_at=?, pic=?, action=?, reason=?
                   WHERE event_id=? AND status='ACTIVE'""",
                (_iso(responded_at), str(pic), str(action), str(reason), str(event_id)),
            )
            if cursor.rowcount not in (0, 1):
                raise RuntimeError("policy event response tidak deterministik")
            if own:
                db.commit()
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()
        item = self.get_event(event_id)
        if item is None:
            raise RuntimeError("policy event tidak ditemukan")
        return item

    def mark_notification_sent(self, event_id: str, at: datetime) -> None:
        with self.security._connection() as db:
            db.execute(
                "UPDATE alarm_policy_event SET notification_sent_at=? WHERE event_id=? AND notification_sent_at IS NULL",
                (_iso(at), str(event_id)),
            )

    def annotate_raw_alarm(self, source_id: str, serid: int, event_time: datetime, *,
                           policy_decision: str, suppression_id: str | None = None,
                           operator_visible: bool = False, policy_event_id: str | None = None,
                           source_silence_state: str | None = None,
                           source_silence_retry_at: datetime | None = None) -> None:
        with self.security._connection() as db:
            db.execute(
                """UPDATE remote_alarm_state
                   SET policy_decision=?, suppression_id=?, operator_visible=?, policy_event_id=?,
                       source_silence_state=COALESCE(?, source_silence_state),
                       source_silence_retry_at=COALESCE(?, source_silence_retry_at)
                   WHERE source_id=? AND serid=? AND event_time=?""",
                (policy_decision, suppression_id, 1 if operator_visible else 0, policy_event_id,
                 source_silence_state, _iso(source_silence_retry_at), source_id, int(serid), _iso(event_time)),
            )

    def pending_source_silences(self, source_id: str | None = None, *, at: datetime | None = None,
                                limit: int = 25) -> list[dict[str, Any]]:
        where = ["source_silence_state IN ('PENDING','FAILED')"]
        params: list[Any] = []
        if source_id is not None:
            where.append("source_id=?")
            params.append(str(source_id))
        if at is not None:
            where.append("(source_silence_retry_at IS NULL OR source_silence_retry_at<=?)")
            params.append(_iso(at))
        params.append(max(1, int(limit)))
        with self.security._connection() as db:
            rows = db.execute(
                f"""SELECT source_id, serid, remote_serid, event_time, policy_event_id,
                           suppression_id, source_silence_state, source_silence_retry_at
                    FROM remote_alarm_state WHERE {' AND '.join(where)}
                    ORDER BY event_time ASC LIMIT ?""", tuple(params),
            ).fetchall()
        return [
            {"source_id": r[0], "serid": int(r[1]), "remote_serid": int(r[2]) if r[2] is not None else None,
             "event_time": _dt(r[3]), "policy_event_id": r[4], "suppression_id": r[5],
             "source_silence_state": r[6], "source_silence_retry_at": _dt(r[7])}
            for r in rows
        ]

    def mark_source_silence_result(self, source_id: str, serid: int, event_time: datetime, *,
                                   state: str, retry_at: datetime | None = None) -> None:
        with self.security._connection() as db:
            db.execute(
                """UPDATE remote_alarm_state SET source_silence_state=?, source_silence_retry_at=?
                   WHERE source_id=? AND serid=? AND event_time=?""",
                (str(state), _iso(retry_at), str(source_id), int(serid), _iso(event_time)),
            )

    @contextmanager
    def detector_transaction(self, serid: int) -> Iterator["_DetectorTransaction"]:
        db = self.security._connection()
        try:
            self._begin(db)
            tx = _DetectorTransaction(self, db, int(serid))
            yield tx
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


class _DetectorTransaction:
    def __init__(self, store: AlarmPolicyStore, connection: sqlite3.Connection, serid: int) -> None:
        self.store = store
        self.connection = connection
        self.serid = int(serid)
        row = connection.execute(
            "SELECT serid, window_started_at, trigger_count, retrigger_locked, active_event_id, last_trigger_at, last_normal_at, updated_at FROM alarm_policy_state WHERE serid=?",
            (self.serid,),
        ).fetchone()
        self.state = store._state_from_row(row, self.serid)
        row = connection.execute(
            """SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
                      started_by, ended_at, ended_reason, first_suppressed_alarm_at, created_at, updated_at
               FROM alarm_suppression WHERE serid=? AND ended_at IS NULL
               ORDER BY started_at DESC LIMIT 1""", (self.serid,),
        ).fetchone()
        self.active_suppression = store._suppression_from_row(row)

    def save_state(self, state: PolicyState | None = None, *, at: datetime | None = None) -> PolicyState:
        target = state or self.state
        target.updated_at = at or target.updated_at or datetime.now()
        self.store.save_state(target, connection=self.connection)
        self.state = target
        return target

    def reset_policy(self, at: datetime) -> PolicyState:
        self.state.window_started_at = None
        self.state.trigger_count = 0
        self.state.retrigger_locked = False
        self.state.active_event_id = None
        self.state.last_trigger_at = None
        self.state.last_normal_at = at
        return self.save_state(at=at)

    def create_alarm_event(self, *, event_key: str, trigger_index: int, surfaced_at: datetime,
                           measured_value: float | None, threshold: float | None,
                           source_id: str | None = None) -> PolicyEvent:
        return self.store.create_policy_event(
            event_key=event_key, serid=self.serid, kind="ALARM", origin="central_policy",
            surfaced_at=surfaced_at, measured_value=measured_value, threshold=threshold,
            status="ACTIVE", trigger_index=trigger_index, source_id=source_id,
            connection=self.connection,
        )

    def create_suppressed_event(self, suppression: SuppressionRecord, *, surfaced_at: datetime,
                                measured_value: float | None, threshold: float | None,
                                source_id: str | None = None) -> PolicyEvent:
        event = self.store.create_policy_event(
            event_key=f"suppressed:{suppression.suppression_id}", serid=self.serid,
            kind="SUPPRESSED", origin="central_policy", surfaced_at=surfaced_at,
            measured_value=measured_value, threshold=threshold, status="AUTO_SILENCED",
            suppression_id=suppression.suppression_id, source_id=source_id,
            connection=self.connection,
        )
        self.connection.execute(
            """UPDATE alarm_suppression
               SET first_suppressed_alarm_at=COALESCE(first_suppressed_alarm_at, ?), updated_at=?
               WHERE suppression_id=?""",
            (_iso(surfaced_at), _iso(surfaced_at), suppression.suppression_id),
        )
        return event

    def end_suppression(self, suppression_id: str, at: datetime, reason: str) -> None:
        self.connection.execute(
            "UPDATE alarm_suppression SET ended_at=?, ended_reason=?, updated_at=? WHERE suppression_id=? AND ended_at IS NULL",
            (_iso(at), str(reason), _iso(at), str(suppression_id)),
        )
        self.active_suppression = None

    def respond_event(self, event_id: str, at: datetime, pic: str, action: str, reason: str) -> PolicyEvent:
        self.connection.execute(
            """UPDATE alarm_policy_event SET status='RESPONDED', responded_at=?, pic=?, action=?, reason=?
               WHERE event_id=? AND status='ACTIVE'""",
            (_iso(at), str(pic), str(action), str(reason), str(event_id)),
        )
        row = self.connection.execute(
            """SELECT event_id, event_key, serid, source_id, remote_serid, remote_event_time,
                      origin, kind, trigger_index, surfaced_at, measured_value, threshold, status,
                      suppression_id, responded_at, pic, action, reason, notification_sent_at
               FROM alarm_policy_event WHERE event_id=?""", (str(event_id),),
        ).fetchone()
        item = self.store._event_from_row(row)
        if item is None:
            raise RuntimeError("policy event tidak ditemukan")
        return item
