from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


class SourceHealthService:
    """Persist per-source LAN connectivity state in the security sidecar."""

    def __init__(
        self,
        security_store,
        *,
        offline_after_failures: int = 3,
        now: Callable[[], datetime] | None = None,
        transition_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = security_store
        self.offline_after_failures = max(1, int(offline_after_failures))
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.transition_sink = transition_sink
        self._init_schema()

    def _init_schema(self) -> None:
        with self.store._connection() as connection:
            connection.executescript(
                """
CREATE TABLE IF NOT EXISTS source_health (
  source_id TEXT PRIMARY KEY,
  host TEXT NOT NULL,
  state TEXT NOT NULL,
  last_success TEXT,
  last_failure TEXT,
  last_live_poll TEXT,
  last_alarm_poll TEXT,
  last_history_import TEXT,
  last_error TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
"""
            )

    @staticmethod
    def _to_dict(row) -> dict[str, Any] | None:
        if row is None:
            return None
        keys = (
            "source_id", "host", "state", "last_success", "last_failure",
            "last_live_poll", "last_alarm_poll", "last_history_import",
            "last_error", "consecutive_failures", "updated_at",
        )
        item = dict(zip(keys, row))
        item["consecutive_failures"] = int(item.get("consecutive_failures") or 0)
        return item

    def get(self, source_id: str) -> dict[str, Any] | None:
        with self.store._connection() as connection:
            row = connection.execute(
                """
SELECT source_id, host, state, last_success, last_failure,
       last_live_poll, last_alarm_poll, last_history_import,
       last_error, consecutive_failures, updated_at
FROM source_health WHERE source_id = ?
""",
                (source_id,),
            ).fetchone()
        return self._to_dict(row)

    def list_states(self) -> list[dict[str, Any]]:
        with self.store._connection() as connection:
            rows = connection.execute(
                """
SELECT source_id, host, state, last_success, last_failure,
       last_live_poll, last_alarm_poll, last_history_import,
       last_error, consecutive_failures, updated_at
FROM source_health ORDER BY source_id
"""
            ).fetchall()
        return [self._to_dict(row) for row in rows if row is not None]

    def _emit_transition(self, item: dict[str, Any], previous: str | None) -> dict[str, Any]:
        state = str(item["state"])
        message = None
        # RECOVERED is the operator-facing recovery transition. The next healthy
        # poll silently normalizes the stored state back to CONNECTED.
        if previous is not None and state != previous and not (previous == "RECOVERED" and state == "CONNECTED"):
            message = f"[SERVER {state}] {item['source_id']} / {item['host']}"
            if item.get("last_error") and state in {"DEGRADED", "OFFLINE"}:
                message += f" - {item['last_error']}"
        item["transition_message"] = message
        if message and self.transition_sink is not None:
            self.transition_sink(dict(item))
        return item

    def record_success(self, source, *, live: bool, alarm: bool, history: bool) -> dict[str, Any]:
        current = self.get(source.source_id)
        previous = str(current["state"]) if current else None
        at = self.now().astimezone(timezone.utc).isoformat()
        state = "RECOVERED" if previous in {"DEGRADED", "OFFLINE"} else "CONNECTED"
        with self.store._connection() as connection:
            connection.execute(
                """
INSERT INTO source_health
  (source_id, host, state, last_success, last_failure, last_live_poll,
   last_alarm_poll, last_history_import, last_error, consecutive_failures, updated_at)
VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, 0, ?)
ON CONFLICT(source_id) DO UPDATE SET
  host = excluded.host,
  state = excluded.state,
  last_success = excluded.last_success,
  last_live_poll = CASE WHEN ? THEN excluded.last_live_poll ELSE source_health.last_live_poll END,
  last_alarm_poll = CASE WHEN ? THEN excluded.last_alarm_poll ELSE source_health.last_alarm_poll END,
  last_history_import = CASE WHEN ? THEN excluded.last_history_import ELSE source_health.last_history_import END,
  last_error = NULL,
  consecutive_failures = 0,
  updated_at = excluded.updated_at
""",
                (
                    source.source_id, source.host, state, at,
                    at if live else None, at if alarm else None, at if history else None, at,
                    1 if live else 0, 1 if alarm else 0, 1 if history else 0,
                ),
            )
        item = self.get(source.source_id)
        assert item is not None
        return self._emit_transition(item, previous)

    def record_failure(self, source, error: str) -> dict[str, Any]:
        current = self.get(source.source_id)
        previous = str(current["state"]) if current else None
        failures = int(current.get("consecutive_failures") or 0) + 1 if current else 1
        state = "OFFLINE" if failures >= self.offline_after_failures else "DEGRADED"
        at = self.now().astimezone(timezone.utc).isoformat()
        with self.store._connection() as connection:
            connection.execute(
                """
INSERT INTO source_health
  (source_id, host, state, last_success, last_failure, last_live_poll,
   last_alarm_poll, last_history_import, last_error, consecutive_failures, updated_at)
VALUES (?, ?, ?, NULL, ?, NULL, NULL, NULL, ?, ?, ?)
ON CONFLICT(source_id) DO UPDATE SET
  host = excluded.host,
  state = excluded.state,
  last_failure = excluded.last_failure,
  last_error = excluded.last_error,
  consecutive_failures = excluded.consecutive_failures,
  updated_at = excluded.updated_at
""",
                (source.source_id, source.host, state, at, str(error)[:1000], failures, at),
            )
        item = self.get(source.source_id)
        assert item is not None
        return self._emit_transition(item, previous)
