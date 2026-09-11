from datetime import datetime, timedelta, timezone

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.security import SecurityStore


def test_get_policy_keeps_current_underlying_dose_and_suppression_details(tmp_path):
    now = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security), now=lambda: now)
    store.start_suppression(
        5201,
        now,
        now + timedelta(minutes=15),
        True,
        "Operator A",
        "Calibration",
        "op",
    )
    policy.evaluate_live({
        "serid": 5201,
        "dtom": now,
        "doserate": 170.0,
        "warnlevel": 100.0,
        "alarmlevel": 150.0,
    })

    snapshot = policy.get_policy(5201)
    assert snapshot["policy_state"] == "SUPPRESSED"
    assert snapshot["underlying_dose_status"] == "ALARM"
    assert snapshot["measured_value"] == 170.0
    assert snapshot["suppression_pic"] == "Operator A"
    assert snapshot["suppression_reason"] == "Calibration"
    assert snapshot["suppression_expires_at"] == now + timedelta(minutes=15)
