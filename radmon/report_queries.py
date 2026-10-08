from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .config import Settings


def _default_connection(settings: Settings):
    from .db import connect_mariadb

    return connect_mariadb(settings)


class DatabaseReportSummaryReader:
    """Efficient full-range report aggregates without loading every sample."""

    def __init__(
        self,
        settings: Settings,
        *,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._connection_factory = connection_factory or (
            lambda: _default_connection(settings)
        )

    def summary(
        self,
        start: datetime,
        end: datetime,
        *,
        serid: int,
    ) -> dict[str, Any]:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT
  MIN(dtom) AS first_measurement,
  MAX(dtom) AS last_measurement,
  MIN(doserate) AS minimum,
  AVG(doserate) AS average,
  MAX(doserate) AS maximum,
  COUNT(doserate) AS sample_count,
  COALESCE(SUM(COALESCE(dose, 0)), 0) AS approximate_dose
FROM measurement
WHERE serid = ?
  AND dtom >= ?
  AND dtom <= ?
""",
                    (serid, start, end),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            return {}
        if isinstance(row, dict):
            return dict(row)
        keys = (
            "first_measurement",
            "last_measurement",
            "minimum",
            "average",
            "maximum",
            "sample_count",
            "approximate_dose",
        )
        return dict(zip(keys, row))

    def measurement_rows(
        self,
        start: datetime,
        end: datetime,
        *,
        serid: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read report detail rows without the generic history-view limit.

        The report worker asks for one bounded, deterministic batch after its
        indexed count preflight.  Keeping this query beside the aggregate query
        prevents a report from accidentally inheriting a UI history limit such
        as 1,000 rows.
        """
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE serid = ?
  AND dtom >= ?
  AND dtom <= ?
ORDER BY dtom ASC, serid ASC
LIMIT ?
""",
                    (serid, start, end, max(1, int(limit))),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        keys = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
        return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
