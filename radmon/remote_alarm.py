from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .audit import AuditTrail
from .security import SecurityStore, UserIdentity


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
        changed = 0
        with self.store._connection() as connection:
            for row in rows:
                event_time = self._event_time(row).isoformat()
                serid = int(row["serid"])
                remote_serid = int(row.get("_remote_serid", serid))
                before = connection.total_changes
                connection.execute(
                    """
INSERT INTO remote_alarm_state
  (source_id, serid, remote_serid, event_time, level, measured_value, threshold, hit_count,
   acknowledged_at, pic, action, note)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(source_id, serid, event_time) DO UPDATE SET
  remote_serid = excluded.remote_serid,
  level = excluded.level,
  measured_value = COALESCE(excluded.measured_value, measured_value),
  threshold = COALESCE(excluded.threshold, threshold),
  hit_count = COALESCE(excluded.hit_count, hit_count),
  acknowledged_at = COALESCE(excluded.acknowledged_at, acknowledged_at),
  pic = COALESCE(excluded.pic, pic),
  note = COALESCE(excluded.note, note)
""",
                    (
                        source_id,
                        serid,
                        remote_serid,
                        event_time,
                        self._level(row),
                        row.get("mvalue"),
                        row.get("thvalue"),
                        row.get("nhit"),
                        row.get("i_op").isoformat() if isinstance(row.get("i_op"), datetime) else None,
                        row.get("pic"),
                        None,
                        row.get("note"),
                    ),
                )
                if connection.total_changes > before:
                    changed += 1
        return changed

    @staticmethod
    def _row(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = (
            "source_id", "serid", "remote_serid", "event_time", "level", "measured_value", "threshold",
            "hit_count", "acknowledged_at", "pic", "action", "note", "notification_sent_at",
        )
        item = dict(zip(keys, row))
        for key in ("event_time", "acknowledged_at", "notification_sent_at"):
            if item[key]:
                item[key] = datetime.fromisoformat(str(item[key]))
        return item

    def list_alarms(self, *, active_only: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        clause = "WHERE acknowledged_at IS NULL" if active_only else ""
        with self.store._connection() as connection:
            rows = connection.execute(
                f"""
SELECT source_id, serid, remote_serid, event_time, level, measured_value, threshold, hit_count,
       acknowledged_at, pic, action, note, notification_sent_at
FROM remote_alarm_state {clause}
ORDER BY event_time DESC LIMIT ?
""",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, source_id: str, serid: int, event_time: datetime) -> dict[str, Any] | None:
        with self.store._connection() as connection:
            row = connection.execute(
                """
SELECT source_id, serid, remote_serid, event_time, level, measured_value, threshold, hit_count,
       acknowledged_at, pic, action, note, notification_sent_at
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
    ) -> dict[str, Any]:
        with self.store._connection() as connection:
            cursor = connection.execute(
                """
UPDATE remote_alarm_state
SET acknowledged_at = ?, pic = ?, action = ?, note = ?
WHERE source_id = ? AND serid = ? AND event_time = ? AND acknowledged_at IS NULL
""",
                (
                    acknowledged_at.isoformat(), pic, action, note,
                    source_id, int(serid), event_time.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("alarm sudah di-ACK atau tidak ditemukan")
        item = self.get(source_id, serid, event_time)
        if item is None:
            raise RuntimeError("alarm tidak ditemukan setelah ACK")
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
        identity: UserIdentity,
        pin: str,
        source_id: str,
        serid: int,
        event_time: datetime,
        *,
        action: str,
        pic: str,
        note: str,
    ) -> dict[str, Any]:
        self.security.require_sensitive(identity, "ack_alarm", pin)
        if not action.strip() or not pic.strip():
            raise ValueError("Action dan PIC wajib diisi")
        before = self.mirror.get(source_id, serid, event_time)
        if before is None:
            raise RuntimeError("alarm tidak ditemukan")
        if before.get("acknowledged_at") is not None:
            raise RuntimeError("alarm sudah di-ACK")
        remote_serid = int(before.get("remote_serid") or serid)
        at = self.now()
        target_id = f"{source_id}:{serid}:{event_time.isoformat()}"
        try:
            remote = self.remote_factory(source_id)
            ok = bool(
                remote.ack_legacy(
                    remote_serid,
                    event_time,
                    action=action.strip(),
                    pic=pic.strip(),
                    note=note.strip(),
                    at=at,
                )
            )
            if not ok:
                raise RuntimeError("source menolak ACK; alarm mungkin sudah ditangani")
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
