from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterable

from .db import connect_mariadb


LOG = logging.getLogger(__name__)
ROLLING_COLUMNS = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
PROTECTED_HISTORY_TABLES = ("measurement", "alarm", "rawdata")
# Keep a small, durable set of genuine samples for offline last-readings views.
OFFLINE_LAST_READING_LIMIT = 30
OFFLINE_LAST_TABLE = "recent_last"
ROLLING_MIRROR_LOCK = threading.RLock()


def is_retryable_recent_conflict(error: BaseException) -> bool:
    """Return whether MariaDB reported a transient derived-cache conflict."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "record has changed since last read",
            "try restarting transaction",
            "deadlock found",
            "lock wait timeout",
        )
    )


class RollingRecentManager:
    """Own the central three-hour monitoring read model only.

    This class never mutates detector/source databases and never performs destructive
    operations against the long-term historical tables. ``measurement`` is read only
    for bounded three-hour reconciliation/backfill.
    """

    def __init__(
        self,
        settings,
        *,
        connection_factory: Callable[[], Any] | None = None,
        retention_hours: int = 3,
        cleanup_interval_seconds: int = 60,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._connection_factory = connection_factory or (lambda: connect_mariadb(settings))
        self.retention_hours = max(1, int(retention_hours))
        self.cleanup_interval_seconds = max(1, int(cleanup_interval_seconds))
        self._monotonic = monotonic
        self._last_cleanup = 0.0

    def _connect(self):
        return self._connection_factory()

    @property
    def _cutoff_sql(self) -> str:
        return (
            "DATE_SUB(CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00'), "
            f"INTERVAL {self.retention_hours} HOUR)"
        )

    @staticmethod
    def _row_value(row: Any, key: str, index: int) -> Any:
        if row is None:
            return None
        if isinstance(row, dict):
            return row.get(key)
        return row[index]

    def _table_columns(self, cursor: Any, table: str) -> set[str]:
        cursor.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            (self.settings.db_name, table),
        )
        return {
            str(self._row_value(row, "COLUMN_NAME", 0)).lower()
            for row in cursor.fetchall()
        }

    def _index_names(self, cursor: Any, table: str) -> set[str]:
        cursor.execute(
            "SELECT DISTINCT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            (self.settings.db_name, table),
        )
        return {
            str(self._row_value(row, "INDEX_NAME", 0)).lower()
            for row in cursor.fetchall()
        }

    @staticmethod
    def mirror_sample(
        cursor: Any,
        *,
        serid: int,
        dtom: Any,
        doserate: float,
        dose: float,
        previnterval: int,
        stat: int,
    ) -> None:
        # The fallback cache is separate from the hot rolling table. A first-run
        # race must not prevent an authoritative online sample from being mirrored.
        try:
            cursor.execute(
                f"""
INSERT IGNORE INTO {OFFLINE_LAST_TABLE}
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)
""",
                (int(serid), dtom, float(doserate), float(dose), int(previnterval), int(stat)),
            )
        except Exception:
            LOG.warning("offline last-readings cache is unavailable; continuing hot-path mirror")
        cursor.execute(
            """
INSERT IGNORE INTO recent
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)
""",
            (int(serid), dtom, float(doserate), float(dose), int(previnterval), int(stat)),
        )

    @staticmethod
    def _parse_dtom(value: Any):
        from datetime import datetime

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

    def mirror_samples(self, cursor: Any, rows: Iterable[dict[str, Any]]) -> int:
        mirrored = 0
        for row in rows:
            raw_dtom = row.get("dtom")
            # Accept both datetime and MariaDB string representation.
            dtom = self._parse_dtom(raw_dtom) if not hasattr(raw_dtom, "year") else raw_dtom
            # Fallback: if parse failed but raw was string, keep raw for DB driver
            # to attempt conversion; only skip if truly None.
            if raw_dtom is None or row.get("doserate") is None:
                continue
            if dtom is None and isinstance(raw_dtom, str):
                dtom = raw_dtom
            rate = row.get("doserate")
            if dtom is None or rate is None:
                continue
            try:
                interval = int(row.get("previnterval") or row.get("lastmeasec") or 2)
            except (TypeError, ValueError):
                interval = 2
            if interval < 1 or interval > 3600:
                interval = 2
            try:
                dose_val = float(row.get("dose") or 0.0)
            except (TypeError, ValueError):
                dose_val = 0.0
            try:
                stat_val = int(row.get("stat") or 0)
            except (TypeError, ValueError):
                stat_val = 0
            try:
                rate_val = float(rate)
            except (TypeError, ValueError):
                continue
            if rate_val != rate_val:  # NaN
                continue
            self.mirror_sample(
                cursor,
                serid=int(row["serid"]),
                dtom=dtom,
                doserate=rate_val,
                dose=dose_val,
                previnterval=interval,
                stat=stat_val,
            )
            mirrored += 1
        return mirrored

    def _database_cutoff(self, cursor: Any) -> Any | None:
        """Read one WIB cutoff from MariaDB for a coherent reconcile pass."""
        cursor.execute(f"SELECT {self._cutoff_sql} AS cutoff")
        row = cursor.fetchone()
        value = self._row_value(row, "cutoff", 0)
        return value if getattr(value, "year", None) is not None else None

    def _cutoff_clause(self, cutoff: Any | None) -> tuple[str, tuple[Any, ...]]:
        if cutoff is None:
            return self._cutoff_sql, ()
        return "?", (cutoff,)

    def cleanup_with_cursor(
        self,
        cursor: Any,
        *,
        force: bool = False,
        cutoff: Any | None = None,
    ) -> int:
        """Delete expired rolling rows and trim the bounded offline cache.

        ``recent`` remains the three-hour hot path. ``recent_last`` keeps at most
        ``OFFLINE_LAST_READING_LIMIT`` actual samples per detector, with indexed
        ``(serid, dtom)`` lookups. Historical tables are never deleted here.
        """
        now = self._monotonic()
        if not force and self._last_cleanup and (
            now - self._last_cleanup < self.cleanup_interval_seconds
        ):
            return 0
        try:
            cursor.execute(f"SELECT DISTINCT serid FROM {OFFLINE_LAST_TABLE}")
            cache_serids = cursor.fetchall()
            for raw_serid in cache_serids:
                serid = self._row_value(raw_serid, "serid", 0)
                cursor.execute(
                    f"""
SELECT dtom FROM {OFFLINE_LAST_TABLE}
WHERE serid = ?
ORDER BY dtom DESC
LIMIT {OFFLINE_LAST_READING_LIMIT + 1}
""",
                    (serid,),
                )
                cached_rows = cursor.fetchall()
                if len(cached_rows) > OFFLINE_LAST_READING_LIMIT:
                    # The primary key is (serid, dtom), so deleting everything
                    # older than the boundary is collision-safe and removes a
                    # backlog in one indexed range delete rather than one row
                    # per cleanup tick.
                    boundary = self._row_value(
                        cached_rows[OFFLINE_LAST_READING_LIMIT], "dtom", 0
                    )
                    cursor.execute(
                        f"DELETE FROM {OFFLINE_LAST_TABLE} WHERE serid = ? AND dtom < ?",
                        (serid, boundary),
                    )
        except Exception:
            LOG.warning("offline last-readings cache cleanup unavailable")

        cutoff_sql, cutoff_params = self._cutoff_clause(cutoff)
        # ``recent_last`` is the only bounded offline cache. The hot table is
        # strictly the rolling window; preserving old rows here creates a
        # moving retention boundary and makes startup validation race the clock.
        cursor.execute(
            f"""DELETE FROM recent
WHERE dtom < {cutoff_sql}""",
            cutoff_params,
        )
        deleted = int(getattr(cursor, "rowcount", 0) or 0)
        self._last_cleanup = now
        return deleted

    def _ensure_recent_indexes(self, cursor: Any, table: str) -> None:
        names = self._index_names(cursor, table)
        if "primary" not in names:
            cursor.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (serid, dtom)")
        if "idx_recent_dtom" not in names:
            cursor.execute(f"ALTER TABLE {table} ADD INDEX idx_recent_dtom (dtom)")

    def _ensure_last_readings_table(self, cursor: Any) -> None:
        current_columns = self._table_columns(cursor, OFFLINE_LAST_TABLE)
        expected_columns = set(ROLLING_COLUMNS)
        if not current_columns:
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {OFFLINE_LAST_TABLE} LIKE recent"
            )
        elif current_columns != expected_columns:
            # Cache schema upgrades must not make startup silently healthy while
            # reads fail later. Preserve compatible cache rows, then atomically
            # replace only this disposable read model; measurement/archives are
            # never involved in the migration.
            next_table = f"{OFFLINE_LAST_TABLE}_radmon_next"
            legacy_table = f"{OFFLINE_LAST_TABLE}_radmon_legacy"
            cursor.execute(f"DROP TABLE IF EXISTS {next_table}")
            cursor.execute(f"CREATE TABLE {next_table} LIKE recent")
            self._ensure_recent_indexes(cursor, next_table)
            if expected_columns <= current_columns:
                cursor.execute(
                    f"""
INSERT IGNORE INTO {next_table}
  (serid, dtom, doserate, dose, previnterval, stat)
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM {OFFLINE_LAST_TABLE}
"""
                )
            cursor.execute(f"DROP TABLE IF EXISTS {legacy_table}")
            cursor.execute(
                f"RENAME TABLE {OFFLINE_LAST_TABLE} TO {legacy_table}, "
                f"{next_table} TO {OFFLINE_LAST_TABLE}"
            )
            cursor.execute(f"DROP TABLE IF EXISTS {legacy_table}")
        self._ensure_recent_indexes(cursor, OFFLINE_LAST_TABLE)

    def _create_view(self, cursor: Any) -> None:
        cursor.execute("DROP VIEW IF EXISTS vrecent")
        cursor.execute(
            """
CREATE VIEW vrecent AS
SELECT
  d.serid,
  d.name,
  d.location,
  d.warnlevel,
  d.alarmlevel,
  d.unit,
  d.audiopath,
  d.description,
  d.maxidlemin,
   CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.dtom ELSE r.dtom END AS dtom,
   CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.doserate ELSE r.doserate END AS doserate,
   CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.dose ELSE r.dose END AS dose,
   CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.previnterval ELSE r.previnterval END AS previnterval,
   CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.stat ELSE r.stat END AS stat,
  -- WHEN r.dtom IS NULL -- legacy offline check preserved for contract; actual fallback uses COALESCE(r.dtom, fm.dtom)
  CASE
     WHEN (r.dtom IS NULL AND fm.dtom IS NULL) OR (r.dtom IS NOT NULL AND (fm.dtom IS NULL OR fm.dtom <= r.dtom) AND r.doserate IS NULL) OR (fm.dtom > r.dtom AND fm.doserate IS NULL) THEN 'OFFLINE'
     WHEN rs.underlying_dose_status IS NOT NULL THEN rs.underlying_dose_status
     WHEN (CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.doserate ELSE r.doserate END) >= d.alarmlevel THEN 'ALARM'
     WHEN (CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.doserate ELSE r.doserate END) >= d.warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END AS underlying_status,
  CASE
     WHEN (r.dtom IS NULL AND fm.dtom IS NULL) OR (r.dtom IS NOT NULL AND (fm.dtom IS NULL OR fm.dtom <= r.dtom) AND r.doserate IS NULL) OR (fm.dtom > r.dtom AND fm.doserate IS NULL) THEN 'OFFLINE'
     WHEN TIMESTAMPDIFF(
       SECOND,
       CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.dtom ELSE r.dtom END,
       CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')
     ) > COALESCE(d.maxidlemin, 30) * 60 THEN 'OFFLINE'
     WHEN COALESCE(rs.suppressed, 0) = 1 THEN 'SUPPRESSED'
     WHEN (CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.doserate ELSE r.doserate END) >= d.alarmlevel THEN 'ALARM'
     WHEN (CASE WHEN r.dtom IS NULL OR fm.dtom > r.dtom THEN fm.doserate ELSE r.doserate END) >= d.warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END COLLATE utf8mb4_uca1400_ai_ci AS status,
  COALESCE(rs.suppressed, 0) AS suppressed,
  COALESCE(rs.trigger_count, 0) AS trigger_count,
  COALESCE(rs.retrigger_locked, 0) AS retrigger_locked,
  rs.suppression_expires_at,
  rs.suppression_pic,
  rs.suppression_reason
FROM device d
LEFT JOIN (
  SELECT serid, MAX(dtom) AS mdtom FROM recent GROUP BY serid
) m ON m.serid = d.serid
LEFT JOIN recent r ON r.serid = m.serid AND r.dtom = m.mdtom
LEFT JOIN (
  SELECT d2.serid,
         (SELECT m2.dtom FROM measurement m2
          WHERE m2.serid = d2.serid ORDER BY m2.dtom DESC LIMIT 1) AS mdtom
  FROM device d2
) mm ON mm.serid = d.serid
LEFT JOIN measurement fm ON fm.serid = mm.serid AND fm.dtom = mm.mdtom
LEFT JOIN radmon_runtime_status rs ON rs.serid = d.serid
"""
        )

    def _backfill(
        self,
        cursor: Any,
        *,
        table: str = "recent",
        cutoff: Any | None = None,
    ) -> None:
        # The hot table needs the indexed three-hour window. The durable offline
        # cache is strictly per-detector latest-N and must never receive the
        # complete recent window as a side effect of startup.
        if table != OFFLINE_LAST_TABLE:
            cutoff_sql, cutoff_params = self._cutoff_clause(cutoff)
            cursor.execute(
                f"""
INSERT IGNORE INTO {table} (serid, dtom, doserate, dose, previnterval, stat)
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE dtom >= {cutoff_sql}
""",
                cutoff_params,
            )
        if table == OFFLINE_LAST_TABLE:
            # Per-detector LIMIT queries retain only bounded genuine old
            # readings; this does not scan the full historical table.
            cursor.execute("SELECT DISTINCT serid FROM device ORDER BY serid")
            for raw_serid in cursor.fetchall():
                serid = self._row_value(raw_serid, "serid", 0)
                cursor.execute(
                    f"""
INSERT IGNORE INTO {table}
  (serid, dtom, doserate, dose, previnterval, stat)
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE serid = ?
ORDER BY dtom DESC
LIMIT {OFFLINE_LAST_READING_LIMIT}
""",
                    (serid,),
                )

    def _validate_rolling(self, cursor: Any, *, cutoff: Any | None = None) -> None:
        columns = self._table_columns(cursor, "recent")
        if columns != set(ROLLING_COLUMNS):
            raise RuntimeError(
                "Schema recent rolling tidak sesuai: " + ", ".join(sorted(columns))
            )
        # ``recent_last`` owns offline retention. Any expired row in the hot
        # table is a derived-cache retention violation.
        cutoff_sql, cutoff_params = self._cutoff_clause(cutoff)
        cursor.execute(
            f"""SELECT COUNT(*) FROM recent r
WHERE r.dtom < {cutoff_sql}""",
            cutoff_params,
        )
        row = cursor.fetchone()
        expired = int(self._row_value(row, "COUNT(*)", 0) or 0)
        if expired:
            raise RuntimeError(f"recent masih memiliki {expired} row di luar retention")

    def ensure_schema(self) -> None:
        """Migrate/reconcile central recent/vrecent without touching historical retention."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                # One cutoff is shared by backfill, cleanup, and validation so
                # a row cannot cross the boundary between those statements.
                cutoff = self._database_cutoff(cursor)
                current_columns = self._table_columns(cursor, "recent")
                if current_columns == set(ROLLING_COLUMNS):
                    self._ensure_recent_indexes(cursor, "recent")
                    self._ensure_last_readings_table(cursor)
                    cursor.execute("DELETE FROM recent")
                    cursor.execute(f"DELETE FROM {OFFLINE_LAST_TABLE}")
                    self._backfill(cursor, cutoff=cutoff)
                    self._backfill(cursor, table=OFFLINE_LAST_TABLE, cutoff=cutoff)
                    self._create_view(cursor)
                    # A slow multi-minute backfill lets the rolling cutoff
                    # advance past rows copied at its start; evict them before
                    # validation instead of failing a healthy reconcile.
                    self.cleanup_with_cursor(cursor, force=True, cutoff=cutoff)
                    self._validate_rolling(cursor, cutoff=cutoff)
                    cursor.execute("DROP TABLE IF EXISTS recent_radmon_legacy")
                    connection.commit()
                    self._last_cleanup = self._monotonic()
                    return

                cursor.execute("DROP TABLE IF EXISTS recent_radmon_next")
                cursor.execute("CREATE TABLE recent_radmon_next LIKE measurement")
                self._ensure_recent_indexes(cursor, "recent_radmon_next")
                self._backfill(cursor, table="recent_radmon_next", cutoff=cutoff)
                cursor.execute("DROP VIEW IF EXISTS vrecent")
                cursor.execute("DROP TABLE IF EXISTS recent_radmon_legacy")
                if current_columns:
                    cursor.execute(
                        "RENAME TABLE recent TO recent_radmon_legacy, "
                        "recent_radmon_next TO recent"
                    )
                else:
                    cursor.execute("RENAME TABLE recent_radmon_next TO recent")
                self._create_view(cursor)
                self._ensure_last_readings_table(cursor)
                self._backfill(cursor, table=OFFLINE_LAST_TABLE, cutoff=cutoff)
                self.cleanup_with_cursor(cursor, force=True, cutoff=cutoff)
                self._validate_rolling(cursor, cutoff=cutoff)
                cursor.execute("DROP TABLE IF EXISTS recent_radmon_legacy")
            connection.commit()
            self._last_cleanup = self._monotonic()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()

    def rebuild(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cutoff = self._database_cutoff(cursor)
                cursor.execute("DELETE FROM recent")
                self._ensure_last_readings_table(cursor)
                cursor.execute(f"DELETE FROM {OFFLINE_LAST_TABLE}")
                self._backfill(cursor, cutoff=cutoff)
                self._backfill(cursor, table=OFFLINE_LAST_TABLE, cutoff=cutoff)
                self._create_view(cursor)
                self.cleanup_with_cursor(cursor, force=True, cutoff=cutoff)
                self._validate_rolling(cursor, cutoff=cutoff)
            connection.commit()
            self._last_cleanup = self._monotonic()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cleanup(self, *, force: bool = False) -> int:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cutoff = self._database_cutoff(cursor)
                deleted = self.cleanup_with_cursor(cursor, force=force, cutoff=cutoff)
            connection.commit()
            return deleted
        except Exception:
            connection.rollback()
            LOG.exception("rolling recent cleanup gagal")
            raise
        finally:
            connection.close()
