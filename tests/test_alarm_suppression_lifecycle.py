from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace

import pytest

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.alarm_suppression import AlarmSuppressionService
from radmon.audit import AuditTrail
from radmon.lan import _retry_source_silences
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.security import Role, SecurityStore


def make(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db", now=lambda: clock[0])
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit, now=lambda: clock[0])
    service = AlarmSuppressionService(security, store, policy, audit, now=lambda: clock[0])
    return clock, security, store, policy, service, audit


def test_cancel_is_idempotent_audited_and_preserves_lifecycle_event(tmp_path):
    clock, security, store, _, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)

    cancelled = service.cancel(identity, "1357", started["suppression_id"], "Kalibrasi selesai")
    repeated = service.cancel(identity, "1357", started["suppression_id"], "Kalibrasi selesai")

    assert cancelled["ended_reason"] == "CANCELLED: Kalibrasi selesai"
    assert cancelled["ended_by"] == "operator"
    assert repeated == cancelled
    lifecycle = [event for event in store.list_policy_events(serid=5201) if event.kind == "SUPPRESSION_END"]
    assert len(lifecycle) == 1
    assert lifecycle[0].status == "ENDED"
    assert lifecycle[0].suppression_id == started["suppression_id"]
    assert [item["action"] for item in audit.list_events() if item["action"] == "ALARM_SUPPRESSION_END"] == ["ALARM_SUPPRESSION_END"]


def test_cancel_requires_valid_pin_and_nonempty_reason(tmp_path):
    _, security, _, _, service, _ = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)

    with pytest.raises(ValueError):
        service.cancel(identity, "1357", started["suppression_id"], "")
    with pytest.raises(Exception):
        service.cancel(identity, "0000", started["suppression_id"], "Selesai")


def test_cancel_terminally_stops_failed_source_silence_retry(tmp_path):
    clock, security, store, policy, service, _ = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, clock[0], policy_decision="SUPPRESSED",
        suppression_id=started["suppression_id"], source_silence_state="FAILED",
        source_silence_retry_at=clock[0],
    )
    service.cancel(identity, "1357", started["suppression_id"], "Selesai")

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    _retry_source_silences(SimpleNamespace(remote_factory=lambda source: remote), SimpleNamespace(source_id="source-a"), policy)
    assert remote.calls == 0
    assert store.pending_source_silences("source-a", at=clock[0]) == []


def test_expiry_sweep_ends_due_session_once_without_measurement(tmp_path):
    clock, security, store, _, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 60, "Budi", "Kalibrasi", False)
    clock[0] += timedelta(seconds=61)

    assert service.expire_due() == 1
    assert service.expire_due() == 0
    ended = store.get_suppression(started["suppression_id"])
    assert ended.ended_reason == "EXPIRED"
    assert len([item for item in audit.list_events() if item["action"] == "ALARM_SUPPRESSION_END"]) == 1


def test_cancel_binds_surfaced_source_failure_and_stops_its_retry(tmp_path):
    clock, security, store, policy, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    event = store.create_policy_event(
        event_key="alarm:surface-before-suppression", serid=5201, kind="ALARM", origin="central_policy",
        surfaced_at=clock[0], status="ACTIVE", source_id="source-a",
    )
    store.save_state(type(store.get_state(5201))(
        serid=5201, active_event_id=event.event_id, updated_at=clock[0],
    ))
    store.annotate_raw_alarm(
        "source-a", 5201, clock[0], policy_decision="SURFACED", operator_visible=True,
        policy_event_id=event.event_id,
    )

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return False

    remote = Remote()
    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: remote, now=lambda: clock[0])
    control.policy_store = store
    control.policy = policy
    service.alarm_control = control

    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)
    assert store.pending_source_silences("source-a", at=clock[0] + timedelta(seconds=5))[0]["suppression_id"] == started["suppression_id"]

    service.cancel(identity, "1357", started["suppression_id"], "Selesai")
    _retry_source_silences(SimpleNamespace(remote_factory=lambda source: remote), SimpleNamespace(source_id="source-a"), policy)
    assert remote.calls == 1
    assert store.pending_source_silences("source-a", at=clock[0] + timedelta(hours=1)) == []


def test_cancel_between_retry_read_and_dispatch_prevents_remote_write(tmp_path):
    clock, security, store, policy, service, _ = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, clock[0], policy_decision="SUPPRESSED",
        suppression_id=started["suppression_id"], source_silence_state="PENDING",
        source_silence_retry_at=clock[0],
    )

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    aggregator = SimpleNamespace(
        remote_factory=lambda source: remote,
        before_source_silence_claim=lambda: service.cancel(
            identity, "1357", started["suppression_id"], "Selesai"
        ),
    )
    _retry_source_silences(aggregator, SimpleNamespace(source_id="source-a"), policy)

    assert remote.calls == 0
    assert store.pending_source_silences("source-a", at=clock[0]) == []


def test_cancel_between_initial_dispatch_and_claim_prevents_remote_write(tmp_path):
    clock, security, store, policy, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    event = store.create_policy_event(
        event_key="alarm:initial-dispatch-race", serid=5201, kind="ALARM", origin="central_policy",
        surfaced_at=clock[0], status="ACTIVE", source_id="source-a",
    )
    store.save_state(type(store.get_state(5201))(
        serid=5201, active_event_id=event.event_id, updated_at=clock[0],
    ))
    store.annotate_raw_alarm(
        "source-a", 5201, clock[0], policy_decision="SURFACED", operator_visible=True,
        policy_event_id=event.event_id,
    )

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: remote, now=lambda: clock[0])
    control.policy_store = store
    control.policy = policy
    service.alarm_control = control
    control.before_source_silence_claim = lambda suppression_id: service.cancel(
        identity, "1357", suppression_id, "Operator membatalkan"
    )

    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)

    assert remote.calls == 0
    assert store.get_suppression(started["suppression_id"]).ended_reason == "CANCELLED: Operator membatalkan"


def test_cancel_before_delayed_source_row_bind_prevents_any_retry_dispatch(tmp_path):
    clock, security, store, policy, service, _ = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])

    policy.before_source_silence_bind = lambda: service.cancel(
        identity, "1357", started["suppression_id"], "Selesai sebelum source terlihat"
    )
    observed = policy.observe_source_alarm("source-a", {
        "serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2,
    })
    assert observed["decision"] == "SUPPRESSED"

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    _retry_source_silences(SimpleNamespace(remote_factory=lambda source: remote), SimpleNamespace(source_id="source-a"), policy)

    assert remote.calls == 0
    with security._connection() as db:
        assert db.execute(
            "SELECT source_silence_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, clock[0].isoformat()),
        ).fetchone()[0] == "CANCELLED"


def test_delayed_source_row_keeps_active_policy_event_resolvable_after_suppression(tmp_path):
    clock, security, store, policy, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    event = store.create_policy_event(
        event_key="alarm:delayed-source-row", serid=5201, kind="ALARM", origin="central_policy",
        surfaced_at=clock[0], status="ACTIVE", source_id="source-a",
    )
    store.save_state(type(store.get_state(5201))(
        serid=5201, active_event_id=event.event_id, updated_at=clock[0],
    ))

    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    observed = policy.observe_source_alarm("source-a", {
        "serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2,
    })

    assert observed["decision"] == "SUPPRESSED"
    assert observed["policy_event_id"] == event.event_id
    assert store.get_event(event.event_id).suppression_id == started["suppression_id"]

    class Remote:
        def respond_alarm(self, *args, **kwargs):
            return True

    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: Remote(), now=lambda: clock[0])
    control.policy_store = store
    control.policy = policy
    control.respond_policy_event(identity, "1357", event.event_id, action="Konfirmasi", pic="Budi", reason="Teratasi")

    assert store.get_event(event.event_id).status == "RESPONDED"
    assert store.pending_source_silences("source-a", at=clock[0]) == []


def test_cancelled_failed_silence_uses_normal_response_protocol_for_later_operator_response(tmp_path):
    clock, security, store, policy, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    mirror = RemoteAlarmMirror(security)
    event = store.create_policy_event(
        event_key="alarm:failed-silence-then-manual-response", serid=5201, kind="ALARM",
        origin="central_policy", surfaced_at=clock[0], status="ACTIVE", source_id="source-a",
    )
    store.save_state(type(store.get_state(5201))(
        serid=5201, active_event_id=event.event_id, updated_at=clock[0],
    ))
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, clock[0], policy_decision="SURFACED", operator_visible=True,
        policy_event_id=event.event_id,
    )

    class Remote:
        def __init__(self):
            self.responses = [False, True]

        def respond_alarm(self, *args, **kwargs):
            return self.responses.pop(0)

    remote = Remote()
    control = AlarmControlService(security, mirror, audit, remote_factory=lambda source: remote, now=lambda: clock[0])
    control.policy_store = store
    control.policy = policy
    service.alarm_control = control

    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)
    service.cancel(identity, "1357", started["suppression_id"], "Selesai")
    responded = control.respond_policy_event(
        identity, "1357", event.event_id, action="Konfirmasi", pic="Budi", reason="Teratasi",
    )

    assert responded["status"] == "RESPONDED"
    assert store.get_event(event.event_id).suppression_id == started["suppression_id"]
    with security._connection() as db:
        silence_state, response_state, suppression_id = db.execute(
            "SELECT source_silence_state, source_response_state, suppression_id "
            "FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, clock[0].isoformat()),
        ).fetchone()
    assert suppression_id == started["suppression_id"]
    assert silence_state == "CANCELLED"
    assert response_state == "CONFIRMED"


def test_expiry_during_started_silence_dispatch_is_uncertain_not_confirmed(tmp_path):
    clock, security, store, _, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 60, "Budi", "Kalibrasi", True)
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": clock[0], "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, clock[0], policy_decision="SUPPRESSED",
        suppression_id=started["suppression_id"], source_silence_state="PENDING",
        source_silence_retry_at=clock[0],
    )
    clock[0] += timedelta(seconds=59)

    state, error = store.dispatch_source_silence(
        "source-a", 5201, clock[0] - timedelta(seconds=59), at=clock[0],
        responder=lambda: (clock.__setitem__(0, clock[0] + timedelta(seconds=2)), service.expire_due(), True)[2],
        backoff_seconds=(5,),
    )

    assert error is None
    assert state == "UNCERTAIN"
    assert store.get_suppression(started["suppression_id"]).ended_reason == "EXPIRED"
    with security._connection() as db:
        assert db.execute(
            "SELECT source_silence_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, (clock[0] - timedelta(seconds=61)).isoformat()),
        ).fetchone()[0] == "UNCERTAIN"
    actions = [item["action"] for item in audit.list_events()]
    assert "ALARM_SUPPRESSION_END" in actions
    assert "SUPPRESSION_SOURCE_SILENCE_UNCERTAIN" in actions


def test_cancel_rolls_back_when_durable_audit_fails(tmp_path):
    clock, security, store, policy, service, audit = make(tmp_path)
    identity = security.authenticate("operator", "Password123!")
    started = service.start(identity, "1357", 5201, 900, "Budi", "Kalibrasi", True)

    class FailingAudit:
        fail = True

        def record(self, *args, **kwargs):
            if self.fail:
                raise RuntimeError("audit storage unavailable")
            return audit.record(*args, **kwargs)

    failing_audit = FailingAudit()
    service.audit = failing_audit
    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        service.cancel(identity, "1357", started["suppression_id"], "Selesai")

    assert store.get_suppression(started["suppression_id"]).ended_at is None


def test_security_startup_migrates_legacy_source_silence_attempts_once(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE remote_alarm_state (source_id TEXT, serid INTEGER, event_time TEXT, level TEXT, PRIMARY KEY (source_id, serid, event_time))")

    security = SecurityStore(path)
    SecurityStore(path)
    with security._connection() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(remote_alarm_state)")}

    assert {"source_silence_attempts", "source_silence_claimed_at"} <= columns
