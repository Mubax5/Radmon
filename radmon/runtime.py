from __future__ import annotations

from datetime import datetime
import logging
import threading
from typing import Any

import uvicorn

from .alarm import AlarmService
from .collector import SerialCollector
from .config import Settings
from .dummy import DummyDoseGenerator
from .models import Measurement
from .public_api import create_public_app
from .sync import SyncAgent

LOGGER = logging.getLogger(__name__)


class ApplicationRuntime:
    """Own detector/dummy acquisition, public monitoring, and optional central sync."""

    def __init__(self, repository: Any, settings: Settings, alarm_service: AlarmService, source: str) -> None:
        if source not in {"detector", "dummy"}:
            raise ValueError(f"unsupported source: {source}")
        self.repository = repository
        self.settings = settings
        self.alarm_service = alarm_service
        self.source = source
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.public_server: uvicorn.Server | None = None

    def _thread(self, name: str, target: Any) -> None:
        thread = threading.Thread(name=name, target=target, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _run_dummy(self) -> None:
        generator = DummyDoseGenerator(
            "mixed",
            warnlevel=self.settings.warnlevel,
            alarmlevel=self.settings.alarmlevel,
        )
        while not self.stop_event.is_set():
            when = datetime.now()
            measurement = Measurement(
                serid=self.settings.serid,
                measured_at=when,
                dose_rate=generator.next_value(),
                previnterval=2,
                stat=0,
            )
            try:
                self.repository.insert_measurement(measurement)
                self.alarm_service.evaluate(measurement)
            except Exception as exc:
                LOGGER.exception("dummy acquisition failed: %s", exc)
            self.stop_event.wait(2.0)

    def _run_public(self) -> None:
        app = create_public_app(self.repository, self.settings)
        config = uvicorn.Config(
            app,
            host=self.settings.public_host,
            port=self.settings.public_port,
            log_level="warning",
            access_log=False,
        )
        self.public_server = uvicorn.Server(config)
        self.public_server.run()

    def _run_sync(self) -> None:
        SyncAgent(self.repository, self.settings).run_forever(self.stop_event, interval=2.0)

    def start(self) -> None:
        if self.source == "dummy":
            self._thread("radmon-dummy", self._run_dummy)
        else:
            collector = SerialCollector(self.settings, self.repository, self.alarm_service)
            self._thread("radmon-detector", lambda: collector.run_forever(self.stop_event))
        if self.settings.public_enabled:
            self._thread("radmon-public", self._run_public)
        if self.settings.sync_enabled and self.settings.central_url and self.settings.central_token:
            self._thread("radmon-sync", self._run_sync)
        LOGGER.info("runtime started source=%s station=%s", self.source, self.settings.station_label)

    def stop(self) -> None:
        self.stop_event.set()
        if self.public_server is not None:
            self.public_server.should_exit = True
        for thread in self.threads:
            thread.join(timeout=3.0)
        LOGGER.info("runtime stopped")
