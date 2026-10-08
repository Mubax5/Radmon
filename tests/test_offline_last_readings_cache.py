from __future__ import annotations

from datetime import datetime

from radmon.config import Settings
from radmon.grafana_tv import build_dashboard_payloads
from radmon.recent_read_model import OFFLINE_LAST_READING_LIMIT, RollingRecentManager


class RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), tuple(params)))

    def fetchall(self):
        sql = self.calls[-1][0].lower()
        if "select distinct serid from device" in sql:
            return [(5201,), (5701,)]
        return []

    def fetchone(self):
        return (0,)


def test_mirror_keeps_real_timestamp_in_cache_and_hot_path_without_cutoff():
    cursor = RecordingCursor()
    RollingRecentManager.mirror_sample(
        cursor,
        serid=5701,
        dtom=datetime(2026, 6, 23, 10, 0, 0),
        doserate=0.17,
        dose=0.01,
        previnterval=2,
        stat=0,
    )

    assert "insert ignore into recent_last" in cursor.calls[0][0].lower()
    assert "insert ignore into recent" in cursor.calls[-1][0].lower()
    assert cursor.calls[0][1] == cursor.calls[-1][1] == (5701, datetime(2026, 6, 23, 10, 0, 0), 0.17, 0.01, 2, 0)


def test_mirror_keeps_stale_source_sample_only_in_bounded_cache_when_cutoff_is_known():
    cursor = RecordingCursor()
    RollingRecentManager.mirror_sample(
        cursor,
        serid=5701,
        dtom=datetime(2026, 6, 23, 10, 0, 0),
        doserate=0.17,
        dose=0.01,
        previnterval=2,
        stat=0,
        hot_cutoff=datetime(2026, 10, 8, 4, 0, 0),
    )

    assert "insert ignore into recent_last" in cursor.calls[0][0].lower()
    assert "select ?, ?, ?, ?, ?, ?" in cursor.calls[-1][0].lower()
    assert "where ? >= ?" in cursor.calls[-1][0].lower()


def test_cleanup_keeps_offline_cache_bounded_and_hot_path_strictly_rolling():
    cursor = RecordingCursor()
    manager = RollingRecentManager(Settings())
    manager.cleanup_with_cursor(cursor, force=True)
    sql = cursor.calls[-1][0].lower()

    assert f"{OFFLINE_LAST_READING_LIMIT}" not in sql
    assert "from recent kept" not in sql
    assert "newer.dtom > recent.dtom" not in sql
    assert "delete from recent" in sql
    assert "interval 3 hour" in sql
    assert all(table not in sql for table in ("measurement", "alarm", "rawdata"))


def test_cache_cleanup_removes_the_entire_older_backlog_in_one_key_range():
    class BacklogCursor(RecordingCursor):
        def fetchall(self):
            sql = self.calls[-1][0].lower()
            if "select distinct serid from recent_last" in sql:
                return [(5701,)]
            if "from recent_last" in sql and "limit 31" in sql:
                return [(datetime(2026, 6, 23, 10, 0, 0),)] * (OFFLINE_LAST_READING_LIMIT + 1)
            return []

    cursor = BacklogCursor()
    RollingRecentManager(Settings()).cleanup_with_cursor(cursor, force=True)
    deletes = [sql for sql, _ in cursor.calls if sql.lower().startswith("delete from recent_last")]
    assert len(deletes) == 1
    assert "dtom < ?" in deletes[0]


def test_backfill_uses_per_detector_limit_instead_of_full_history_fallback_scan():
    cursor = RecordingCursor()
    RollingRecentManager(Settings())._backfill(cursor, table="recent_last")
    statements = [sql.lower() for sql, _ in cursor.calls]
    per_detector = [sql for sql in statements if "where serid = ?" in sql and "from measurement" in sql]
    assert per_detector
    assert all(f"limit {OFFLINE_LAST_READING_LIMIT}" in sql for sql in per_detector)
    assert all("dtom >=" not in sql for sql in statements)


def test_grafana_offline_table_uses_original_times_and_no_synthetic_values():
    page_two = build_dashboard_payloads()[1]
    panel = next(item for item in page_two["panels"] if item.get("description") == "offline-last-readings")
    sql = panel["targets"][0]["rawSql"]

    assert "FROM recent_last" in sql
    assert "DATE_FORMAT(r.dtom" in sql
    assert "Umur Data (detik)" in sql
    assert "OFFLINE · LAST READING" in sql
    assert "FROM measurement" not in sql
    assert f"LIMIT {15 * OFFLINE_LAST_READING_LIMIT}" in sql
    assert panel["fieldConfig"]["overrides"][0]["properties"][1] == {"id": "decimals", "value": 2}
