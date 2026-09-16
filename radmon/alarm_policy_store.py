from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3
import threading
from typing import Any, Callable, Iterator
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
  ended_by TEXT,
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


_SOURCE_SILENCE_LOCK_GUARD = threading.Lock()
_SOURCE_SILENCE_LOCKS: dict[tuple[str, int, str], threading.RLock] = {}
_ALARM_POLICY_SCHEMA_MIGRATION_LOCK = threading.Lock()


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
    ended_by: str | None = None
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
            started_by=str(row[7]), ended_at=_dt(row[8]), ended_reason=row[9], ended_by=row[10],
            first_suppressed_alarm_at=_dt(row[11]), created_at=_dt(row[12]), updated_at=_dt(row[13]),
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
        # DDL must be serialized both in-process and across independently
        # started processes so an additive ALTER cannot race another startup.
        with _ALARM_POLICY_SCHEMA_MIGRATION_LOCK:
            db = self.security._connection()
            try:
                self._begin(db)
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        db.execute(statement)
                suppression_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(alarm_suppression)")}
                if "ended_by" not in suppression_columns:
                    db.execute("ALTER TABLE alarm_suppression ADD COLUMN ended_by TEXT")
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

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
       started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at
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
            row = db.execute('\nSELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,\n       started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at\nFROM alarm_suppression WHERE suppression_id = ?\n', (suppression_id,)).fetchone()
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

    def get_suppression(self, suppression_id: str, *, connection: sqlite3.Connection | None = None) -> SuppressionRecord | None:
        own = connection is None
        db = connection or self.security._connection()
        try:
            row = db.execute(
                """
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression WHERE suppression_id = ?
""", (str(suppression_id),),
            ).fetchone()
        finally:
            if own:
                db.close()
        return self._suppression_from_row(row)

    def list_suppressions(self, *, active_only: bool = False, limit: int = 500) -> list[SuppressionRecord]:
        clause = "WHERE ended_at IS NULL" if active_only else ""
        with self.security._connection() as db:
            rows = db.execute(
                f"""
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression {clause}
ORDER BY started_at DESC LIMIT ?
""", (max(1, int(limit)),),
            ).fetchall()
        return [item for row in rows if (item := self._suppression_from_row(row)) is not None]

    def due_suppressions(self, at: datetime, *, limit: int = 500) -> list[SuppressionRecord]:
        with self.security._connection() as db:
            rows = db.execute(
                """
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression WHERE ended_at IS NULL AND expires_at <= ?
ORDER BY expires_at ASC LIMIT ?
""", (_iso(at), max(1, int(limit))),
            ).fetchall()
        return [item for row in rows if (item := self._suppression_from_row(row)) is not None]

    def end_suppression(self, suppression_id: str, ended_at: datetime, ended_reason: str,
                        *, ended_by: str | None = None, cancel_source_silences: bool = False,
                        connection: sqlite3.Connection | None = None) -> tuple[SuppressionRecord | None, bool]:
        own = connection is None
        db = connection or self.security._connection()
        result = None
        try:
            if own:
                self._begin(db)
            cursor = db.execute(
                "UPDATE alarm_suppression SET ended_at=?, ended_reason=?, ended_by=?, updated_at=? WHERE suppression_id=? AND ended_at IS NULL",
                (_iso(ended_at), str(ended_reason), ended_by, _iso(ended_at), str(suppression_id)),
            )
            changed = cursor.rowcount == 1
            if changed:
                if cancel_source_silences:
                    db.execute(
                        """UPDATE remote_alarm_state
                           SET source_silence_state=CASE
                                 WHEN source_silence_state='DISPATCHING'
                                      AND source_silence_dispatch_started_at IS NOT NULL THEN 'UNCERTAIN'
                                 ELSE 'CANCELLED'
                               END,
                               source_silence_retry_at=NULL,
                               source_silence_claimed_at=CASE
                                 WHEN source_silence_state='DISPATCHING'
                                      AND source_silence_dispatch_started_at IS NULL THEN source_silence_claimed_at
                                 ELSE NULL
                               END
                           WHERE suppression_id=?
                             AND source_silence_state IN ('PENDING', 'FAILED', 'DISPATCHING')""",
                        (str(suppression_id),),
                    )
                row = db.execute("SELECT serid FROM alarm_suppression WHERE suppression_id=?", (str(suppression_id),)).fetchone()
                if row is not None:
                    self.create_policy_event(
                        event_key=f"suppression-end:{suppression_id}", serid=int(row[0]),
                        kind="SUPPRESSION_END", origin="central_policy", surfaced_at=ended_at,
                        status="ENDED", suppression_id=str(suppression_id), pic=ended_by,
                        action=str(ended_reason).split(":", 1)[0], reason=str(ended_reason), connection=db,
                    )
            if own:
                db.commit()
            row = db.execute(
                """SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
                          started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at
                   FROM alarm_suppression WHERE suppression_id=?""",
                (str(suppression_id),),
            ).fetchone()
            result = self._suppression_from_row(row)
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()
        return result, changed

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
                            trigger_index: int | None = None, pic: str | None = None,
                            action: str | None = None, reason: str | None = None,
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
    trigger_index, surfaced_at, measured_value, threshold, status, suppression_id, pic, action, reason)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(event_key) DO NOTHING
""",
                (event_id, str(event_key), int(serid), source_id,
                 int(remote_serid) if remote_serid is not None else None, _iso(remote_event_time),
                 str(origin), str(kind), int(trigger_index) if trigger_index is not None else None,
                  _iso(surfaced_at), measured_value, threshold, str(status), suppression_id, pic, action, reason),
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

    @staticmethod
    def _source_silence_key(source_id: str, serid: int, event_time: datetime) -> tuple[str, int, str]:
        return str(source_id), int(serid), _iso(event_time) or ""

    @contextmanager
    def source_silence_lock(self, source_id: str, serid: int, event_time: datetime):
        key = self._source_silence_key(source_id, serid, event_time)
        with _SOURCE_SILENCE_LOCK_GUARD:
            lock = _SOURCE_SILENCE_LOCKS.setdefault(key, threading.RLock())
        with lock:
            yield

    @contextmanager
    def suppression_source_silence_locks(self, suppression_id: str):
        with self.security._connection() as db:
            rows = db.execute(
                """SELECT source_id, serid, event_time FROM remote_alarm_state
                   WHERE suppression_id=? AND source_silence_state IN ('PENDING', 'FAILED', 'DISPATCHING')
                   ORDER BY source_id, serid, event_time""",
                (str(suppression_id),),
            ).fetchall()
        with ExitStack() as locks:
            for source_id, serid, event_time in rows:
                locks.enter_context(self.source_silence_lock(str(source_id), int(serid), _dt(event_time)))
            yield

    def claim_source_silence(self, source_id: str, serid: int, event_time: datetime, *, claimed_at: datetime) -> int | None:
        with self.security._connection() as db:
            self._begin(db)
            try:
                row = db.execute(
                    """SELECT raw.source_silence_attempts, raw.source_observation_version
                       FROM remote_alarm_state AS raw
                       LEFT JOIN alarm_suppression AS suppression ON suppression.suppression_id=raw.suppression_id
                       WHERE raw.source_id=? AND raw.serid=? AND raw.event_time=?
                         AND raw.source_silence_state IN ('PENDING', 'FAILED')
                         AND (raw.suppression_id IS NULL OR suppression.ended_at IS NULL)""",
                    (str(source_id), int(serid), _iso(event_time)),
                ).fetchone()
                if row is None:
                    # A source row can arrive after cancellation. Never turn
                    # that late observation into a post-cancel remote write.
                    db.execute(
                        """UPDATE remote_alarm_state AS raw
                           SET source_silence_state='CANCELLED', source_silence_retry_at=NULL
                           WHERE raw.source_id=? AND raw.serid=? AND raw.event_time=?
                             AND raw.source_silence_state IN ('PENDING', 'FAILED')
                             AND raw.suppression_id IS NOT NULL
                             AND NOT EXISTS (
                                 SELECT 1 FROM alarm_suppression AS suppression
                                 WHERE suppression.suppression_id=raw.suppression_id AND suppression.ended_at IS NULL
                             )""",
                        (str(source_id), int(serid), _iso(event_time)),
                    )
                    db.commit()
                    return None
                attempts = int(row[0] or 0) + 1
                observation = int(row[1] or 0)
                cursor = db.execute(
                    """UPDATE remote_alarm_state
                       SET source_silence_state='DISPATCHING', source_silence_retry_at=NULL,
                            source_silence_claimed_at=?, source_silence_attempts=?,
                            source_silence_claim_observation=?
                        WHERE source_id=? AND serid=? AND event_time=?
                          AND source_silence_state IN ('PENDING', 'FAILED')
                          AND (suppression_id IS NULL OR EXISTS (
                              SELECT 1 FROM alarm_suppression AS suppression
                              WHERE suppression.suppression_id=remote_alarm_state.suppression_id
                                AND suppression.ended_at IS NULL
                          ))""",
                    (_iso(claimed_at), attempts, observation, str(source_id), int(serid), _iso(event_time)),
                )
                if cursor.rowcount != 1:
                    db.rollback()
                    return None
                db.commit()
                return attempts
            except Exception:
                db.rollback()
                raise

    def claim_source_response(self, source_id: str, serid: int, event_time: datetime, *, claimed_at: datetime) -> int | None:
        with self.security._connection() as db:
            self._begin(db)
            try:
                row = db.execute(
                    """SELECT source_response_attempts, source_observation_version FROM remote_alarm_state
                       WHERE source_id=? AND serid=? AND event_time=? AND is_active=1
                         AND (source_response_state IS NULL OR source_response_state='FAILED')""",
                    (str(source_id), int(serid), _iso(event_time)),
                ).fetchone()
                if row is None:
                    db.rollback()
                    return None
                attempts = int(row[0] or 0) + 1
                observation = int(row[1] or 0)
                cursor = db.execute(
                    """UPDATE remote_alarm_state
                        SET source_response_state='DISPATCHING', source_response_claimed_at=?,
                            source_response_attempts=?, source_response_claim_observation=?
                       WHERE source_id=? AND serid=? AND event_time=? AND is_active=1
                         AND (source_response_state IS NULL OR source_response_state='FAILED')""",
                    (_iso(claimed_at), attempts, observation, str(source_id), int(serid), _iso(event_time)),
                )
                if cursor.rowcount != 1:
                    db.rollback()
                    return None
                db.commit()
                return attempts
            except Exception:
                db.rollback()
                raise

    def finish_claimed_source_response(self, source_id: str, serid: int, event_time: datetime, *, state: str) -> bool:
        if state not in {'CONFIRMED', 'FAILED'}:
            raise ValueError('hasil source response tidak valid')
        with self.security._connection() as db:
            self._begin(db)
            try:
                cursor = db.execute(
                    """UPDATE remote_alarm_state
                       SET source_response_state=?, source_response_claimed_at=NULL
                       WHERE source_id=? AND serid=? AND event_time=? AND source_response_state='DISPATCHING'""",
                    (state, str(source_id), int(serid), _iso(event_time)),
                )
                db.commit()
                return cursor.rowcount == 1
            except Exception:
                db.rollback()
                raise

    def finish_claimed_source_silence(self, source_id: str, serid: int, event_time: datetime, *,
                                      state: str, retry_at: datetime | None = None) -> bool:
        if state not in {'CONFIRMED', 'FAILED'}:
            raise ValueError('hasil source silence tidak valid')
        with self.security._connection() as db:
            self._begin(db)
            try:
                row = db.execute(
                    """SELECT suppression.ended_at
                       FROM remote_alarm_state AS raw
                       LEFT JOIN alarm_suppression AS suppression ON suppression.suppression_id=raw.suppression_id
                       WHERE raw.source_id=? AND raw.serid=? AND raw.event_time=?
                         AND raw.source_silence_state='DISPATCHING'""",
                    (str(source_id), int(serid), _iso(event_time)),
                ).fetchone()
                if row is None:
                    db.rollback()
                    return False
                final_state = 'CANCELLED' if state == 'FAILED' and row[0] is not None else state
                cursor = db.execute(
                    """UPDATE remote_alarm_state
                        SET source_silence_state=?, source_silence_retry_at=?, source_silence_claimed_at=NULL,
                            source_silence_claim_observation=NULL
                       WHERE source_id=? AND serid=? AND event_time=? AND source_silence_state='DISPATCHING'""",
                    (final_state, _iso(retry_at) if final_state == 'FAILED' else None,
                     str(source_id), int(serid), _iso(event_time)),
                )
                db.commit()
                return cursor.rowcount == 1
            except Exception:
                db.rollback()
                raise

    def begin_claimed_source_silence_dispatch(self, source_id: str, serid: int, event_time: datetime, *,
                                              started_at: datetime) -> bool:
        """Record the irreversible external-call boundary while the suppression is active."""
        with self.security._connection() as db:
            self._begin(db)
            try:
                cursor = db.execute(
                    """UPDATE remote_alarm_state
                       SET source_silence_dispatch_started_at=?
                       WHERE source_id=? AND serid=? AND event_time=?
                         AND source_silence_state='DISPATCHING'
                         AND (suppression_id IS NULL OR EXISTS (
                             SELECT 1 FROM alarm_suppression AS suppression
                             WHERE suppression.suppression_id=remote_alarm_state.suppression_id
                               AND suppression.ended_at IS NULL
                               AND suppression.expires_at > ?
                          ))""",
                    (_iso(started_at), str(source_id), int(serid), _iso(event_time), _iso(started_at)),
                )
                if cursor.rowcount != 1:
                    # A claim can race expiry before the remote call begins.
                    # It is safe to cancel that unstarted logical dispatch.
                    db.execute(
                        """UPDATE remote_alarm_state
                           SET source_silence_state='CANCELLED', source_silence_retry_at=NULL,
                               source_silence_claimed_at=NULL
                           WHERE source_id=? AND serid=? AND event_time=?
                             AND source_silence_state='DISPATCHING'
                             AND suppression_id IS NOT NULL
                             AND NOT EXISTS (
                                 SELECT 1 FROM alarm_suppression AS suppression
                                 WHERE suppression.suppression_id=remote_alarm_state.suppression_id
                                   AND suppression.ended_at IS NULL
                                   AND suppression.expires_at > ?
                             )""",
                        (str(source_id), int(serid), _iso(event_time), _iso(started_at)),
                    )
                db.commit()
                return cursor.rowcount == 1
            except Exception:
                db.rollback()
                raise

    def source_silence_state(self, source_id: str, serid: int, event_time: datetime) -> str | None:
        with self.security._connection() as db:
            row = db.execute(
                "SELECT source_silence_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
                (str(source_id), int(serid), _iso(event_time)),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def mark_source_silence_result(self, source_id: str, serid: int, event_time: datetime, *,
                                    state: str, retry_at: datetime | None = None) -> None:
        with self.security._connection() as db:
            db.execute(
                """UPDATE remote_alarm_state SET source_silence_state=?, source_silence_retry_at=?
                   WHERE source_id=? AND serid=? AND event_time=?
                     AND COALESCE(source_silence_state, '') != 'CANCELLED'""",
                (str(state), _iso(retry_at), str(source_id), int(serid), _iso(event_time)),
            )

    def recover_stale_source_silences(self, source_id: str | None, *, at: datetime,
                                      claim_timeout: timedelta = timedelta(seconds=60)) -> list[dict[str, Any]]:
        cutoff = at - claim_timeout
        with self.security._connection() as db:
            self._begin(db)
            try:
                source_clause = "AND source_id=?" if source_id is not None else ""
                params: tuple[Any, ...] = (_iso(cutoff), str(source_id)) if source_id is not None else (_iso(cutoff),)
                rows = db.execute(
                    f"""SELECT source_id, serid, event_time FROM remote_alarm_state
                       WHERE source_silence_state='DISPATCHING'
                         AND source_silence_claimed_at IS NOT NULL
                         AND source_silence_claimed_at<=? {source_clause}""",
                    params,
                ).fetchall()
                for row_source_id, serid, event_time in rows:
                    db.execute(
                        """UPDATE remote_alarm_state SET source_silence_state='RECONCILING',
                                   source_silence_retry_at=NULL
                           WHERE source_id=? AND serid=? AND event_time=?
                             AND source_silence_state='DISPATCHING'""",
                        (str(row_source_id), int(serid), str(event_time)),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return [{"source_id": str(row_source_id), "serid": int(serid), "event_time": _dt(event_time)} for row_source_id, serid, event_time in rows]

    def recover_stale_source_responses(self, source_id: str | None, *, at: datetime,
                                       claim_timeout: timedelta = timedelta(seconds=60)) -> list[dict[str, Any]]:
        cutoff = at - claim_timeout
        with self.security._connection() as db:
            self._begin(db)
            try:
                source_clause = "AND source_id=?" if source_id is not None else ""
                params: tuple[Any, ...] = (_iso(cutoff), str(source_id)) if source_id is not None else (_iso(cutoff),)
                rows = db.execute(
                    f"""SELECT source_id, serid, event_time FROM remote_alarm_state
                        WHERE source_response_state='DISPATCHING'
                          AND source_response_claimed_at IS NOT NULL
                          AND source_response_claimed_at<=? {source_clause}""",
                    params,
                ).fetchall()
                for row_source_id, serid, event_time in rows:
                    db.execute(
                        """UPDATE remote_alarm_state SET source_response_state='RECONCILING'
                           WHERE source_id=? AND serid=? AND event_time=?
                             AND source_response_state='DISPATCHING'""",
                        (str(row_source_id), int(serid), str(event_time)),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return [{"source_id": str(row_source_id), "serid": int(serid), "event_time": _dt(event_time)} for row_source_id, serid, event_time in rows]

    def drain_cancelled_source_silence_claims(self, source_id: str, *, at: datetime,
                                              claim_timeout: timedelta = timedelta(seconds=60)) -> list[dict[str, Any]]:
        """Audit an end that won the race before a claimed call could start."""
        cutoff = at - claim_timeout
        with self.security._connection() as db:
            self._begin(db)
            try:
                rows = db.execute(
                    """SELECT serid, event_time FROM remote_alarm_state
                       WHERE source_id=? AND source_silence_state='CANCELLED'
                         AND source_silence_claimed_at IS NOT NULL
                         AND source_silence_claimed_at<=?""",
                    (str(source_id), _iso(cutoff)),
                ).fetchall()
                for serid, event_time in rows:
                    db.execute(
                        """UPDATE remote_alarm_state SET source_silence_claimed_at=NULL
                           WHERE source_id=? AND serid=? AND event_time=?
                             AND source_silence_state='CANCELLED'""",
                        (str(source_id), int(serid), str(event_time)),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return [{"source_id": str(source_id), "serid": int(serid), "event_time": _dt(event_time)} for serid, event_time in rows]

    def reconcile_source_silences(self, source_id: str, *, at: datetime) -> list[dict[str, Any]]:
        """Resolve a stale claim only after the source has been observed again."""
        with self.security._connection() as db:
            self._begin(db)
            try:
                rows = db.execute(
                    """SELECT raw.serid, raw.event_time, raw.is_active, suppression.ended_at
                       FROM remote_alarm_state AS raw
                       LEFT JOIN alarm_suppression AS suppression ON suppression.suppression_id=raw.suppression_id
                       WHERE raw.source_id=? AND raw.source_silence_state='RECONCILING'
                         AND raw.source_observation_version > COALESCE(raw.source_silence_claim_observation, -1)""",
                    (str(source_id),),
                ).fetchall()
                result = []
                for serid, event_time, is_active, ended_at in rows:
                    state = "CANCELLED" if ended_at is not None else ("PENDING" if bool(is_active) else "RECONCILED")
                    db.execute(
                        """UPDATE remote_alarm_state
                           SET source_silence_state=?, source_silence_retry_at=?,
                               source_silence_claimed_at=NULL, source_silence_claim_observation=NULL
                           WHERE source_id=? AND serid=? AND event_time=?
                             AND source_silence_state='RECONCILING'""",
                        (state, _iso(at) if state == "PENDING" else None,
                         str(source_id), int(serid), str(event_time)),
                    )
                    result.append({"source_id": str(source_id), "serid": int(serid), "event_time": _dt(event_time), "state": state})
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    def reconcile_source_responses(self, source_id: str, *, at: datetime) -> list[dict[str, Any]]:
        """Resolve an ambiguous normal response only after a fresh source observation."""
        with self.security._connection() as db:
            self._begin(db)
            try:
                rows = db.execute(
                    """SELECT serid, event_time, is_active FROM remote_alarm_state
                       WHERE source_id=? AND source_response_state='RECONCILING'
                         AND source_observation_version > COALESCE(source_response_claim_observation, -1)""",
                    (str(source_id),),
                ).fetchall()
                result = []
                for serid, event_time, is_active in rows:
                    # An inactive source row proves no retry is appropriate, but
                    # not which actor made the non-atomic MariaDB write.
                    state = "FAILED" if bool(is_active) else "RECONCILED"
                    db.execute(
                        """UPDATE remote_alarm_state
                           SET source_response_state=?, source_response_claimed_at=NULL,
                               source_response_claim_observation=NULL
                           WHERE source_id=? AND serid=? AND event_time=?
                             AND source_response_state='RECONCILING'""",
                        (state, str(source_id), int(serid), str(event_time)),
                    )
                    result.append({"source_id": str(source_id), "serid": int(serid), "event_time": _dt(event_time), "state": state})
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    def dispatch_source_silence(self, source_id: str, serid: int, event_time: datetime, *, at: datetime,
                                responder: Callable[[], bool], backoff_seconds: tuple[int, ...]) -> tuple[str, Exception | None]:
        """Run the durable claim/call/finalize protocol for every source write."""
        with self.source_silence_lock(source_id, serid, event_time):
            attempts = self.claim_source_silence(source_id, serid, event_time, claimed_at=at)
            if attempts is None:
                return "SKIPPED", None
            if not self.begin_claimed_source_silence_dispatch(source_id, serid, event_time, started_at=at):
                return "CANCELLED", None
        # The durable start marker lets expiry/cancel end immediately. If the
        # external call has started, its outcome is intentionally uncertain.
        # MariaDB and this SQLite transaction cannot be committed atomically.
        try:
            if not responder():
                raise RuntimeError("source menolak alarm silence")
            confirmed = self.finish_claimed_source_silence(
                source_id, serid, event_time, state="CONFIRMED",
            )
            if confirmed:
                return "CONFIRMED", None
            return self.source_silence_state(source_id, serid, event_time) or "CANCELLED", None
        except Exception as exc:
            delay = backoff_seconds[min(attempts - 1, len(backoff_seconds) - 1)]
            failed = self.finish_claimed_source_silence(
                source_id, serid, event_time, state="FAILED", retry_at=at + timedelta(seconds=delay),
            )
            if failed:
                return "FAILED", exc
            return self.source_silence_state(source_id, serid, event_time) or "CANCELLED", exc

    def dispatch_source_response(self, source_id: str, serid: int, event_time: datetime, *, at: datetime,
                                 responder: Callable[[], bool]) -> tuple[str, Exception | None]:
        """Claim an operator response without entering the suppression retry state machine."""
        with self.source_silence_lock(source_id, serid, event_time):
            if self.claim_source_response(source_id, serid, event_time, claimed_at=at) is None:
                return "SKIPPED", None
            try:
                if not responder():
                    raise RuntimeError("source menolak alarm response")
                confirmed = self.finish_claimed_source_response(
                    source_id, serid, event_time, state="CONFIRMED",
                )
                return ("CONFIRMED" if confirmed else "SKIPPED"), None
            except Exception as exc:
                failed = self.finish_claimed_source_response(
                    source_id, serid, event_time, state="FAILED",
                )
                return ("FAILED" if failed else "SKIPPED"), exc

    def bind_source_silences_to_suppression(self, event_id: str, suppression_id: str, *,
                                             connection: sqlite3.Connection | None = None) -> None:
        own = connection is None
        db = connection or self.security._connection()
        try:
            db.execute(
                """UPDATE remote_alarm_state
                   SET suppression_id=?, source_silence_state=COALESCE(source_silence_state, 'PENDING')
                   WHERE policy_event_id=? AND EXISTS (
                       SELECT 1 FROM alarm_suppression AS suppression
                       WHERE suppression.suppression_id=? AND suppression.ended_at IS NULL
                   )""",
                (str(suppression_id), str(event_id), str(suppression_id)),
            )
        finally:
            if own:
                db.close()

    def bind_source_silence_if_active(self, source_id: str, serid: int, event_time: datetime,
                                      suppression_id: str, *, retry_at: datetime) -> bool:
        """Bind a delayed source observation only while its suppression remains active."""
        with self.security._connection() as db:
            self._begin(db)
            try:
                cursor = db.execute(
                    """UPDATE remote_alarm_state
                       SET suppression_id=?, source_silence_state='PENDING', source_silence_retry_at=?
                       WHERE source_id=? AND serid=? AND event_time=? AND EXISTS (
                           SELECT 1 FROM alarm_suppression AS suppression
                           WHERE suppression.suppression_id=? AND suppression.ended_at IS NULL
                       )""",
                    (str(suppression_id), _iso(retry_at), str(source_id), int(serid), _iso(event_time), str(suppression_id)),
                )
                if cursor.rowcount != 1:
                    db.execute(
                        """UPDATE remote_alarm_state
                           SET source_silence_state='CANCELLED', source_silence_retry_at=NULL
                           WHERE source_id=? AND serid=? AND event_time=? AND suppression_id=?
                             AND NOT EXISTS (
                                 SELECT 1 FROM alarm_suppression AS suppression
                                 WHERE suppression.suppression_id=? AND suppression.ended_at IS NULL
                             )""",
                        (str(source_id), int(serid), _iso(event_time), str(suppression_id), str(suppression_id)),
                    )
                db.commit()
                return cursor.rowcount == 1
            except Exception:
                db.rollback()
                raise

    def bind_policy_event_to_suppression(self, event_id: str, suppression_id: str, *,
                                         connection: sqlite3.Connection | None = None) -> None:
        own = connection is None
        db = connection or self.security._connection()
        try:
            db.execute(
                "UPDATE alarm_policy_event SET suppression_id=? WHERE event_id=? AND status='ACTIVE'",
                (str(suppression_id), str(event_id)),
            )
        finally:
            if own:
                db.close()

    def active_suppression_event(self, serid: int, suppression_id: str, source_id: str) -> PolicyEvent | None:
        with self.security._connection() as db:
            rows = db.execute(
                """SELECT event_id, event_key, serid, source_id, remote_serid, remote_event_time,
                          origin, kind, trigger_index, surfaced_at, measured_value, threshold, status,
                          suppression_id, responded_at, pic, action, reason, notification_sent_at
                   FROM alarm_policy_event
                   WHERE serid=? AND suppression_id=? AND kind='ALARM' AND status='ACTIVE'
                     AND (source_id IS NULL OR source_id=?)
                   ORDER BY surfaced_at DESC LIMIT 2""",
                (int(serid), str(suppression_id), str(source_id)),
            ).fetchall()
        if len(rows) != 1:
            return None
        return self._event_from_row(rows[0])

    def suppression_source_silence_state(self, suppression_id: str) -> str:
        with self.security._connection() as db:
            rows = db.execute(
                "SELECT source_silence_state FROM remote_alarm_state WHERE suppression_id=?",
                (str(suppression_id),),
            ).fetchall()
        states = {str(row[0]) for row in rows if row[0]}
        for state in ("UNCERTAIN", "FAILED", "RECONCILING", "PENDING", "DISPATCHING", "CANCELLED", "RECONCILED", "CONFIRMED"):
            if state in states:
                return state
        return "NONE"

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
                      started_by, ended_at, ended_reason, ended_by, first_suppressed_alarm_at, created_at, updated_at
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
        self.store.end_suppression(
            suppression_id, at, reason, ended_by="system", cancel_source_silences=True,
            connection=self.connection,
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
