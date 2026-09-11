from datetime import datetime, timezone

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.security import SecurityStore
from radmon.whatsapp import WhatsAppAlarmDispatcher


class Sender:
    def __init__(self): self.messages = []
    def send(self, message): self.messages.append(message)


def fixture(tmp_path):
    now = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security), now=lambda: now)
    sender = Sender()
    dispatcher = WhatsAppAlarmDispatcher(policy, sender, now=lambda: now)
    return now, store, policy, sender, dispatcher


def test_suppressed_and_responded_events_never_notify(tmp_path):
    now, store, policy, sender, dispatcher = fixture(tmp_path)
    store.create_policy_event(
        event_key="suppressed:s1", serid=5201, kind="SUPPRESSED",
        origin="central_policy", surfaced_at=now, status="AUTO_SILENCED",
    )
    event = store.create_policy_event(
        event_key="alarm:responded", serid=5201, kind="ALARM",
        origin="central_policy", surfaced_at=now, status="ACTIVE",
    )
    store.respond_event(event.event_id, now, "PIC", "Confirm", "checked")
    assert dispatcher.run_once() == 0
    assert sender.messages == []


def test_active_alarm_notifies_once_across_dispatcher_restart(tmp_path):
    now, store, policy, sender, dispatcher = fixture(tmp_path)
    store.create_policy_event(
        event_key="alarm:a2", serid=5201, kind="ALARM", origin="central_policy",
        surfaced_at=now, measured_value=170.0, threshold=150.0,
        status="ACTIVE", trigger_index=2, source_id="gd52",
    )
    assert dispatcher.run_once() == 1
    restarted = WhatsAppAlarmDispatcher(policy, sender, now=lambda: now)
    assert restarted.run_once() == 0
    assert len(sender.messages) == 1
    assert "#2" in sender.messages[0]


def test_restore_gate_blocks_notification_until_first_live_cycle(tmp_path):
    now, store, policy, sender, dispatcher = fixture(tmp_path)
    store.create_policy_event(
        event_key="alarm:old", serid=5201, kind="ALARM", origin="central_policy",
        surfaced_at=now, status="ACTIVE",
    )
    policy.restore_and_reconcile_current_state()
    assert dispatcher.run_once() == 0
    policy.process_cycle("gd52", [{
        "serid": 5202, "dtom": now, "doserate": 10.0,
        "warnlevel": 100.0, "alarmlevel": 150.0,
    }], [])
    assert dispatcher.run_once() == 1
