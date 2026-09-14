from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .lan import MariaCentralStore, _shared_serids


class BatchedMariaCentralStore(MariaCentralStore):
    """Write one source live snapshot with one central MariaDB transaction."""

    @staticmethod
    def _ensure_remote_device_with_cursor(cursor: Any, source_id: str, row: dict[str, Any]) -> None:
        serid = int(row["serid"])
        cursor.execute(
            "SELECT name, location, hwaddress, hwtype FROM device WHERE serid = ?",
            (serid,),
        )
        existing = cursor.fetchone()
        if existing is not None:
            if isinstance(existing, dict):
                old_name = str(existing.get("name") or "")
                old_location = str(existing.get("location") or "")
                old_source = str(existing.get("hwaddress") or "")
                old_type = str(existing.get("hwtype") or "")
            else:
                old_name, old_location, old_source, old_type = (
                    str(value or "") for value in existing[:4]
                )
            if old_type == "remote" and old_source and old_source != source_id:
                compatible = (
                    old_name == str(row.get("name") or "")
                    and old_location == str(row.get("location") or "")
                )
                if serid not in _shared_serids() or not compatible:
                    raise RuntimeError(
                        f"SERID conflict {serid}: source {old_source} vs {source_id}"
                    )
                return

        cursor.execute(
            """INSERT INTO device
  (serid, name, location, maxidlemin, warnlevel, alarmlevel, unit,
   audiopath, hwaddress, hwtype, description)
VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'remote', ?)
ON DUPLICATE KEY UPDATE
  name = VALUES(name), location = VALUES(location), maxidlemin = VALUES(maxidlemin),
  warnlevel = VALUES(warnlevel), alarmlevel = VALUES(alarmlevel), unit = VALUES(unit),
  hwaddress = VALUES(hwaddress), hwtype = 'remote', description = VALUES(description)""",
            (
                serid,
                str(row.get("name") or f"Remote {serid}"),
                str(row.get("location") or source_id),
                int(row.get("maxidlemin") or 30),
                float(row.get("warnlevel") or 0),
                float(row.get("alarmlevel") or 0),
                str(row.get("unit") or "µSv/h"),
                source_id[:50],
                str(row.get("description") or f"Synced from {source_id}")[:255],
            ),
        )

    def upsert_live_rows(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0

        connection = self._connection()
        changed = 0
        try:
            with connection.cursor() as cursor:
                for row in values:
                    self._ensure_remote_device_with_cursor(cursor, source_id, row)

                    cursor.execute(
                        """INSERT INTO recent
  (serid, dtom, doserate, dose, lastrate, minrate, maxrate, avgrate,
   lastdose, mindose, maxdose, avgdose, firstmea, lastmea, lastmeasec, meacount)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  dtom = VALUES(dtom), doserate = VALUES(doserate), dose = VALUES(dose),
  lastrate = VALUES(lastrate), minrate = VALUES(minrate), maxrate = VALUES(maxrate),
  avgrate = VALUES(avgrate), lastdose = VALUES(lastdose), mindose = VALUES(mindose),
  maxdose = VALUES(maxdose), avgdose = VALUES(avgdose), firstmea = VALUES(firstmea),
  lastmea = VALUES(lastmea), lastmeasec = VALUES(lastmeasec), meacount = VALUES(meacount)""",
                        (
                            int(row["serid"]),
                            row.get("dtom"),
                            float(row["doserate"]) if row.get("doserate") is not None else 0.0,
                            row.get("dose"),
                            row.get("lastrate"),
                            row.get("minrate"),
                            row.get("maxrate"),
                            row.get("avgrate"),
                            row.get("lastdose"),
                            row.get("mindose"),
                            row.get("maxdose"),
                            row.get("avgdose"),
                            row.get("firstmea"),
                            row.get("lastmea"),
                            row.get("lastmeasec"),
                            row.get("meacount"),
                        ),
                    )
                    changed += 1

                    measured_at = row.get("dtom")
                    rate = row.get("doserate")
                    if not isinstance(measured_at, datetime) or rate is None:
                        continue
                    try:
                        interval = int(row.get("lastmeasec") or 2)
                    except (TypeError, ValueError):
                        interval = 2
                    if interval < 1 or interval > 3600:
                        interval = 2
                    cursor.execute(
                        """INSERT IGNORE INTO measurement
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, 0)""",
                        (
                            int(row["serid"]),
                            measured_at,
                            float(rate),
                            float(row.get("dose") or 0.0),
                            interval,
                        ),
                    )
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
