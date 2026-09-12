from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, Callable

from .audit import AuditTrail
from .security import SecurityStore, UserIdentity


_REMOTE_ALARM_SCHEMA_LOCK = threading.Lock()


class RemoteAlarmMirror:
    def __init__(self, store: SecurityStore) -> None:
        self.store = store

    @staticmethod
    def _event_time(row: dict[str, Any]) -> datetime:
        value = row.get("dtoa", row.get("dtom"))
        if not isinstance(value, datetime):
            raise ValueError("alarm event time tidak valid")
        return value

    @staticmethod
    def _level(row: dict[str, Any]) -> str:
        if "lvl" in row:
            return "ALARM" if int(row.get("lvl") or 0) >= 2 else "ALERT"
        value = str(row.get("type") or "ALERT").upper()
        return value if value in {"ALERT", "ALARM"} else "ALERT"

        def mirror(self, source_id: str, rows: list[dict[str, Any]]) -> int:
            self._ensure_active_schema()
            changed = 0
            with self.store._connection() as connection:
                for row in rows:
                    event_time = self._event_time(row)
                    event_iso = event_time.isoformat()
                    serid = int(row["serid"])
                    remote_serid = int(row.get("_remote_serid", serid))
                    acknowledged_at = row.get("i_op")
                    ack_iso = (
                        acknowledged_at.isoformat()
                        if isinstance(acknowledged_at, datetime) else None
                    )
                    if "i_flag" in row:
                        is_active = 0 if int(row.get("i_flag") or 0) else 1
                    else:
                        is_active = 0 if ack_iso or bool(row.get("ack")) else 1
                    historical = bool(row.get("_historical_seed"))
                    already_notified = (
                        historical
                        or not bool(is_active)
                        or bool(row.get("ack"))
                        or ack_iso is not None
                    )
                    notification_sent_at = ack_iso or (
                        event_iso if already_notified else None
                    )
                    before_changes = connection.total_changes
                    connection.execute(
                        """
    INSERT INTO remote_alarm_state
      (source_id, serid, remote_serid, event_time, level, measured_value,
       threshold, hit_count, acknowledged_at, pic, action, note,
       notification_sent_at, is_active)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source_id, serid, event_time) DO UPDATE SET
      remote_serid = excluded.remote_serid,
      level = excluded.level,
      measured_value = COALESCE(excluded.measured_value, measured_value),
      threshold = COALESCE(excluded.threshold, threshold),
      hit_count = COALESCE(excluded.hit_count, hit_count),
      is_active = excluded.is_active,
      acknowledged_at = CASE
        WHEN excluded.is_active = 1 THEN NULL
        ELSE COALESCE(excluded.acknowledged_at, acknowledged_at)
      END,
      pic = COALESCE(excluded.pic, pic),
      note = COALESCE(excluded.note, note),
      notification_sent_at = COALESCE(notification_sent_at, excluded.notification_sent_at)
    """,
                        (
                            source_id, serid, remote_serid, event_iso,
                            self._level(row), row.get("mvalue"), row.get("thvalue"),
                            row.get("nhit"), ack_iso, row.get("pic"), None,
                            row.get("note"), notification_sent_at, is_active,
                        ),
                    )
                    if connection.total_changes > before_changes:
                        changed += 1
            return changed

    @staticmethod
    def _row(row):
        keys = (
            "source_id", "serid", "remote_serid", "event_time", "level",
            "measured_value", "threshold", "hit_count", "acknowledged_at",
            "pic", "action", "note", "notification_sent_at", "is_active",
        )
        item = dict(zip(keys, row))
        for key in ("event_time", "acknowledged_at", "notification_sent_at"):
            if item[key]:
                item[key] = datetime.fromisoformat(str(item[key]))
        item["is_active"] = bool(item.get("is_active"))
        return item

        def list_alarms(self, *, active_only: bool = False, limit: int = 500):
            self._ensure_active_schema()
            clause = "WHERE is_active = 1" if active_only else ""
            with self.store._connection() as connection:
                rows = connection.execute(
                    f"""
    SELECT source_id, serid, remote_serid, event_time, level, measured_value,
           threshold, hit_count, acknowledged_at, pic, action, note,
           notification_sent_at, is_active
    FROM remote_alarm_state {clause}
    ORDER BY event_time DESC LIMIT ?
    """,
                    (max(1, int(limit)),),
                ).fetchall()
            return [self._row(row) for row in rows]

        def get(self, source_id: str, serid: int, event_time: datetime):
            self._ensure_active_schema()
            with self.store._connection() as connection:
                row = connection.execute(
                    """
    SELECT source_id, serid, remote_serid, event_time, level, measured_value,
           threshold, hit_count, acknowledged_at, pic, action, note,
           notification_sent_at, is_active
    FROM remote_alarm_state
    WHERE source_id = ? AND serid = ? AND event_time = ?
    """,
                    (source_id, int(serid), event_time.isoformat()),
                ).fetchone()
            return self._row(row) if row else None

        def mark_acknowledged(
            self,
            source_id: str,
            serid: int,
            event_time: datetime,
            *,
            acknowledged_at: datetime,
            pic: str,
            action: str,
            note: str,
        ):
            self._ensure_active_schema()
            with self.store._connection() as connection:
                cursor = connection.execute(
                    """
    UPDATE remote_alarm_state
    SET acknowledged_at = ?, pic = ?, action = ?, note = ?, is_active = 0
    WHERE source_id = ? AND serid = ? AND event_time = ? AND is_active = 1
    """,
                    (
                        acknowledged_at.isoformat(), pic, action, note,
                        source_id, int(serid), event_time.isoformat(),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("alarm sudah ditangani atau tidak ditemukan")
            item = get(self, source_id, serid, event_time)
            if item is None:
                raise RuntimeError("alarm tidak ditemukan setelah response")
            return item

    def mark_notification_sent(self, source_id: str, serid: int, event_time: datetime, at: datetime) -> None:
        with self.store._connection() as connection:
            connection.execute(
                """
UPDATE remote_alarm_state SET notification_sent_at = ?
WHERE source_id = ? AND serid = ? AND event_time = ?
""",
                (at.isoformat(), source_id, int(serid), event_time.isoformat()),
            )

    def _ensure_active_schema(self) -> None:
        if getattr(self, "_active_schema_ready", False):
            return
        with _REMOTE_ALARM_SCHEMA_LOCK:
            if getattr(self, "_active_schema_ready", False):
                return
            with self.store._connection() as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(remote_alarm_state)"
                    ).fetchall()
                }
                if "is_active" not in columns:
                    connection.execute(
                        "ALTER TABLE remote_alarm_state "
                        "ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                    )
                connection.execute(
                    "UPDATE remote_alarm_state SET is_active = 0 "
                    "WHERE acknowledged_at IS NOT NULL"
                )
            self._active_schema_ready = True

        def reconcile_source_active_keys(
            self,
            source_id: str,
            active_keys: set[tuple[int, datetime]],
        ) -> list[tuple[int, datetime]]:
            self._ensure_active_schema()
            normalized = {
                (int(serid), when.isoformat())
                for serid, when in active_keys
                if isinstance(when, datetime)
            }
            handled: list[tuple[int, datetime]] = []
            with self.store._connection() as connection:
                rows = connection.execute(
                    """
    SELECT serid, event_time
    FROM remote_alarm_state
    WHERE source_id = ? AND is_active = 1
    """,
                    (str(source_id),),
                ).fetchall()
                for serid, event_text in rows:
                    key = (int(serid), str(event_text))
                    if key in normalized:
                        continue
                    cursor = connection.execute(
                        """
    UPDATE remote_alarm_state
    SET is_active = 0
    WHERE source_id = ? AND serid = ? AND event_time = ? AND is_active = 1
    """,
                        (str(source_id), int(serid), str(event_text)),
                    )
                    if cursor.rowcount == 1:
                        handled.append((int(serid), datetime.fromisoformat(str(event_text))))
            return handled


class AlarmControlService:
    def __init__(
        self,
        security: SecurityStore,
        mirror: RemoteAlarmMirror,
        audit: AuditTrail,
        *,
        remote_factory: Callable[[str], Any],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.security = security
        self.mirror = mirror
        self.audit = audit
        self.remote_factory = remote_factory
        self.now = now or datetime.now

    def ack(
        self,
        identity,
        pin: str,
        source_id: str,
        serid: int,
        event_time: datetime,
        *,
        action: str,
        pic: str,
        note: str,
    ):
        self.security.require_sensitive(identity, "ack_alarm", pin)
        if not action.strip() or not pic.strip():
            raise ValueError("Action dan PIC wajib diisi")
        before = self.mirror.get(source_id, serid, event_time)
        if before is None:
            raise RuntimeError("alarm tidak ditemukan")
        if before.get("is_active") is False:
            raise RuntimeError("alarm sudah ditangani")
        remote_serid = int(before.get("remote_serid") or serid)
        at = self.now()
        target_id = f"{source_id}:{serid}:{event_time.isoformat()}"
        try:
            remote = self.remote_factory(source_id)
            ok = bool(
                remote.respond_alarm(
                    remote_serid,
                    event_time,
                    action=action.strip(),
                    pic=pic.strip(),
                    note=note.strip(),
                    at=at,
                )
            )
            if not ok:
                raise RuntimeError("source menolak response; alarm mungkin sudah ditangani")
            after = self.mirror.mark_acknowledged(
                source_id,
                serid,
                event_time,
                acknowledged_at=at,
                pic=pic.strip(),
                action=action.strip(),
                note=note.strip(),
            )
        except Exception as exc:
            self.audit.record(
                "ALARM_ACK", identity, "alarm", target_id,
                before=before, success=False, reason=str(exc), source=source_id,
            )
            raise
        self.audit.record(
            "ALARM_ACK", identity, "alarm", target_id,
            before=before, after=after, source=source_id,
        )
        return after
