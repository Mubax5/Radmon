from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum


class MonitorStatus(str, Enum):
    NORMAL = "NORMAL"
    ALERT = "ALERT"
    ALARM = "ALARM"
    OFFLINE = "OFFLINE"


def classify_status(
    dose_rate: float | None,
    measured_at: datetime | None,
    now: datetime,
    warnlevel: float,
    alarmlevel: float,
    maxidlemin: int,
) -> MonitorStatus:
    if dose_rate is None or measured_at is None:
        return MonitorStatus.OFFLINE
    if measured_at < now - timedelta(minutes=maxidlemin):
        return MonitorStatus.OFFLINE
    if dose_rate >= alarmlevel:
        return MonitorStatus.ALARM
    if dose_rate >= warnlevel:
        return MonitorStatus.ALERT
    return MonitorStatus.NORMAL


def trend_code(current: float | None, previous: float | None, deadband: float = 0.001) -> str:
    if current is None:
        return "OFFLINE"
    if previous is None or abs(current - previous) <= deadband:
        return "STABLE"
    return "UP" if current > previous else "DOWN"


def trend_symbol(code: str) -> str:
    return {"UP": "↑", "DOWN": "↓", "STABLE": "→", "OFFLINE": "✖"}.get(code, "→")
