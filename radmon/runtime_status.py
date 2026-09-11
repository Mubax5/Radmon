from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import mariadb


class RuntimeStatusProjector:
    """Project current policy state into the central MariaDB only.

    The projector is intentionally constructed from the central Settings object
    and never accepts a LAN/source connection, preventing accidental DDL on the
    production source hosts.
    """

    CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS radmon_runtime_status (
  serid INT PRIMARY KEY,
  policy_state VARCHAR(32) NOT NULL,
  trigger_count INT NOT NULL,
  retrigger_locked TINYINT NOT NULL,
  suppressed TINYINT NOT NULL,
  suppression_expires_at DATETIME NULL,
  suppression_pic VARCHAR(128) NULL,
  suppression_reason VARCHAR(1000) NULL,
  underlying_dose_status VARCHAR(16) NOT NULL,
  updated_at DATETIME NOT NULL
)
"""

    UPSERT_SQL = """
INSERT INTO radmon_runtime_status
  (serid, policy_state, trigger_count, retrigger_locked, suppressed,
   suppression_expires_at, suppression_pic, suppression_reason,
   underlying_dose_status, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  policy_state = VALUES(policy_state),
  trigger_count = VALUES(trigger_count),
  retrigger_locked = VALUES(retrigger_locked),
  suppressed = VALUES(suppressed),
  suppression_expires_at = VALUES(suppression_expires_at),
  suppression_pic = VALUES(suppression_pic),
  suppression_reason = VALUES(suppression_reason),
  underlying_dose_status = VALUES(underlying_dose_status),
  updated_at = VALUES(updated_at)
"""

    def __init__(self, settings, *, connection_factory: Callable[[], object] | None = None) -> None:
        self.settings = settings
        self.connection_factory = connection_factory

    def _connection(self):
        if self.connection_factory is not None:
            return self.connection_factory()
        return mariadb.connect(
            host=self.settings.db_host,
            port=int(self.settings.db_port),
            user=self.settings.db_user,
            password=self.settings.db_password,
            database=self.settings.db_name,
            autocommit=False,
        )

    def ensure_schema(self) -> None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(self.CREATE_TABLE_SQL)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _sql_datetime(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo is not None else value
        return value

    def project(self, snapshot: dict) -> None:
        updated_at = snapshot.get("updated_at") or datetime.now(timezone.utc)
        params = (
            int(snapshot["serid"]),
            str(snapshot.get("policy_state") or "NORMAL"),
            int(snapshot.get("trigger_count") or 0),
            1 if snapshot.get("retrigger_locked") else 0,
            1 if snapshot.get("suppressed") else 0,
            self._sql_datetime(snapshot.get("suppression_expires_at")),
            snapshot.get("suppression_pic"),
            snapshot.get("suppression_reason"),
            str(snapshot.get("underlying_dose_status") or "NORMAL"),
            self._sql_datetime(updated_at),
        )
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(self.UPSERT_SQL, params)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
