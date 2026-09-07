from datetime import datetime
from radmon.collector import SerialCollector
from radmon.config import Settings


class Repo:
    def __init__(self): self.calls = []
    def insert_measurement(self, measurement, *, raw=None, queue_sync=True): self.calls.append((measurement, raw, queue_sync)); return "sample-key"


class Alarm:
    def __init__(self): self.calls = []
    def evaluate(self, measurement, now=None): self.calls.append(measurement); return "NORMAL"


def test_collector_processes_existing_ascii_protocol_into_5202_measurement():
    settings = Settings(); repo = Repo(); alarm = Alarm(); collector = SerialCollector(settings, repo, alarm); when = datetime(2026, 9, 7, 10, 0, 0)
    measurement = collector.process_raw("0.12345 some detector text", when)
    assert measurement.serid == 5202
    assert measurement.dose_rate == 0.12345
    assert measurement.previnterval == 2
    assert repo.calls[0][1] == "0.12345 some detector text"
    assert alarm.calls == [measurement]


def test_collector_rejects_invalid_line_without_database_write():
    repo = Repo(); collector = SerialCollector(Settings(), repo, None)
    try: collector.process_raw("not-a-number", datetime.now())
    except ValueError: pass
    else: raise AssertionError("invalid detector line should fail")
    assert repo.calls == []
