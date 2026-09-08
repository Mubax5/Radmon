from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from typing import Any

from .security import SecurityStore, UserIdentity


_SENSITIVE_MARKERS = ("password", "pin", "token", "secret")


def _safe(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SENSITIVE_MARKERS):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = _safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class AuditTrail:
    def __init__(self, store: SecurityStore, application_logger: Any | None = None) -> None:
        self.store = store
        self.application_logger = application_logger

    def record(
        self,
        action: str,
        identity: UserIdentity | None,
        target_type: str | None = None,
        target_id: str | None = None,
        *,
        before: Any = None,
        after: Any = None,
        success: bool = True,
        reason: str | None = None,
        source: str | None = None,
    ) -> None:
        occurred_at = datetime.now(timezone.utc).isoformat()
        before_json = json.dumps(_safe(before), ensure_ascii=False, sort_keys=True) if before is not None else None
        after_json = json.dumps(_safe(after), ensure_ascii=False, sort_keys=True) if after is not None else None
        username = identity.username if identity else None
        role = identity.role.value if identity else None
        with self.store._connection() as connection:
            connection.execute(
                """
INSERT INTO audit_events
  (occurred_at, username, role, action, target_type, target_id, source,
   before_json, after_json, success, reason)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    occurred_at,
                    username,
                    role,
                    action,
                    target_type,
                    target_id,
                    source,
                    before_json,
                    after_json,
                    1 if success else 0,
                    reason,
                ),
            )

        if self.application_logger is not None and hasattr(self.application_logger, "record_applog"):
            actor = username or "anonymous"
            result = "SUCCESS" if success else "FAILED"
            summary = f"AUDIT {result} user={actor} action={action}"
            if target_type or target_id:
                summary += f" target={target_type or '-'}:{target_id or '-'}"
            if source:
                summary += f" source={source}"
            if before_json is not None or after_json is not None:
                summary += f" before={before_json or '-'} after={after_json or '-'}"
            if reason:
                summary += f" reason={reason}"
            self.application_logger.record_applog(summary)

    def list_events(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.store._connection() as connection:
            rows = connection.execute(
                """
SELECT audit_id, occurred_at, username, role, action, target_type, target_id,
       source, before_json, after_json, success, reason
FROM audit_events ORDER BY audit_id DESC LIMIT ?
""",
                (max(1, int(limit)),),
            ).fetchall()
        keys = (
            "audit_id", "occurred_at", "username", "role", "action", "target_type",
            "target_id", "source", "before_json", "after_json", "success", "reason",
        )
        return [dict(zip(keys, row)) for row in rows]
