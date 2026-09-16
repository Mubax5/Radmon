from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.security import SecurityStore


def test_policy_schema_is_additive_and_idempotent(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    store.ensure_schema()
    store.ensure_schema()
    with security._connection() as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"alarm_policy_state", "alarm_suppression", "alarm_policy_event"} <= names
    with security._connection() as db:
        assert "ended_by" in {row[1] for row in db.execute("PRAGMA table_info(alarm_suppression)")}


def test_policy_schema_adds_end_actor_to_an_installed_suppression_table(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    with security._connection() as db:
        db.execute("""CREATE TABLE alarm_suppression (
            suppression_id TEXT PRIMARY KEY, serid INTEGER NOT NULL, started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, auto_resume_on_normal INTEGER NOT NULL, pic TEXT NOT NULL,
            reason TEXT NOT NULL, started_by TEXT NOT NULL, ended_at TEXT, ended_reason TEXT,
            first_suppressed_alarm_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
    AlarmPolicyStore(security)
    with security._connection() as db:
        assert "ended_by" in {row[1] for row in db.execute("PRAGMA table_info(alarm_suppression)")}


def test_policy_schema_end_actor_migration_is_concurrent_and_idempotent(tmp_path):
    path = tmp_path / "security.db"
    security = SecurityStore(path)
    with security._connection() as db:
        db.execute("""CREATE TABLE alarm_suppression (
            suppression_id TEXT PRIMARY KEY, serid INTEGER NOT NULL, started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, auto_resume_on_normal INTEGER NOT NULL, pic TEXT NOT NULL,
            reason TEXT NOT NULL, started_by TEXT NOT NULL, ended_at TEXT, ended_reason TEXT,
            first_suppressed_alarm_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")

    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda _: AlarmPolicyStore(SecurityStore(path)), range(16)))

    with security._connection() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(alarm_suppression)")]
    assert columns.count("ended_by") == 1


def test_policy_schema_end_actor_migration_uses_an_immediate_transaction(tmp_path):
    path = tmp_path / "security.db"
    security = SecurityStore(path)
    with security._connection() as db:
        db.execute("""CREATE TABLE alarm_suppression (
            suppression_id TEXT PRIMARY KEY, serid INTEGER NOT NULL, started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, auto_resume_on_normal INTEGER NOT NULL, pic TEXT NOT NULL,
            reason TEXT NOT NULL, started_by TEXT NOT NULL, ended_at TEXT, ended_reason TEXT,
            first_suppressed_alarm_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")

    class TransactionCheckingConnection(sqlite3.Connection):
        immediate_started = False

        def execute(self, sql, parameters=()):
            normalized = str(sql).strip().upper()
            if normalized == "BEGIN IMMEDIATE":
                type(self).immediate_started = True
            if normalized.startswith("ALTER TABLE ALARM_SUPPRESSION ADD COLUMN ENDED_BY"):
                assert type(self).immediate_started
            return super().execute(sql, parameters)

    original_connection = security._connection
    security._connection = lambda: sqlite3.connect(path, factory=TransactionCheckingConnection)
    try:
        AlarmPolicyStore(security)
    finally:
        security._connection = original_connection


def test_one_active_suppression_per_detector_is_persistence_enforced(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    now = datetime(2026, 9, 11, 10, 0, 0)
    store.start_suppression(5201, now, now + timedelta(minutes=15), True, "PIC A", "Calibration", "op")
    with pytest.raises(sqlite3.IntegrityError):
        store.start_suppression(5201, now, now + timedelta(minutes=30), False, "PIC B", "Maintenance", "op")


def test_only_one_suppressed_event_can_exist_per_suppression(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    now = datetime(2026, 9, 11, 10, 0, 0)
    suppression = store.start_suppression(5201, now, now + timedelta(minutes=15), True, "PIC A", "Calibration", "op")
    first = store.create_policy_event(
        event_key=f"suppressed:{suppression.suppression_id}", serid=5201,
        kind="SUPPRESSED", origin="central_policy", surfaced_at=now,
        measured_value=160.0, threshold=150.0,
        suppression_id=suppression.suppression_id, status="AUTO_SILENCED",
    )
    second = store.create_policy_event(
        event_key=f"suppressed:{suppression.suppression_id}", serid=5201,
        kind="SUPPRESSED", origin="central_policy", surfaced_at=now,
        measured_value=170.0, threshold=150.0,
        suppression_id=suppression.suppression_id, status="AUTO_SILENCED",
    )
    assert second.event_id == first.event_id
    assert len(store.list_policy_events(serid=5201)) == 1
