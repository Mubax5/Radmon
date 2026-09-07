from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class StationConfig:
    serid: int
    building: str
    room: str
    location: str
    warnlevel: float
    alarmlevel: float
    maxidlemin: int
    unit: str = "uSv/h"


@dataclass(frozen=True, slots=True)
class Measurement:
    serid: int
    measured_at: datetime
    dose_rate: float
    previnterval: int = 2
    stat: int = 0


@dataclass(frozen=True, slots=True)
class LatestReading:
    station: StationConfig
    measured_at: datetime | None
    dose_rate: float | None
    previous_dose_rate: float | None = None
    raw: str | None = None
