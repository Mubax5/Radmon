from datetime import datetime

from radmon.lan import LanAggregator, LanCheckpointStore, LanSource, parse_lan_sources
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.security import SecurityStore


def test_parse_three_lan_sources_without_committed_credentials(monkeypatch):
    monkeypatch.setenv("RADMON_LAN_SOURCES", "server50@192.168.1.50;server52@192.168.1.52;server38@192.168.1.38")
    monkeypatch.setenv("RADMON_LAN_DB_USER", "radmon_reader")
    monkeypatch.setenv("RADMON_LAN_DB_PASSWORD", "runtime-secret")
    sources = parse_lan_sources()
    assert [source.source_id for source in sources] == ["server50", "server52", "server38"]
    assert [source.host for source in sources] == ["192.168.1.50", "192.168.1.52", "192.168.1.38"]
    assert all(source.user == "radmon_reader" for source in sources)
    assert all(source.password == "runtime-secret" for source in sources)


def test_checkpoint_is_per_source_and_station(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    at = datetime(2026, 9, 8, 14, 1, 2)
    checkpoints.save("server52", 5201, at)
    assert checkpoints.load("server52", 5201) == at
    assert checkpoints.load("server50", 5201) is None
    assert checkpoints.load("server52", 5202) is None


class FakeRemote:
    def __init__(self, source, rows, *, fail=False, alarms=None):
        self.source = source
        self.rows = rows
        self.fail = fail
        self._alarms = alarms or []

    def live_rows(self):
        if self.fail:
            raise RuntimeError("offline")
        latest = self.rows[-1] if self.rows else {}
        return [{
            "serid": 5201,
            "name": "IS-1",
            "location": "Gd.52",
            "warnlevel": 23,
            "alarmlevel": 25,
            "maxidlemin": 30,
            "unit": "µSv/h",
            "description": "prod",
            "audiopath": "",
            "dtom": latest.get("dtom", datetime(2026, 9, 8, 14, 0, 0)),
            "doserate": latest.get("doserate", 0.1),
            "dose": latest.get("dose", 0.0),
            "lastrate": latest.get("doserate", 0.1),
            "minrate": 0.1,
            "maxrate": latest.get("doserate", 0.1),
            "avgrate": 0.2,
            "lastdose": 0.0,
            "mindose": 0.0,
            "maxdose": latest.get("dose", 0.0),
            "avgdose": 0.0,
            "firstmea": datetime(2026, 9, 8, 13, 0, 0),
            "lastmea": latest.get("dtom", datetime(2026, 9, 8, 14, 0, 0)),
            "lastmeasec": 2,
            "meacount": len(self.rows),
        }]

    def measurements_after(self, serid, after, limit):
        return [row for row in self.rows if after is None or row["dtom"] > after][:limit]

    def alarms_after(self, checkpoint, limit=500):
        rows = sorted(self._alarms, key=lambda row: (row["dtoa"], row["serid"]))
        if checkpoint is not None:
            rows = [row for row in rows if (row["dtoa"], row["serid"]) > checkpoint]
        return rows[:limit]


class FakeCentral:
    def __init__(self):
        self.devices = {}
        self.live = {}
        self.measurements = {}
        self.alarm_events = {}

    def ensure_remote_device(self, source_id, row):
        self.devices.setdefault(row["serid"], dict(row))

    def upsert_live_rows(self, source_id, rows):
        for row in rows:
            self.devices.setdefault(row["serid"], dict(row))
            self.live[row["serid"]] = dict(row)
        return len(rows)

    def import_measurements(self, source_id, rows):
        inserted = 0
        for row in rows:
            key = (row["serid"], row["dtom"])
            if key not in self.measurements:
                self.measurements[key] = dict(row)
                inserted += 1
        return inserted

    def mirror_alarm_events(self, source_id, rows):
        inserted = 0
        for row in rows:
            key = (source_id, row["serid"], row.get("dtoa"))
            if key not in self.alarm_events:
                self.alarm_events[key] = dict(row)
                inserted += 1
        return inserted


def test_aggregator_preserves_remote_dose_and_deduplicates(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    source = LanSource("server52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    rows = [
        {"serid": 5201, "dtom": datetime(2026, 9, 8, 14, 0, 0), "doserate": 1.2, "dose": 0.0042, "previnterval": 2, "stat": 0},
        {"serid": 5201, "dtom": datetime(2026, 9, 8, 14, 0, 2), "doserate": 1.3, "dose": 0.0007, "previnterval": 2, "stat": 0},
    ]
    central = FakeCentral()
    aggregator = LanAggregator(central, checkpoints, remote_factory=lambda value: FakeRemote(value, rows), batch_size=100)
    first = aggregator.run_source_once(source)
    second = aggregator.run_source_once(source)
    assert first.inserted_measurements == 2
    assert second.inserted_measurements == 0
    assert central.live[5201]["avgrate"] == 0.2
    assert [row["dose"] for row in central.measurements.values()] == [0.0042, 0.0007]
    assert checkpoints.load("server52", 5201) == datetime(2026, 9, 8, 14, 0, 2)


def test_history_catchup_is_bounded_to_one_batch_per_poll(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    source = LanSource("server52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    rows = [
        {"serid": 5201, "dtom": datetime(2026, 9, 8, 14, 0, second), "doserate": 1.0, "dose": 0.001, "previnterval": 2, "stat": 0}
        for second in range(5)
    ]
    central = FakeCentral()
    aggregator = LanAggregator(central, checkpoints, remote_factory=lambda value: FakeRemote(value, rows), batch_size=2)
    first = aggregator.run_source_once(source)
    assert first.inserted_measurements == 2
    assert len(central.measurements) == 2
    second = aggregator.run_source_once(source)
    assert second.inserted_measurements == 2
    assert len(central.measurements) == 4


def test_central_tag_mapping_does_not_change_remote_checkpoint_identity(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.resolve_station("server52", 5201)
    store.remap_central_serid(5201, 6201)
    checkpoints = LanCheckpointStore(store)
    source = LanSource("server52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    rows = [{"serid": 5201, "dtom": datetime(2026, 9, 8, 14, 0, 0), "doserate": 1.2, "dose": 0.0042, "previnterval": 2, "stat": 0}]
    central = FakeCentral()
    aggregator = LanAggregator(central, checkpoints, remote_factory=lambda value: FakeRemote(value, rows))
    result = aggregator.run_source_once(source)
    assert result.inserted_measurements == 1
    assert 6201 in central.devices
    assert 5201 not in central.devices
    assert (6201, datetime(2026, 9, 8, 14, 0, 0)) in central.measurements
    assert checkpoints.load("server52", 5201) == datetime(2026, 9, 8, 14, 0, 0)
    assert checkpoints.load("server52", 6201) is None


def test_legacy_alarm_is_incrementally_mirrored_to_sidecar_and_central(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    mirror = RemoteAlarmMirror(store)
    source = LanSource("server52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    alarm = {"serid": 5201, "dtoa": datetime(2026, 9, 8, 14, 3, 0), "lvl": 2,
             "mvalue": 26.2, "thvalue": 25.0, "nhit": 4, "ack": 0, "i_flag": 0,
             "i_op": None, "pic": None, "note": None}
    central = FakeCentral()
    aggregator = LanAggregator(
        central, checkpoints,
        remote_factory=lambda value: FakeRemote(value, [], alarms=[alarm]),
        alarm_mirror=mirror,
    )
    first = aggregator.run_source_once(source)
    second = aggregator.run_source_once(source)
    assert first.mirrored_alarms >= 1
    assert second.mirrored_alarms == 0
    assert len(mirror.list_alarms()) == 1
    assert len(central.alarm_events) == 1
    assert checkpoints.load_alarm("server52") == (alarm["dtoa"], 5201)


def test_one_offline_source_does_not_define_other_source_result(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    central = FakeCentral()
    good = LanSource("server52", "ok", 3306, "u", "p", "ipradmon")
    bad = LanSource("server50", "bad", 3306, "u", "p", "ipradmon")
    def factory(source):
        return FakeRemote(source, [], fail=source.source_id == "server50")
    aggregator = LanAggregator(central, checkpoints, remote_factory=factory)
    results = aggregator.run_sources_once([bad, good])
    assert results[0].error == "offline"
    assert results[1].error is None
