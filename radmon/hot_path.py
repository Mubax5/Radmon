from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .central_api import CentralMariaDBRepository
from .datetime_utils import parse_database_datetime
from .lan import LIVE_KEYS, RemoteMariaDBSource


# Retain the historical private import for downstream source adapters.
_parse_dtom = parse_database_datetime


def _snapshot_needs_measurement_fallback(row: dict[str, Any]) -> bool:
    measured_at = parse_database_datetime(row.get("dtom"))
    if measured_at is None:
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
        # Reconnect-friendly: transient remote failures must not kill the
        # 2-second live mirror; fall back to last measurement sample.
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        """SELECT serid, name, location, warnlevel, alarmlevel, unit, audiopath,
       description, maxidlemin, dtom, doserate, dose, lastrate,
       minrate, maxrate, avgrate, lastdose, mindose, maxdose,
       avgdose, lastmea, lastmeasec, meacount, firstmea
FROM vrecent
ORDER BY serid"""
                    )
                    rows = self._dict_rows(cursor.fetchall(), LIVE_KEYS)
                except Exception:
                    # vrecent is a disposable view; if it fails (e.g. transient
                    # collation or lock), fall back to per-detector latest
                    # measurement so recent can still be refreshed.
                    rows = []
                    try:
                        cursor.execute("SELECT serid, name, location, warnlevel, alarmlevel, unit, audiopath, description, maxidlemin FROM device ORDER BY serid")
                        devices = self._dict_rows(cursor.fetchall(), ("serid", "name", "location", "warnlevel", "alarmlevel", "unit", "audiopath", "description", "maxidlemin"))
                    except Exception:
                        return []
                    for dev in devices:
                        try:
                            cursor.execute(
                                """SELECT serid, dtom, doserate, dose
FROM measurement
WHERE serid = ?
ORDER BY dtom DESC LIMIT 1""",
                                (int(dev["serid"]),),
                            )
                            latest_raw = cursor.fetchone()
                        except Exception:
                            continue
                        if latest_raw is None:
                            rows.append({**dev, "dtom": None, "doserate": None, "dose": None, "lastrate": None, "minrate": None, "maxrate": None, "avgrate": None, "lastdose": None, "mindose": None, "maxdose": None, "avgdose": None, "firstmea": None, "lastmea": None, "lastmeasec": 2, "meacount": 0})
                            continue
                        latest = (
                            dict(latest_raw)
                            if isinstance(latest_raw, dict)
                            else dict(zip(("serid", "dtom", "doserate", "dose"), latest_raw))
                        )
                        latest_at = parse_database_datetime(latest.get("dtom"))
                        if latest_at is None:
                            continue
                        rows.append({**dev, "dtom": latest_at, "doserate": latest.get("doserate"), "dose": latest.get("dose"), "lastrate": latest.get("doserate"), "minrate": None, "maxrate": None, "avgrate": None, "lastdose": None, "mindose": None, "maxdose": None, "avgdose": None, "firstmea": None, "lastmea": latest_at, "lastmeasec": 2, "meacount": 1})
                    return rows

                for row in rows:
                    if not _snapshot_needs_measurement_fallback(row):
                        continue
                    try:
                        cursor.execute(
                            """SELECT serid, dtom, doserate, dose
FROM measurement
WHERE serid = ?
ORDER BY dtom DESC LIMIT 1""",
                            (int(row["serid"]),),
                        )
                        latest_raw = cursor.fetchone()
                    except Exception:
                        continue
                    if latest_raw is None:
                        continue
                    latest = (
                        dict(latest_raw)
                        if isinstance(latest_raw, dict)
                        else dict(zip(("serid", "dtom", "doserate", "dose"), latest_raw))
                    )
                    latest_at = parse_database_datetime(latest.get("dtom"))
                    current_at = parse_database_datetime(row.get("dtom"))
                    if latest_at is None:
                        continue
                    if isinstance(current_at, datetime) and latest_at <= current_at:
                        continue
                    # Normalize to datetime for downstream mirror.
                    row["dtom"] = latest_at
                    row["lastmea"] = latest_at
                    if latest.get("doserate") is not None:
                        try:
                            row["doserate"] = float(latest["doserate"])
                        except (TypeError, ValueError):
                            continue
                    row["dose"] = latest.get("dose")
            return rows
        finally:
            try:
                connection.close()
            except Exception:
                pass


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
  SELECT serid, MAX(dtom) AS mdtom FROM vrecent GROUP BY serid
) newest ON newest.serid = d.serid
LEFT JOIN vrecent v ON v.serid = newest.serid AND v.dtom = newest.mdtom
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
