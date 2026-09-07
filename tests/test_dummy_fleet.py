from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

import radmon.runtime as runtime_module
from radmon.config import Settings
from radmon.runtime import ApplicationRuntime, DummyFleet
from radmon.stations import station_catalog, station_by_id


class FakeRepository:
    def __init__(self):
        self.measurements = []
        self.alarms = []

    def station_configs(self):
        return station_catalog()

    def station_config(self, serid=None):
        station = station_by_id(int(serid))
        if station is None:
            raise KeyError(serid)
        return station

    def insert_measurement(self, measurement, raw=None):
        self.measurements.append(measurement)
        return 0.0

    def last_alarm(self, serid):
        for row in reversed(self.alarms):
            if row["serid"] == serid:
                return row
        return None

    def record_alarm(self, serid, alarm_type, message, *, at=None):
        self.alarms.append(
            {"serid": serid, "type": alarm_type, "msg": message, "dtom": at}
        )
        return len(self.alarms)


class FixedGenerator:
    def __init__(self, value=0.2):
        self.value = value

    def next_value(self):
        return self.value


def test_dummy_fleet_emits_one_measurement_for_every_detector_room_per_step():
    repository = FakeRepository()
    created = []

    def generator_factory(station):
        generator = FixedGenerator(0.2 + station.serid / 1_000_000)
        created.append((station.serid, generator))
        return generator

    fleet = DummyFleet(
        repository,
        repository.station_configs(),
        generator_factory=generator_factory,
    )
    at = datetime(2026, 9, 7, 15, 0, 0)
    count = fleet.step(at=at)

    expected_ids = [station.serid for station in station_catalog()]
    assert count == len(expected_ids) == 15
    assert [measurement.serid for measurement in repository.measurements] == expected_ids
    assert all(measurement.measured_at == at for measurement in repository.measurements)
    assert len(created) == len(expected_ids)
    assert len({id(generator) for _, generator in created}) == len(expected_ids)


def test_detector_bindings_default_to_legacy_single_port_and_parse_multi_port_map():
    legacy = replace(Settings(), serid=5201, serial_port="COM15", detectors="")
    assert legacy.detector_bindings() == [(5201, "COM15")]

    multi = replace(
        Settings(),
        detectors="5201@COM15; 5202@COM16;5701@COM18",
    )
    assert multi.detector_bindings() == [
        (5201, "COM15"),
        (5202, "COM16"),
        (5701, "COM18"),
    ]


@pytest.mark.parametrize(
    "value",
    ["abc", "5201", "@COM15", "5201@", "5201@COM15;5201@COM16"],
)
def test_detector_bindings_reject_invalid_or_duplicate_entries(value):
    with pytest.raises(ValueError):
        replace(Settings(), detectors=value).detector_bindings()


def test_runtime_builds_one_real_collector_per_configured_detector(monkeypatch):
    repository = FakeRepository()
    settings = replace(
        Settings(),
        serid=5201,
        serial_port="COM15",
        detectors="5201@COM15;5202@COM16;5701@COM18",
    )
    captured = []

    class FakeCollector:
        def __init__(self, collector_settings, repo, alarm_service):
            captured.append((collector_settings, repo, alarm_service))
            self.settings = collector_settings

    monkeypatch.setattr(runtime_module, "SerialCollector", FakeCollector)
    runtime = ApplicationRuntime(repository, settings, None, "detector")
    collectors = runtime._build_detector_collectors()

    assert [collector.settings.serid for collector in collectors] == [5201, 5202, 5701]
    assert [collector.settings.serial_port for collector in collectors] == [
        "COM15",
        "COM16",
        "COM18",
    ]
    assert [item[2].station.serid for item in captured] == [5201, 5202, 5701]
    assert [collector.settings.unit for collector in collectors] == [
        "µSv/h",
        "µSv/h",
        "µSv/h",
    ]
