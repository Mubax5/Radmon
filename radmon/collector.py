from __future__ import annotations

from datetime import datetime
import importlib
import logging
import time
from typing import Any

from .config import Settings
from .detector import parse_detector_line
from .models import Measurement

LOGGER = logging.getLogger(__name__)


class SerialCollector:
    def __init__(self, settings: Settings, repository: Any, alarm_service: Any | None) -> None:
        self.settings = settings
        self.repository = repository
        self.alarm_service = alarm_service

    def process_raw(self, raw: str, measured_at: datetime | None = None) -> Measurement:
        when = measured_at or datetime.now()
        dose_rate = parse_detector_line(raw)
        measurement = Measurement(
            serid=self.settings.serid,
            measured_at=when,
            dose_rate=dose_rate,
            previnterval=2,
            stat=0,
        )
        self.repository.insert_measurement(measurement, raw=raw)
        if self.alarm_service is not None:
            self.alarm_service.evaluate(measurement)
        LOGGER.info("measurement serid=%s time=%s dose=%.4f %s", measurement.serid, measurement.measured_at.isoformat(sep=" "), measurement.dose_rate, self.settings.unit)
        return measurement

    def _open_serial(self):
        serial = importlib.import_module("serial")
        return serial.Serial(
            port=self.settings.serial_port,
            baudrate=self.settings.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=min(self.settings.serial_timeout, 2.0),
        )

    def run_forever(self, stop_event: Any | None = None) -> None:
        stop = stop_event
        LOGGER.info("starting detector collector port=%s baud=%s station=%s", self.settings.serial_port, self.settings.baudrate, self.settings.station_label)
        while stop is None or not stop.is_set():
            serial_port = None
            try:
                serial_port = self._open_serial()
                LOGGER.info("serial connected: %s", self.settings.serial_port)
                while stop is None or not stop.is_set():
                    raw_bytes = serial_port.readline()
                    if not raw_bytes:
                        continue
                    raw = raw_bytes.decode("ascii", errors="ignore").strip()
                    if not raw:
                        continue
                    try:
                        self.process_raw(raw)
                    except ValueError:
                        LOGGER.warning("invalid detector raw line: %r", raw)
            except KeyboardInterrupt:
                return
            except Exception as exc:
                LOGGER.exception("collector connection/acquisition error: %s", exc)
                if stop is not None:
                    stop.wait(2.0)
                else:
                    time.sleep(2.0)
            finally:
                if serial_port is not None:
                    try:
                        serial_port.close()
                    except Exception:
                        pass
