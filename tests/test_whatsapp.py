from datetime import datetime

from radmon.remote_alarm import RemoteAlarmMirror
from radmon.security import SecurityStore
from radmon.whatsapp import WhatsAppAlarmDispatcher


class Sender:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        if self.fail:
            raise RuntimeError("send failed")


def make_alarm(mirror):
    mirror.mirror("gd52", [{
        "serid": 5201,
        "dtoa": datetime(2026, 9, 8, 14, 0, 0),
        "lvl": 2,
        "mvalue": 26.1,
        "thvalue": 25.0,
        "nhit": 3,
        "i_op": None,
        "pic": None,
        "note": None,
    }])


def test_dispatcher_sends_once_and_marks_notification(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    mirror = RemoteAlarmMirror(store)
    make_alarm(mirror)
    sender = Sender()
    dispatcher = WhatsAppAlarmDispatcher(mirror, sender)

    assert dispatcher.run_once() == 1
    assert dispatcher.run_once() == 0
    assert len(sender.messages) == 1
    assert "gd52" in sender.messages[0]
    assert "5201" in sender.messages[0]
    assert "26.10" in sender.messages[0]
    assert "25.00" in sender.messages[0]


def test_failed_send_is_not_marked_and_retries_next_run(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    mirror = RemoteAlarmMirror(store)
    make_alarm(mirror)
    sender = Sender(fail=True)
    dispatcher = WhatsAppAlarmDispatcher(mirror, sender)

    assert dispatcher.run_once() == 0
    sender.fail = False
    assert dispatcher.run_once() == 1
    assert len(sender.messages) == 2
