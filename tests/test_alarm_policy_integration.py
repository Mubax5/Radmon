from datetime import datetime, timedelta
import inspect

import pytest

from radmon.lan import LanAggregator, LanSource, RemoteMariaDBSource
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.security import SecurityStore


def test_source_silence_sql_sets_i_flag_and_preserves_ack():
    class Cursor:
        def __init__(self):
            self.rowcount = 0
            self.sqls = []
            self.row = [5201, datetime(2026, 9, 11, 10, 0), 0, 0, None, None, None]
            self.result = None
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()):
            self.sqls.append(sql)
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("select"):
                self.result = tuple(self.row)
            elif normalized.startswith("update"):
                self.row[3] = 1
                self.row[4] = params[0]
                self.row[5] = params[1]
                self.row[6] = params[2]
                self.rowcount = 1
        def fetchone(self): return self.result

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
    sql = " ".join(next(item for item in db.c.sqls if item.lower().lstrip().startswith("update")).lower().split())
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


def test_remote_clock_offset_samples_source_now_and_rejects_unbounded_skew():
    class Cursor:
        def __init__(self, skew): self.skew, self.calls = skew, 0
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql):
            assert sql == "SELECT NOW()"
            self.calls += 1
        def fetchone(self): return (datetime.now() + self.skew,)

    class Connection:
        def __init__(self, skew): self.cursor_value = Cursor(skew)
        def cursor(self): return self.cursor_value
        def close(self): pass

    connection = Connection(timedelta(seconds=50))
    remote = RemoteMariaDBSource(
        LanSource("gd52", "source", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: connection,
    )
    measured = remote.clock_offset()
    assert measured.total_seconds() == pytest.approx(50, abs=0.2)
    assert connection.cursor_value.calls == 1

    unbounded = RemoteMariaDBSource(
        LanSource("gd52", "source", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: Connection(timedelta(minutes=6)),
    )
    assert unbounded.clock_offset() == timedelta(0)


def test_source_and_threshold_event_correlate_once_without_mutating_source_status(tmp_path):
    security = SecurityStore(tmp_path / "correlation.db")
    mirror = RemoteAlarmMirror(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security))
    at = datetime(2026, 10, 1, 12, 0, 0)
    source_alarm = {"serid": 5702, "_remote_serid": 5702, "dtoa": at,
                    "lvl": 2, "mvalue": 99.99, "thvalue": 25.0, "i_flag": 0}
    mirror.mirror("gd52", [source_alarm])
    policy.process_cycle("gd52", [{
        "serid": 5702, "_remote_serid": 5702, "dtom": at,
        "_policy_measured_at": at, "_source_observed_at": at,
        "doserate": 99.99, "warnlevel": 23.0, "alarmlevel": 25.0,
    }], [dict(source_alarm, _policy_measured_at=at)])

    events = policy.list_events()
    raw = mirror.get("gd52", 5702, at)
    with security._connection() as db:
        details = db.execute(
            "SELECT policy_decision, policy_event_id, source_i_flag, acknowledged_at FROM remote_alarm_state WHERE source_id=? AND serid=? AND event_time=?",
            ("gd52", 5702, at.isoformat()),
        ).fetchone()

    assert len(events) == 1
    assert events[0]["reason"] == "HIGH_THRESHOLD"
    assert details[0] == "SURFACED"
    assert details[1] == events[0]["event_id"]
    assert details[2] == 0
    assert details[3] is None
    assert raw["is_active"] is True
