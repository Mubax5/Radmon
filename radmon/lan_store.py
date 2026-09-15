from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Callable, Iterable

from .lan import MariaCentralStore, _shared_serids
from .recent_read_model import RollingRecentManager


LOG = logging.getLogger(__name__)


class BatchedMariaCentralStore(MariaCentralStore):
    """Write one source live snapshot efficiently while preserving history first."""

    def __init__(self, settings, *, connection_factory: Callable[[], Any] | None = None) -> None:
        super().__init__(settings, connection_factory=connection_factory)
        self._recent_manager = RollingRecentManager(
            settings,
            connection_factory=self._connection,
        )

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

    @staticmethod
    def _rolling_row(row: dict[str, Any]) -> dict[str, Any] | None:
        measured_at = row.get("dtom")
        rate = row.get("doserate")
        if not isinstance(measured_at, datetime) or rate is None:
            return None
        try:
            interval = int(row.get("lastmeasec") or row.get("previnterval") or 2)
        except (TypeError, ValueError):
            interval = 2
        if interval < 1 or interval > 3600:
            interval = 2
        return {
            "serid": int(row["serid"]),
            "dtom": measured_at,
            "doserate": float(rate),
            "dose": float(row.get("dose") or 0.0),
            "previnterval": interval,
            "stat": int(row.get("stat") or 0),
        }

    def upsert_live_rows(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0

        connection = self._connection()
        rolling_rows: list[dict[str, Any]] = []
        changed = 0
        try:
            # Phase 1: device metadata + authoritative historical measurement.
            with connection.cursor() as cursor:
                for row in values:
                    self._ensure_remote_device_with_cursor(cursor, source_id, row)
                    rolling = self._rolling_row(row)
                    if rolling is None:
                        continue
                    cursor.execute(
                        """INSERT IGNORE INTO measurement
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            rolling["serid"], rolling["dtom"], rolling["doserate"],
                            rolling["dose"], rolling["previnterval"], rolling["stat"],
                        ),
                    )
                    rolling_rows.append(rolling)
                    changed += 1
            connection.commit()

            # Phase 2: disposable/read-optimized mirror. Failure here must not undo
            # measurements already committed above.
            if rolling_rows:
                try:
                    with connection.cursor() as cursor:
                        self._recent_manager.mirror_samples(cursor, rolling_rows)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    LOG.exception(
                        "measurement source=%s tersimpan tetapi rolling recent gagal",
                        source_id,
                    )
            try:
                self._recent_manager.cleanup()
            except Exception:
                pass
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
