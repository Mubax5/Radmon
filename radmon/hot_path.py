from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .central_api import CentralMariaDBRepository
from .lan import LIVE_KEYS, RemoteMariaDBSource


def _snapshot_needs_measurement_fallback(row: dict[str, Any]) -> bool:
    measured_at = row.get("dtom")
    if not isinstance(measured_at, datetime):
        return True

    try:
        interval = int(row.get("lastmeasec") or 2)
    except (TypeError, ValueError):
        interval = 2
    if interval < 1 or interval > 3600:
        interval = 2

    try:
        max_idle_minutes = max(1, int(row.get("maxidlemin") or 30))
    except (TypeError, ValueError):
        max_idle_minutes = 30

    # Keep the normal realtime path on each source's legacy vrecent. Only verify
    # source measurement when that source snapshot has stopped moving.
    refresh_after_seconds = min(max_idle_minutes * 60, max(10, interval * 3))
    now = datetime.now(measured_at.tzinfo) if measured_at.tzinfo is not None else datetime.now()
    return (now - measured_at) > timedelta(seconds=refresh_after_seconds)


class RealtimeRemoteMariaDBSource(RemoteMariaDBSource):
    """Low-cost source read model with an indexed fallback for stale snapshots."""

    def live_rows(self) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT serid, name, location, warnlevel, alarmlevel, unit, audiopath,
       description, maxidlemin, dtom, doserate, dose, lastrate,
       minrate, maxrate, avgrate, lastdose, mindose, maxdose,
       avgdose, lastmea, lastmeasec, meacount, firstmea
FROM vrecent
ORDER BY serid"""
                )
                rows = self._dict_rows(cursor.fetchall(), LIVE_KEYS)

                for row in rows:
                    if not _snapshot_needs_measurement_fallback(row):
                        continue
                    cursor.execute(
                        """SELECT serid, dtom, doserate, dose
FROM measurement
WHERE serid = ?
ORDER BY dtom DESC LIMIT 1""",
                        (int(row["serid"]),),
                    )
                    latest_raw = cursor.fetchone()
                    if latest_raw is None:
                        continue
                    latest = (
                        dict(latest_raw)
                        if isinstance(latest_raw, dict)
                        else dict(zip(("serid", "dtom", "doserate", "dose"), latest_raw))
                    )
                    latest_at = latest.get("dtom")
                    current_at = row.get("dtom")
                    if not isinstance(latest_at, datetime):
                        continue
                    if isinstance(current_at, datetime) and latest_at <= current_at:
                        continue
                    row["dtom"] = latest_at
                    row["lastmea"] = latest_at
                    if latest.get("doserate") is not None:
                        row["doserate"] = float(latest["doserate"])
                    row["dose"] = latest.get("dose")
            return rows
        finally:
            connection.close()


class RealtimeCentralMariaDBRepository(CentralMariaDBRepository):
    """Serve overview from the bounded three-hour central monitoring read model."""

    def overview_rows(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT d.serid, d.name, d.location, d.description, d.warnlevel, d.alarmlevel, d.maxidlemin, d.unit,
       v.dtom, v.doserate, v.dose, v.previnterval, v.stat
FROM device d
LEFT JOIN (
  SELECT current.*
  FROM vrecent current
  JOIN (
    SELECT serid, MAX(dtom) AS dtom
    FROM recent
    WHERE dtom IS NOT NULL
    GROUP BY serid
  ) newest ON newest.serid = current.serid AND newest.dtom = current.dtom
) v ON v.serid = d.serid
ORDER BY d.location, d.name
"""
                )
                rows = cursor.fetchall()
            keys = (
                "serid", "name", "location", "description", "warnlevel", "alarmlevel", "maxidlemin", "unit",
                "dtom", "doserate", "dose", "previnterval", "stat",
            )
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()
