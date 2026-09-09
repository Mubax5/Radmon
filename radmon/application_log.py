from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


class MariaApplicationLogWriter:
    """Write concise human-readable audit summaries to central ``applog``."""

    def __init__(self, settings, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self.connection_factory = connection_factory

    def _connect(self):
        if self.connection_factory is not None:
            return self.connection_factory()
        from .db import connect_mariadb
        return connect_mariadb(self.settings)

    def record_applog(self, message: str, at: datetime | None = None) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO applog (ts, id, msg) VALUES (?, ?, ?)",
                    (at or datetime.now(), 0, str(message)[:4000]),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
