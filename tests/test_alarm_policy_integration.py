from datetime import datetime
import inspect

from radmon.lan import LanAggregator, LanSource, RemoteMariaDBSource
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror


def test_source_silence_sql_sets_i_flag_and_preserves_ack():
    class Cursor:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()): self.sql, self.params = sql, params

    class Connection:
        def __init__(self): self.c = Cursor()
        def cursor(self): return self.c
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    db = Connection()
    remote = RemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: db,
    )
    remote.respond_alarm(
        5201,
        datetime(2026, 9, 11, 10, 0),
        action="Suppressed",
        pic="PIC",
        note="Calibration",
        at=datetime(2026, 9, 11, 10, 1),
    )
    sql = " ".join(db.c.sql.lower().split())
    assert "i_flag = 1" in sql
    assert "ack =" not in sql


def test_final_lan_live_cycle_exposes_alarm_policy_hook():
    source = inspect.getsource(LanAggregator.run_live_once)
    assert "alarm_policy" in source
    assert "process_cycle" in source


def test_raw_alarm_mirror_exposes_policy_annotation_helpers():
    assert hasattr(RemoteAlarmMirror, "annotate_policy")
    assert hasattr(RemoteAlarmMirror, "pending_source_silences")
    assert hasattr(RemoteAlarmMirror, "mark_source_silence_result")


def test_alarm_control_exposes_policy_event_response():
    assert hasattr(AlarmControlService, "respond_policy_event")
    assert hasattr(AlarmControlService, "silence_source_row")
