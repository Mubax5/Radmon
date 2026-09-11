from datetime import datetime, timedelta, timezone
import pytest

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.alarm_suppression import AlarmSuppressionService
from radmon.audit import AuditTrail
from radmon.security import Role, SecurityStore


def make(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db", now=lambda: clock[0])
    password = "A" * 12
    pin = "1" * 4
    security.create_user("admin", "Administrator", Role.ADMINISTRATOR, password, pin)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security), now=lambda: clock[0])
    service = AlarmSuppressionService(security, store, policy, AuditTrail(security), now=lambda: clock[0])
    return clock, security, store, policy, service, password, pin


def test_suppression_requires_duration_pic_reason_and_permission(tmp_path):
    clock, security, store, policy, service, password, pin = make(tmp_path)
    admin = security.authenticate("admin", password)
    with pytest.raises(ValueError):
        service.start(admin, pin, 5201, 59, "PIC", "Calibration", True)
    with pytest.raises(ValueError):
        service.start(admin, pin, 5201, 900, "", "Calibration", True)
    with pytest.raises(ValueError):
        service.start(admin, pin, 5201, 900, "PIC", "", True)


def test_suppression_creates_exactly_one_event_for_many_high_cycles(tmp_path):
    clock, security, store, policy, service, password, pin = make(tmp_path)
    admin = security.authenticate("admin", password)
    session = service.start(admin, pin, 5201, 900, "PIC", "Calibration", True)
    for second in range(20):
        policy.evaluate_live({
            "serid": 5201,
            "dtom": clock[0] + timedelta(seconds=second),
            "doserate": 170.0,
            "warnlevel": 100.0,
            "alarmlevel": 150.0,
        })
    events = [e for e in store.list_policy_events(serid=5201) if e.kind == "SUPPRESSED"]
    assert len(events) == 1
    assert events[0].suppression_id == session["suppression_id"]
    assert store.get_state(5201).trigger_count == 0


def test_auto_resume_requires_actual_normal_not_alert(tmp_path):
    clock, security, store, policy, service, password, pin = make(tmp_path)
    admin = security.authenticate("admin", password)
    service.start(admin, pin, 5201, 900, "PIC", "Calibration", True)
    policy.evaluate_live({"serid": 5201, "dtom": clock[0], "doserate": 120.0, "warnlevel": 100.0, "alarmlevel": 150.0})
    assert store.active_suppression(5201) is not None
    policy.evaluate_live({"serid": 5201, "dtom": clock[0], "doserate": 99.0, "warnlevel": 100.0, "alarmlevel": 150.0})
    assert store.active_suppression(5201) is None


def test_expiry_while_high_surfaces_fresh_one_unless_locked(tmp_path):
    clock, security, store, policy, service, password, pin = make(tmp_path)
    admin = security.authenticate("admin", password)
    service.start(admin, pin, 5201, 60, "PIC", "Calibration", False)
    policy.evaluate_live({"serid": 5201, "dtom": clock[0], "doserate": 170.0, "warnlevel": 100.0, "alarmlevel": 150.0})
    clock[0] += timedelta(seconds=61)
    snap = policy.evaluate_live({"serid": 5201, "dtom": clock[0], "doserate": 170.0, "warnlevel": 100.0, "alarmlevel": 150.0})
    assert snap["policy_state"] == "ALARM"
    assert snap["trigger_count"] == 1


def test_start_clears_unlocked_burst_but_preserves_retrigger_lock(tmp_path):
    clock, security, store, policy, service, password, pin = make(tmp_path)
    admin = security.authenticate("admin", password)
    first = policy.evaluate_live({"serid": 5201, "dtom": clock[0], "doserate": 170.0, "warnlevel": 100.0, "alarmlevel": 150.0})
    policy.mark_event_responded(first["active_event_id"], clock[0], "PIC", "Confirm", "checked")
    assert store.get_state(5201).trigger_count == 1
    service.start(admin, pin, 5201, 300, "PIC", "Calibration", False)
    state = store.get_state(5201)
    assert state.trigger_count == 0
    assert state.retrigger_locked is False
