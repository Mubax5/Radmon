from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import Measurement, StationConfig
from .status import classify_status


class AlarmService:
    """Persist threshold transitions using the legacy ipradmon.alarm table."""

    def __init__(self, repository: Any, station: StationConfig) -> None:
        self.repository = repository
        self.station = station

    def evaluate(self, measurement: Measurement) -> str:
        state = classify_status(
            measurement.dose_rate,
            measurement.measured_at,
            measurement.measured_at,
            self.station.warnlevel,
            self.station.alarmlevel,
            self.station.maxidlemin,
        ).value
        previous = self.repository.last_alarm(self.station.serid)
        previous_type = str(previous.get("type", "")) if previous else ""
        active_type = previous_type if previous_type in {"ALERT", "ALARM"} else "NORMAL"

        if state in {"ALERT", "ALARM"} and active_type != state:
            threshold = self.station.alarmlevel if state == "ALARM" else self.station.warnlevel
            self.repository.record_alarm(
                self.station.serid,
                state,
                f"Dose rate {measurement.dose_rate:.3f} {self.station.unit}; threshold {threshold:g} {self.station.unit}",
                at=measurement.measured_at,
            )
        elif state == "NORMAL" and active_type in {"ALERT", "ALARM"}:
            self.repository.record_alarm(
                self.station.serid,
                "RECOVERY",
                f"Dose rate kembali normal: {measurement.dose_rate:.3f} {self.station.unit}",
                at=measurement.measured_at,
            )
        return state
