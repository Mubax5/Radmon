from datetime import datetime, timedelta, timezone

import pytest

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.lan import _retry_source_silences
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.security import Role, SecurityStore


def _surfaced_source_alarm(policy, mirror, source_id, at):
    event = policy.evaluate_live({
        "serid": 5201, "dtom": at, "doserate": 170.0,
        "warnlevel": 100.0, "alarmlevel": 150.0,
    }, source_id=source_id)
    mirror.mirror(source_id, [{"serid": 5201, "_remote_serid": 1, "dtoa": at, "lvl": 2}])
    observed = policy.observe_source_alarm(source_id, {
        "serid": 5201, "_remote_serid": 1, "dtoa": at, "lvl": 2,
    })
    assert observed["decision"] == "SURFACED"
    return event["active_event_id"]


def test_operator_response_dispatches_production_surfaced_source_alarm(tmp_path):
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = security.authenticate("operator", "Password123!")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit, now=lambda: at)
    mirror = RemoteAlarmMirror(security)
    event_id = _surfaced_source_alarm(policy, mirror, "source-a", at)

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: remote, now=lambda: at)
    control.policy_store = store
    control.policy = policy

    control.respond_policy_event(identity, "1357", event_id, action="Konfirmasi", pic="Budi", reason="Periksa")

    assert remote.calls == 1
    assert store.get_event(event_id).status == "RESPONDED"
    with security._connection() as db:
        assert db.execute(
            "SELECT source_response_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, at.isoformat()),
        ).fetchone()[0] == "CONFIRMED"


def test_failed_remote_response_keeps_production_surfaced_event_active(tmp_path):
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = security.authenticate("operator", "Password123!")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit, now=lambda: at)
    mirror = RemoteAlarmMirror(security)
    event_id = _surfaced_source_alarm(policy, mirror, "source-a", at)

    class Remote:
        def respond_alarm(self, *args, **kwargs):
            return False

    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: Remote(), now=lambda: at)
    control.policy_store = store
    control.policy = policy
    with pytest.raises(RuntimeError, match="tetap aktif"):
        control.respond_policy_event(identity, "1357", event_id, action="Konfirmasi", pic="Budi", reason="Periksa")

    assert store.get_event(event_id).status == "ACTIVE"
    with security._connection() as db:
        assert db.execute(
            "SELECT source_response_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, at.isoformat()),
        ).fetchone()[0] == "FAILED"


def test_source_linked_event_without_mirror_row_stays_active(tmp_path):
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = security.authenticate("operator", "Password123!")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit, now=lambda: at)
    mirror = RemoteAlarmMirror(security)
    event = store.create_policy_event(
        event_key="alarm:response-no-source-row", serid=5201, kind="ALARM", origin="central_policy",
        surfaced_at=at, status="ACTIVE", source_id="source-a",
    )
    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: None, now=lambda: at)
    control.policy_store = store
    control.policy = policy

    with pytest.raises(RuntimeError, match="tidak ada baris sumber"):
        control.respond_policy_event(identity, "1357", event.event_id, action="Konfirmasi", pic="Budi", reason="Periksa")

    assert store.get_event(event.event_id).status == "ACTIVE"


def test_stale_normal_response_claim_reconciles_from_fresh_handled_source_without_duplicate_write(tmp_path):
    at = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    clock = [at]
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit, now=lambda: clock[0])
    mirror = RemoteAlarmMirror(security)
    event_id = _surfaced_source_alarm(policy, mirror, "source-a", at)
    assert store.claim_source_response("source-a", 5201, at, claimed_at=at) == 1

    # The process crashed after claiming the external MariaDB write. A later
    # source observation says the row is already inactive, but cannot prove who
    # made that write, so reconciliation must not retry or close the event.
    clock[0] += timedelta(seconds=61)
    policy.restore_and_reconcile_current_state()
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": at, "lvl": 2, "i_flag": 1}])

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    _retry_source_silences(
        type("Aggregator", (), {"remote_factory": lambda self, source: remote})(),
        type("Source", (), {"source_id": "source-a"})(), policy,
    )

    assert remote.calls == 0
    assert store.get_event(event_id).status == "ACTIVE"
    with security._connection() as db:
        assert db.execute(
            "SELECT source_response_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, at.isoformat()),
        ).fetchone()[0] == "RECONCILED"
    actions = [item["action"] for item in audit.list_events()]
    assert "ALARM_POLICY_SOURCE_RESPONSE_RECONCILING" in actions
    assert "ALARM_POLICY_SOURCE_RESPONSE_RECONCILED" in actions
