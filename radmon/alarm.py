from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import Measurement, StationConfig
from .status import MonitorStatus, classify_status


class AlarmRepository(Protocol):
    def active_alarm(self, serid: int | None = None): ...
    def open_alarm(self, serid: int, state: str, severity: str, started_at: datetime, last_value: float | None, threshold_value: float | None) -> int: ...
    def update_alarm(self, event_id: int, state: str, severity: str, value: float | None, threshold: float | None, at: datetime) -> None: ...
    def close_alarm(self, event_id: int, ended_at: datetime, last_value: float | None = None) -> None: ...
    def acknowledge_alarm(self, event_id: int, operator: str, note: str, at: datetime | None = None) -> None: ...


class AlarmService:
    def __init__(self, repository: AlarmRepository, station: StationConfig) -> None:
        self.repository = repository
        self.station = station

    def evaluate(self, measurement: Measurement, now: datetime | None = None) -> str:
        current_time = now or measurement.measured_at
        state = classify_status(
            measurement.dose_rate,
            measurement.measured_at,
            current_time,
            self.station.warnlevel,
            self.station.alarmlevel,
            self.station.maxidlemin,
        ).value
        active = self.repository.active_alarm(self.station.serid)
        if state == MonitorStatus.NORMAL.value:
            if active is not None:
                self.repository.close_alarm(int(active["eventid"]), current_time, measurement.dose_rate)
            return state

        severity = {
            MonitorStatus.ALERT.value: "warning",
            MonitorStatus.ALARM.value: "critical",
            MonitorStatus.OFFLINE.value: "offline",
        }[state]
        threshold = (
            self.station.alarmlevel if state == MonitorStatus.ALARM.value
            else self.station.warnlevel if state == MonitorStatus.ALERT.value
            else float(self.station.maxidlemin)
        )
        if active is None:
            self.repository.open_alarm(
                self.station.serid,
                state,
                severity,
                current_time,
                measurement.dose_rate,
                threshold,
            )
        elif active.get("state") != state or active.get("severity") != severity:
            self.repository.update_alarm(
                int(active["eventid"]),
                state,
                severity,
                measurement.dose_rate,
                threshold,
                current_time,
            )
        return state

    def acknowledge(self, event_id: int, operator: str, note: str = "") -> None:
        if not operator.strip():
            raise ValueError("operator name is required")
        self.repository.acknowledge_alarm(event_id, operator, note)
