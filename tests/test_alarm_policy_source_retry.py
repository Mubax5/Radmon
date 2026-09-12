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
