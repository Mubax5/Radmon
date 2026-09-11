from datetime import datetime, timedelta
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
