from datetime import datetime

import pytest

from radmon.audit import AuditTrail
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.security import Role, SecurityStore


class AppLogger:
    def __init__(self):
        self.messages = []

    def record_applog(self, message, at=None):
        self.messages.append(message)


class FakeRemote:
    def __init__(self, *, succeed=True):
        self.succeed = succeed
        self.calls = []

    def ack_legacy(self, serid, dtoa, *, action, pic, note, at):
        self.calls.append((serid, dtoa, action, pic, note, at))
        return self.succeed


def _alarm_row():
    return {
        "serid": 5201,
        "dtoa": datetime(2026, 9, 8, 14, 0, 0),
        "lvl": 2,
        "mvalue": 26.1,
        "thvalue": 25.0,
        "nhit": 3,
        "i_op": None,
        "pic": None,
        "note": None,
    }


def test_mirror_maps_legacy_alarm_fields(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    mirror = RemoteAlarmMirror(store)
    assert mirror.mirror("gd52", [_alarm_row()]) == 1

    rows = mirror.list_alarms()
    assert rows[0]["source_id"] == "gd52"
    assert rows[0]["serid"] == 5201
    assert rows[0]["level"] == "ALARM"
    assert rows[0]["measured_value"] == 26.1
    assert rows[0]["threshold"] == 25.0
    assert rows[0]["hit_count"] == 3
    assert rows[0]["acknowledged_at"] is None


def test_operator_ack_requires_pin_and_writes_through_before_marking_local(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = store.authenticate("op", "Password123!")
    mirror = RemoteAlarmMirror(store)
    mirror.mirror("gd52", [_alarm_row()])
    remote = FakeRemote(succeed=True)
    audit = AuditTrail(store, AppLogger())
    service = AlarmControlService(
        store,
        mirror,
        audit,
        remote_factory=lambda source_id: remote,
    )

    alarm = service.ack(
        identity,
        "1357",
        "gd52",
        5201,
        datetime(2026, 9, 8, 14, 0, 0),
        action="Confirm to Location",
        pic="Budi",
        note="Sudah dikonfirmasi",
    )

    assert remote.calls and remote.calls[0][0:5] == (
        5201,
        datetime(2026, 9, 8, 14, 0, 0),
        "Confirm to Location",
        "Budi",
        "Sudah dikonfirmasi",
    )
    assert alarm["acknowledged_at"] is not None
    assert alarm["pic"] == "Budi"
    assert alarm["action"] == "Confirm to Location"


def test_failed_remote_ack_does_not_mark_local_alarm(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = store.authenticate("op", "Password123!")
    mirror = RemoteAlarmMirror(store)
    event_time = datetime(2026, 9, 8, 14, 0, 0)
    mirror.mirror("gd52", [_alarm_row()])
    service = AlarmControlService(
        store,
        mirror,
        AuditTrail(store),
        remote_factory=lambda source_id: FakeRemote(succeed=False),
    )

    with pytest.raises(RuntimeError):
        service.ack(
            identity, "1357", "gd52", 5201, event_time,
            action="Confirm to Location", pic="Budi", note="x"
        )

    alarm = mirror.get("gd52", 5201, event_time)
    assert alarm["acknowledged_at"] is None


def test_viewer_cannot_ack_even_with_correct_pin(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("view", "Viewer", Role.VIEWER, "Password123!", "9999")
    identity = store.authenticate("view", "Password123!")
    mirror = RemoteAlarmMirror(store)
    event_time = datetime(2026, 9, 8, 14, 0, 0)
    mirror.mirror("gd52", [_alarm_row()])
    service = AlarmControlService(
        store,
        mirror,
        AuditTrail(store),
        remote_factory=lambda source_id: FakeRemote(),
    )

    with pytest.raises(Exception):
        service.ack(
            identity, "9999", "gd52", 5201, event_time,
            action="Confirm to Location", pic="Viewer", note="x"
        )
