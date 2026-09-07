from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging
import threading
from typing import Any, Callable

from .alarm import AlarmService
from .collector import SerialCollector
from .config import Settings
from .dummy import DummyDoseGenerator
from .models import Measurement, StationConfig
from .sync import SyncAgent

LOGGER = logging.getLogger(__name__)


class DummyFleet:
    """Generate one independent dummy stream for every configured station."""

    def __init__(
        self,
        repository: Any,
        stations: list[StationConfig],
        *,
        generator_factory: Callable[[StationConfig], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.stations = list(stations)
        factory = generator_factory or self._default_generator
        self.generators = {
            station.serid: factory(station) for station in self.stations
        }
        self.alarm_services = {
            station.serid: AlarmService(repository, station) for station in self.stations
        }

    @staticmethod
    def _default_generator(station: StationConfig) -> DummyDoseGenerator:
        # Per-station seeds keep streams independent while making demo behavior
        # reproducible enough for troubleshooting.
        return DummyDoseGenerator(
            "mixed",
            seed=station.serid,
            warnlevel=station.warnlevel,
            alarmlevel=station.alarmlevel,
        )

    def step(self, *, at: datetime | None = None) -> int:
        when = at or datetime.now()
        written = 0
        for station in self.stations:
            generator = self.generators[station.serid]
            measurement = Measurement(
                serid=station.serid,
                measured_at=when,
                dose_rate=float(generator.next_value()),
                previnterval=2,
                stat=0,
            )
            self.repository.insert_measurement(measurement)
            self.alarm_services[station.serid].evaluate(measurement)
            written += 1
        return written


class ApplicationRuntime:
    """Own detector/dummy acquisition and optional central sync; Grafana is external."""

    def __init__(
        self,
        repository: Any,
        settings: Settings,
        alarm_service: AlarmService | None,
        source: str,
    ) -> None:
        if source not in {"detector", "dummy"}:
            raise ValueError(f"unsupported source: {source}")
        self.repository = repository
        self.settings = settings
        self.alarm_service = alarm_service
        self.source = source
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self._dummy_fleet: DummyFleet | None = None

    def _thread(self, name: str, target: Any) -> None:
        thread = threading.Thread(name=name, target=target, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _settings_for_station(
        self,
        station: StationConfig,
        *,
        serial_port: str | None = None,
    ) -> Settings:
        return replace(
            self.settings,
            serial_port=serial_port or self.settings.serial_port,
            serid=station.serid,
            building=station.building,
            room=station.room,
            location=station.location,
            warnlevel=station.warnlevel,
            alarmlevel=station.alarmlevel,
            maxidlemin=station.maxidlemin,
            unit=station.unit,
        )

    def _run_dummy(self) -> None:
        stations = self.repository.station_configs()
        self._dummy_fleet = DummyFleet(self.repository, stations)
        while not self.stop_event.is_set():
            try:
                count = self._dummy_fleet.step()
                LOGGER.debug("dummy fleet wrote %s station measurements", count)
            except Exception as exc:
                LOGGER.exception("dummy fleet acquisition failed: %s", exc)
            self.stop_event.wait(max(0.1, self.settings.sample_interval))

    def _build_detector_collectors(self) -> list[SerialCollector]:
        bindings = self.settings.detector_bindings()
        collectors: list[SerialCollector] = []
        for serid, port in bindings:
            station = self.repository.station_config(serid)
            collector_settings = self._settings_for_station(
                station,
                serial_port=port,
            )
            if (
                self.alarm_service is not None
                and serid == self.settings.serid
                and self.alarm_service.station.serid == serid
            ):
                alarm_service = self.alarm_service
            else:
                alarm_service = AlarmService(self.repository, station)
            collectors.append(
                SerialCollector(
                    collector_settings,
                    self.repository,
                    alarm_service,
                )
            )
        return collectors

    def _sync_station_settings(self) -> list[Settings]:
        if self.source == "dummy":
            stations = self.repository.station_configs()
        else:
            stations = [
                self.repository.station_config(serid)
                for serid, _ in self.settings.detector_bindings()
            ]
        return [self._settings_for_station(station) for station in stations]

    def _run_sync(self, station_settings: Settings) -> None:
        SyncAgent(self.repository, station_settings).run_forever(
            self.stop_event,
            interval=2.0,
        )

    def start(self) -> None:
        if self.source == "dummy":
            self._thread("radmon-dummy-fleet", self._run_dummy)
        else:
            collectors = self._build_detector_collectors()
            for collector in collectors:
                self._thread(
                    f"radmon-detector-{collector.settings.serid}",
                    lambda active=collector: active.run_forever(self.stop_event),
                )

        if (
            self.settings.sync_enabled
            and self.settings.central_url
            and self.settings.central_token
        ):
            for station_settings in self._sync_station_settings():
                self._thread(
                    f"radmon-sync-{station_settings.serid}",
                    lambda active=station_settings: self._run_sync(active),
                )
        LOGGER.info(
            "runtime started source=%s stations=%s",
            self.source,
            len(self.repository.station_configs())
            if self.source == "dummy"
            else len(self.settings.detector_bindings()),
        )

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3.0)
        LOGGER.info("runtime stopped")
