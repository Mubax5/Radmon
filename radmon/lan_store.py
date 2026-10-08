from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import Any, Callable, Iterable

from .lan import MariaCentralStore, _shared_serids
from .recent_read_model import (
    ROLLING_MIRROR_LOCK,
    RollingRecentManager,
    is_retryable_recent_conflict,
)


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
    def _parse_dtom(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace(" ", "T"))
            except ValueError:
                try:
                    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return None
        return None

    @staticmethod
    def _rolling_row(row: dict[str, Any]) -> dict[str, Any] | None:
        measured_at = BatchedMariaCentralStore._parse_dtom(row.get("dtom"))
        rate = row.get("doserate")
        if measured_at is None or rate is None:
            return None
        # Guard against NaN/empty string rates that would silently drop recent.
        try:
            doserate = float(rate)
        except (TypeError, ValueError):
            return None
        # NaN check
        if doserate != doserate:  # NaN
            return None
        try:
            interval = int(row.get("lastmeasec") or row.get("previnterval") or 2)
        except (TypeError, ValueError):
            interval = 2
        if interval < 1 or interval > 3600:
            interval = 2
        try:
            dose = float(row.get("dose") or 0.0)
        except (TypeError, ValueError):
            dose = 0.0
        if dose != dose:
            dose = 0.0
        try:
            stat = int(row.get("stat") or 0)
        except (TypeError, ValueError):
            stat = 0
        return {
            "serid": int(row["serid"]),
            "dtom": measured_at,
            "doserate": doserate,
            "dose": dose,
            "previnterval": interval,
            "stat": stat,
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

            # Phase 2: disposable/read-optimized mirror. History above is already
            # durable; mirror/cleanup failure cannot roll it back.
            if rolling_rows:
                try:
                    # All live-source threads share this process-wide derived
                    # cache. Serialize mirror + cleanup and retry only MariaDB's
                    # transient optimistic-concurrency conflict.
                    with ROLLING_MIRROR_LOCK:
                        for attempt in range(3):
                            try:
                                with connection.cursor() as cursor:
                                    self._recent_manager.mirror_samples(cursor, rolling_rows)
                                    self._recent_manager.cleanup_with_cursor(cursor)
                                connection.commit()
                                break
                            except Exception as exc:
                                connection.rollback()
                                if not is_retryable_recent_conflict(exc) or attempt == 2:
                                    raise
                                LOG.warning(
                                    "rolling recent conflict; retrying mirror attempt=%s",
                                    attempt + 2,
                                )
                                time.sleep(0.05 * (attempt + 1))
                except Exception:
                    connection.rollback()
                    LOG.exception(
                        "measurement source=%s tersimpan tetapi rolling recent gagal",
                        source_id,
                    )
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
