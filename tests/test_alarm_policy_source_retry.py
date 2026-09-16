from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.lan import _retry_source_silences
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.security import SecurityStore


def test_failed_source_silence_recovers_without_second_operator_event(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security), now=lambda: clock[0])
    mirror = RemoteAlarmMirror(security)
    event_time = clock[0]
    mirror.mirror("source-a", [{
        "serid": 5201,
        "_remote_serid": 1,
        "dtoa": event_time,
        "lvl": 2,
        "mvalue": 170.0,
        "thvalue": 150.0,
        "nhit": 1,
    }])
    event = store.create_policy_event(
        event_key="suppressed:retry-session",
        serid=5201,
        kind="SUPPRESSED",
        origin="central_policy",
        surfaced_at=event_time,
        measured_value=170.0,
        threshold=150.0,
        status="AUTO_SILENCED",
    )
    store.annotate_raw_alarm(
        "source-a",
        5201,
        event_time,
        policy_decision="SUPPRESSED",
        operator_visible=False,
        policy_event_id=event.event_id,
        source_silence_state="PENDING",
        source_silence_retry_at=clock[0],
    )

    class Remote:
        def __init__(self):
            self.calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return self.calls >= 2

    remote = Remote()
    aggregator = SimpleNamespace(remote_factory=lambda source: remote)
    source = SimpleNamespace(source_id="source-a")

    _retry_source_silences(aggregator, source, policy)
    pending = store.pending_source_silences(
        "source-a", at=clock[0] + timedelta(seconds=5), limit=25
    )
    assert len(pending) == 1
    assert pending[0]["source_silence_state"] == "FAILED"

    clock[0] += timedelta(seconds=5)
    _retry_source_silences(aggregator, source, policy)
    with security._connection() as db:
        state = db.execute(
            "SELECT source_silence_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, event_time.isoformat()),
        ).fetchone()[0]
    assert state == "CONFIRMED"
    assert len(store.list_policy_events(serid=5201)) == 1


def test_stale_dispatch_claim_is_reconciled_from_a_fresh_source_row_without_duplicate_write(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    audit = AuditTrail(security)
    policy = AlarmPolicyService(store, audit, now=lambda: clock[0])
    mirror = RemoteAlarmMirror(security)
    event_time = clock[0]
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": event_time, "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, event_time, policy_decision="SUPPRESSED",
        source_silence_state="PENDING", source_silence_retry_at=clock[0],
    )
    assert store.claim_source_silence("source-a", 5201, event_time, claimed_at=clock[0]) == 1

    # This is the next source observation after a process crashed mid-dispatch.
    # i_flag proves the source row is no longer active, but not who wrote it.
    clock[0] += timedelta(seconds=61)
    policy.restore_and_reconcile_current_state()
    mirror.mirror("source-a", [{
        "serid": 5201, "_remote_serid": 1, "dtoa": event_time, "lvl": 2, "i_flag": 1,
    }])

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    _retry_source_silences(
        SimpleNamespace(remote_factory=lambda source: remote), SimpleNamespace(source_id="source-a"), policy,
    )

    with security._connection() as db:
        state = db.execute(
            "SELECT source_silence_state FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("source-a", 5201, event_time.isoformat()),
        ).fetchone()[0]
    assert state == "RECONCILED"
    assert remote.calls == 0
    assert any(item["action"] == "SUPPRESSION_SOURCE_SILENCE_RECONCILED" for item in audit.list_events())


def test_stale_dispatch_claim_retries_only_after_a_fresh_source_row_is_still_active(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security), now=lambda: clock[0])
    mirror = RemoteAlarmMirror(security)
    event_time = clock[0]
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": event_time, "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, event_time, policy_decision="SUPPRESSED",
        source_silence_state="PENDING", source_silence_retry_at=clock[0],
    )
    store.claim_source_silence("source-a", 5201, event_time, claimed_at=clock[0])
    clock[0] += timedelta(seconds=61)
    policy.restore_and_reconcile_current_state()
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": event_time, "lvl": 2, "i_flag": 0}])

    class Remote:
        calls = 0

        def respond_alarm(self, *args, **kwargs):
            self.calls += 1
            return True

    remote = Remote()
    _retry_source_silences(
        SimpleNamespace(remote_factory=lambda source: remote), SimpleNamespace(source_id="source-a"), policy,
    )

    assert remote.calls == 1
    assert store.pending_source_silences("source-a", at=clock[0]) == []


def test_cancelled_stale_claim_is_audited_as_cancelled_not_reconciled_or_retryable(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    audit = AuditTrail(security)
    policy = AlarmPolicyService(store, audit, now=lambda: clock[0])
    mirror = RemoteAlarmMirror(security)
    event_time = clock[0]
    suppression = store.start_suppression(5201, clock[0], clock[0] + timedelta(minutes=15), False, "Budi", "Kalibrasi", "operator")
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": event_time, "lvl": 2}])
    store.annotate_raw_alarm(
        "source-a", 5201, event_time, policy_decision="SUPPRESSED",
        suppression_id=suppression.suppression_id, source_silence_state="PENDING", source_silence_retry_at=clock[0],
    )
    assert store.claim_source_silence("source-a", 5201, event_time, claimed_at=clock[0]) == 1
    store.end_suppression(suppression.suppression_id, clock[0], "CANCELLED: selesai", cancel_source_silences=True)
    clock[0] += timedelta(seconds=61)
    policy.restore_and_reconcile_current_state()
    mirror.mirror("source-a", [{"serid": 5201, "_remote_serid": 1, "dtoa": event_time, "lvl": 2, "i_flag": 0}])

    _retry_source_silences(
        SimpleNamespace(remote_factory=lambda source: None), SimpleNamespace(source_id="source-a"), policy,
    )

    events = audit.list_events()
    assert any(item["action"] == "SUPPRESSION_SOURCE_SILENCE_CANCELLED" for item in events)
    assert not any(
        item["action"] == "SUPPRESSION_SOURCE_SILENCE_RECONCILED" and "retry is authorized" in str(item["reason"])
        for item in events
    )
