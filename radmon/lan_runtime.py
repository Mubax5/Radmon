from __future__ import annotations

import logging
import os
import threading
from typing import Any

from .lan import LanAggregator, LanCheckpointStore, MariaCentralStore, RemoteMariaDBSource

LOGGER = logging.getLogger(__name__)


class LanRuntime:
    """Pull production LAN databases into the local central ipradmon."""

    def __init__(self, settings, services, *, whatsapp_dispatcher: Any | None = None) -> None:
        self.settings = settings
        self.services = services
        self.whatsapp_dispatcher = whatsapp_dispatcher
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.interval = max(0.5, float(os.getenv("RADMON_LAN_POLL_INTERVAL", "2")))
        self.batch_size = max(1, int(os.getenv("RADMON_LAN_BATCH_SIZE", "1000")))
        self.central = MariaCentralStore(settings)
        self.checkpoints = LanCheckpointStore(services.security)

    def _thread(self, name: str, target) -> None:
        thread = threading.Thread(name=name, target=target, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _run_source(self, source) -> None:
        aggregator = LanAggregator(
            self.central,
            self.checkpoints,
            remote_factory=lambda item: RemoteMariaDBSource(item),
            alarm_mirror=self.services.alarm_mirror,
            batch_size=self.batch_size,
        )
        while not self.stop_event.is_set():
            result = aggregator.run_source_once(source)
            if result.error:
                LOGGER.warning("LAN source=%s error=%s", source.source_id, result.error)
            elif result.inserted_measurements or result.mirrored_alarms:
                LOGGER.info(
                    "LAN source=%s measurements=%s alarms=%s",
                    source.source_id,
                    result.inserted_measurements,
                    result.mirrored_alarms,
                )
            self.stop_event.wait(self.interval)

    def _run_whatsapp(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.whatsapp_dispatcher.run_once()
            except Exception as exc:
                LOGGER.warning("WhatsApp dispatcher error=%s", exc)
            self.stop_event.wait(max(2.0, float(os.getenv("RADMON_WHATSAPP_INTERVAL", "20"))))

    def start(self) -> None:
        for source in self.services.sources.values():
            self._thread(f"radmon-lan-{source.source_id}", lambda active=source: self._run_source(active))
        if self.whatsapp_dispatcher is not None:
            self._thread("radmon-whatsapp", self._run_whatsapp)
        LOGGER.info("LAN runtime started sources=%s", len(self.services.sources))

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3.0)
        LOGGER.info("LAN runtime stopped")
