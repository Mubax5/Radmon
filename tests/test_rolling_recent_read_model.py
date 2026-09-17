from __future__ import annotations

from pathlib import Path

from radmon.config import Settings
from radmon.grafana_tv import build_dashboard_payloads
from radmon.lan import LIVE_KEYS
from radmon.repository import REQUIRED_SCHEMA


ROOT = Path(__file__).resolve().parents[1]


class _RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.rowcount = 3

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), tuple(params)))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _RecordingConnection:
    def __init__(self) -> None:
        self.cursor_obj = _RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_rolling_recent_manager_exists_with_three_hour_defaults():
    from radmon.recent_read_model import RollingRecentManager

    connection = _RecordingConnection()
    manager = RollingRecentManager(Settings(), connection_factory=lambda: connection)
    assert manager.retention_hours == 3
    assert manager.cleanup_interval_seconds == 60


def test_cleanup_deletes_only_expired_recent_rows():
    from radmon.recent_read_model import RollingRecentManager

    connection = _RecordingConnection()
    manager = RollingRecentManager(Settings(), connection_factory=lambda: connection)
    deleted = manager.cleanup(force=True)

    assert deleted == 3
    sql = "\n".join(statement for statement, _ in connection.cursor_obj.calls).lower()
    assert "delete from recent" in sql
    assert "interval 3 hour" in sql
    for protected in ("measurement", "alarm", "rawdata"):
        assert f"delete from {protected}" not in sql
        assert f"truncate table {protected}" not in sql
        assert f"drop table {protected}" not in sql
    assert connection.commits == 1


def test_mirror_sample_uses_only_rolling_sample_fields():
    from radmon.recent_read_model import RollingRecentManager

    cursor = _RecordingCursor()
    RollingRecentManager.mirror_sample(
        cursor,
        serid=5201,
        dtom="2026-09-15 08:00:00",
        doserate=0.27,
        dose=0.01,
        previnterval=2,
        stat=0,
    )
    sql = cursor.calls[-1][0].lower()
    assert "insert ignore into recent" in sql
    for field in ("serid", "dtom", "doserate", "dose", "previnterval", "stat"):
        assert field in sql
    for legacy in ("lastrate", "minrate", "maxrate", "avgrate", "meacount", "lastmea"):
        assert legacy not in sql


def test_central_schema_contract_redefines_only_recent_and_vrecent():
    assert REQUIRED_SCHEMA["recent"] == {
        "serid", "dtom", "doserate", "dose", "previnterval", "stat"
    }
    required_view_fields = {
        "serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel",
        "unit", "audiopath", "description", "dtom", "doserate", "dose",
        "previnterval", "stat", "underlying_status", "status", "suppressed",
        "trigger_count", "retrigger_locked", "suppression_expires_at",
        "suppression_pic", "suppression_reason",
    }
    assert required_view_fields <= REQUIRED_SCHEMA["vrecent"]
    assert REQUIRED_SCHEMA["measurement"] == {
        "serid", "dtom", "doserate", "dose", "previnterval", "stat"
    }
    assert "dtoa" in REQUIRED_SCHEMA["alarm"]
    assert REQUIRED_SCHEMA["rawdata"] == {"serid", "dtom", "val"}


def test_central_live_write_uses_shared_rolling_manager_not_legacy_aggregates():
    source = (ROOT / "radmon" / "lan_store.py").read_text(encoding="utf-8")
    manager = (ROOT / "radmon" / "recent_read_model.py").read_text(encoding="utf-8")
    assert "INSERT IGNORE INTO measurement" in source
    assert "mirror_samples" in source
    assert "INSERT IGNORE INTO recent" in manager
    assert "previnterval" in manager
    assert "stat" in manager
    assert "INSERT INTO recent\n  (serid, dtom, doserate, dose, lastrate" not in source + manager


def test_archive_rebuild_delegates_to_bounded_rolling_manager():
    source = (ROOT / "radmon" / "archive_store.py").read_text(encoding="utf-8")
    start = source.index("    def rebuild_recent")
    block = source[start:]
    assert "RollingRecentManager" in block
    assert "manager.rebuild()" in block
    assert "MIN(doserate)" not in block
    assert "AVG(doserate)" not in block
    assert "COUNT(*)" not in block


def test_ensure_schema_evicts_backfill_boundary_rows_before_validation():
    """A slow multi-minute backfill lets the rolling cutoff advance past rows
    copied at its start; ensure_schema must evict them before validation
    instead of failing a healthy reconcile with vrecent already recreated."""
    from radmon.recent_read_model import ROLLING_COLUMNS, RollingRecentManager

    class _SchemaCursor(_RecordingCursor):
        def fetchall(self):
            if self.calls and "information_schema.columns" in self.calls[-1][0].lower():
                return [(column,) for column in sorted(ROLLING_COLUMNS)]
            return []

        def fetchone(self):
            if self.calls and self.calls[-1][0].lower().startswith("select count(*)"):
                return (0,)
            return None

    class _SchemaConnection(_RecordingConnection):
        def __init__(self) -> None:
            super().__init__()
            self.cursor_obj = _SchemaCursor()

    connection = _SchemaConnection()
    manager = RollingRecentManager(Settings(), connection_factory=lambda: connection)
    manager.ensure_schema()

    statements = [" ".join(str(sql).split()).lower() for sql, _ in connection.cursor_obj.calls]
    create_view = next(i for i, sql in enumerate(statements) if sql.startswith("create view vrecent"))
    cleanup_delete = next(
        i for i, sql in enumerate(statements) if sql.startswith("delete from recent where dtom <")
    )
    validate_select = next(
        i for i, sql in enumerate(statements) if sql.startswith("select count(*) from recent where dtom <")
    )
    assert create_view < cleanup_delete < validate_select
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_grafana_continuous_dose_queries_use_vrecent_not_measurement():
    dashboards = build_dashboard_payloads()
    saw_time_series = False
    for dashboard in dashboards:
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                sql = str(target.get("rawSql") or "")
                if panel.get("type") == "timeseries":
                    saw_time_series = True
                    assert "FROM vrecent" in sql or "FROM recent" in sql
                    assert "FROM measurement" not in sql
    assert saw_time_series is True


def test_alarm_panel_remains_on_historical_alarm_table():
    for dashboard in build_dashboard_payloads()[2:]:
        panel = next(
            item for item in dashboard["panels"]
            if item.get("title") == "Alarm Terbaru · 24 Jam"
        )
        sql = panel["targets"][0]["rawSql"]
        assert "FROM alarm" in sql
        assert "INTERVAL 24 HOUR" in sql


def test_remote_source_legacy_vrecent_contract_is_unchanged():
    for field in (
        "lastrate", "minrate", "maxrate", "avgrate", "lastdose", "mindose",
        "maxdose", "avgdose", "lastmea", "lastmeasec", "meacount", "firstmea",
    ):
        assert field in LIVE_KEYS
