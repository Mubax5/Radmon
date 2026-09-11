from datetime import datetime, timedelta
from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.security import SecurityStore


def row(at, dose):
    return {"serid": 5201, "dtom": at, "doserate": dose, "warnlevel": 100.0, "alarmlevel": 150.0}


def test_three_alarm_rule_and_normal_only_reset(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    service = AlarmPolicyService(store, AuditTrail(security))
    t0 = datetime(2026, 9, 11, 10, 0, 0)

    first = service.evaluate_live(row(t0, 151.0))
    assert first["policy_state"] == "ALARM"
    assert first["trigger_count"] == 1
    service.mark_event_responded(first["active_event_id"], t0 + timedelta(seconds=20), "PIC", "Confirm", "checked")

    second = service.evaluate_live(row(t0 + timedelta(minutes=3), 160.0))
    assert second["trigger_count"] == 2
    service.mark_event_responded(second["active_event_id"], t0 + timedelta(minutes=3, seconds=20), "PIC", "Confirm", "checked")

    third = service.evaluate_live(row(t0 + timedelta(minutes=4), 170.0))
    assert third["trigger_count"] == 3
    assert third["retrigger_locked"] is True
    service.mark_event_responded(third["active_event_id"], t0 + timedelta(minutes=4, seconds=20), "PIC", "Confirm", "checked")

    blocked = service.evaluate_live(row(t0 + timedelta(minutes=6), 180.0))
    assert blocked["trigger_count"] == 3
    assert blocked["retrigger_locked"] is True
    assert blocked["active_event_id"] is None

    alert = service.evaluate_live(row(t0 + timedelta(minutes=7), 120.0))
    assert alert["retrigger_locked"] is True

    normal = service.evaluate_live(row(t0 + timedelta(minutes=8), 99.0))
    assert normal["trigger_count"] == 0
    assert normal["retrigger_locked"] is False


def test_five_minute_window_is_anchored_to_first_alarm(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    service = AlarmPolicyService(AlarmPolicyStore(security), AuditTrail(security))
    t0 = datetime(2026, 9, 11, 10, 0, 0)
    a1 = service.evaluate_live(row(t0, 151.0))
    service.mark_event_responded(a1["active_event_id"], t0, "PIC", "Confirm", "x")
    a2 = service.evaluate_live(row(t0 + timedelta(minutes=3), 151.0))
    assert a2["trigger_count"] == 2
    service.mark_event_responded(a2["active_event_id"], t0, "PIC", "Confirm", "x")
    same_boundary = service.evaluate_live(row(t0 + timedelta(minutes=5), 151.0))
    assert same_boundary["trigger_count"] == 3


def test_after_window_next_alarm_is_new_one_when_not_locked(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    service = AlarmPolicyService(AlarmPolicyStore(security), AuditTrail(security))
    t0 = datetime(2026, 9, 11, 10, 0, 0)
    a1 = service.evaluate_live(row(t0, 151.0))
    service.mark_event_responded(a1["active_event_id"], t0, "PIC", "Confirm", "x")
    a2 = service.evaluate_live(row(t0 + timedelta(minutes=3), 151.0))
    service.mark_event_responded(a2["active_event_id"], t0, "PIC", "Confirm", "x")
    new_burst = service.evaluate_live(row(t0 + timedelta(minutes=7), 151.0))
    assert new_burst["trigger_count"] == 1
