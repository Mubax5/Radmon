from datetime import datetime, timedelta, timezone
import threading

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.alarm_suppression import AlarmSuppressionService
from radmon.audit import AuditTrail
from radmon.security import Role, SecurityStore


def high(at, serid=5201):
    return {"serid": serid, "dtom": at, "doserate": 170.0, "warnlevel": 100.0, "alarmlevel": 150.0}


def test_simultaneous_first_high_creates_one_active_alarm(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security))
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(policy.evaluate_live(high(at)))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)

    events = [e for e in store.list_policy_events(serid=5201) if e.kind == "ALARM" and e.status == "ACTIVE"]
    assert len(events) == 1
    assert store.get_state(5201).trigger_count == 1


def test_parallel_suppression_start_allows_only_one_active_session(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = security.authenticate("op", "Password123!")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security))
    service = AlarmSuppressionService(security, store, policy, AuditTrail(security))
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        barrier.wait()
        try:
            service.start(identity, "1357", 5201, 300, "PIC", "Calibration", True)
            outcomes.append("ok")
        except RuntimeError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)
    assert sorted(outcomes) == ["conflict", "ok"]
    assert len(store.list_suppressions(active_only=True)) == 1


def test_policy_suppression_and_notification_state_survive_restart(tmp_path):
    db_path = tmp_path / "security.db"
    security = SecurityStore(db_path)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security))
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    snap = policy.evaluate_live(high(at))
    policy.mark_notification_sent(snap["active_event_id"], at)
    store.start_suppression(5202, at, at + timedelta(minutes=15), True, "PIC", "Calibration", "op")

    reopened = AlarmPolicyStore(SecurityStore(db_path))
    assert reopened.get_state(5201).trigger_count == 1
    event = reopened.get_event(snap["active_event_id"])
    assert event.notification_sent_at == at
    assert reopened.active_suppression(5202) is not None


def test_historical_seed_alarm_is_evidence_not_notification_candidate(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security))
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    policy.process_cycle("gd52", [], [{
        "serid": 5201, "_remote_serid": 1, "dtoa": at, "lvl": 2,
        "mvalue": 170.0, "thvalue": 150.0, "_historical_seed": True,
    }])
    assert policy.list_events(notify_pending_only=True) == []


def test_store_start_suppression_can_return_inside_existing_detector_transaction(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    with store.detector_transaction(5201) as tx:
        item = store.start_suppression(
            5201, at, at + timedelta(minutes=5), True, "PIC", "Calibration", "op",
            connection=tx.connection,
        )
        assert item.serid == 5201
