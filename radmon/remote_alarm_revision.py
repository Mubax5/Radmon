"""Compatibility adjustments for legacy production alarm mirroring."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def apply() -> None:
    from . import remote_alarm as module

    def mirror(self, source_id: str, rows: list[dict[str, Any]]) -> int:
        changed = 0
        with self.store._connection() as connection:
            for row in rows:
                event_time = self._event_time(row)
                event_iso = event_time.isoformat()
                serid = int(row["serid"])
                remote_serid = int(row.get("_remote_serid", serid))
                acknowledged_at = row.get("i_op")
                ack_iso = acknowledged_at.isoformat() if isinstance(acknowledged_at, datetime) else None
                historical = bool(row.get("_historical_seed"))
                already_notified = historical or bool(row.get("i_flag")) or bool(row.get("ack")) or ack_iso is not None
                notification_sent_at = ack_iso or (event_iso if already_notified else None)
                before = connection.total_changes
                connection.execute(
                    """
INSERT INTO remote_alarm_state
  (source_id, serid, remote_serid, event_time, level, measured_value, threshold, hit_count,
   acknowledged_at, pic, action, note, notification_sent_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(source_id, serid, event_time) DO UPDATE SET
  remote_serid = excluded.remote_serid,
  level = excluded.level,
  measured_value = COALESCE(excluded.measured_value, measured_value),
  threshold = COALESCE(excluded.threshold, threshold),
  hit_count = COALESCE(excluded.hit_count, hit_count),
  acknowledged_at = COALESCE(excluded.acknowledged_at, acknowledged_at),
  pic = COALESCE(excluded.pic, pic),
  note = COALESCE(excluded.note, note),
  notification_sent_at = COALESCE(notification_sent_at, excluded.notification_sent_at)
""",
                    (
                        source_id,
                        serid,
                        remote_serid,
                        event_iso,
                        self._level(row),
                        row.get("mvalue"),
                        row.get("thvalue"),
                        row.get("nhit"),
                        ack_iso,
                        row.get("pic"),
                        None,
                        row.get("note"),
                        notification_sent_at,
                    ),
                )
                if connection.total_changes > before:
                    changed += 1
        return changed

    module.RemoteAlarmMirror.mirror = mirror
