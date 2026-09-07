from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    serial_port: str = "COM15"
    detectors: str = ""
    baudrate: int = 2400
    serial_timeout: float = 3.0
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "ipradmon"
    serid: int = 5201
    building: str = "52"
    room: str = "IS-1"
    location: str = "Gd.52"
    warnlevel: float = 23.0
    alarmlevel: float = 25.0
    maxidlemin: int = 30
    unit: str = "µSv/h"
    sample_interval: float = 2.0
    refresh_interval: float = 2.0
    sync_enabled: bool = False
    central_url: str = ""
    central_token: str = ""
    sync_batch_size: int = 100
    sync_timeout: float = 10.0
    sync_initial_lookback_hours: int = 24
    grafana_url: str = "http://localhost:3300/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv"
    grafana_fallback_port: int = 3300
    grafana_user: str = "admin"
    grafana_password: str = "admin"
    runtime_dir: Path = Path("runtime")
    log_dir: Path = Path("logs")
    single_instance_port: int = 47652

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Settings":
        if load_dotenv is not None and env_file:
            load_dotenv(env_file, override=False)
        get = os.getenv
        return cls(
            serial_port=get("RADMON_SERIAL_PORT", "COM15"),
            detectors=get("RADMON_DETECTORS", ""),
            baudrate=int(get("RADMON_BAUDRATE", "2400")),
            serial_timeout=float(get("RADMON_SERIAL_TIMEOUT", "3")),
            db_host=get("RADMON_DB_HOST", "localhost"),
            db_port=int(get("RADMON_DB_PORT", "3306")),
            db_user=get("RADMON_DB_USER", "root"),
            db_password=get("RADMON_DB_PASSWORD", ""),
            db_name=get("RADMON_DB_NAME", "ipradmon"),
            serid=int(get("RADMON_SERID", "5201")),
            building=get("RADMON_BUILDING", "52"),
            room=get("RADMON_ROOM", "IS-1"),
            location=get("RADMON_LOCATION", "Gd.52"),
            warnlevel=float(get("RADMON_WARNLEVEL", "23")),
            alarmlevel=float(get("RADMON_ALARMLEVEL", "25")),
            maxidlemin=int(get("RADMON_MAXIDLEMIN", "30")),
            unit=get("RADMON_UNIT", "µSv/h").replace("μ", "µ").replace("uSv/h", "µSv/h"),
            sample_interval=float(get("RADMON_SAMPLE_INTERVAL", "2")),
            refresh_interval=float(get("RADMON_REFRESH_INTERVAL", "2")),
            sync_enabled=_as_bool(get("RADMON_SYNC_ENABLED"), False),
            central_url=get("RADMON_CENTRAL_URL", ""),
            central_token=get("RADMON_CENTRAL_TOKEN", ""),
            sync_batch_size=int(get("RADMON_SYNC_BATCH_SIZE", "100")),
            sync_timeout=float(get("RADMON_SYNC_TIMEOUT", "10")),
            sync_initial_lookback_hours=int(get("RADMON_SYNC_INITIAL_LOOKBACK_HOURS", "24")),
            grafana_url=get(
                "RADMON_GRAFANA_URL",
                "http://localhost:3300/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv",
            ),
            grafana_fallback_port=int(get("RADMON_GRAFANA_PORT", "3300")),
            grafana_user=get("RADMON_GRAFANA_USER", "admin"),
            grafana_password=get("RADMON_GRAFANA_PASSWORD", "admin"),
            runtime_dir=Path(get("RADMON_RUNTIME_DIR", "runtime")),
            log_dir=Path(get("RADMON_LOG_DIR", "logs")),
            single_instance_port=int(get("RADMON_SINGLE_INSTANCE_PORT", "47652")),
        )

    def detector_bindings(self) -> list[tuple[int, str]]:
        """Return configured detector ID -> serial port bindings.

        `RADMON_DETECTORS` accepts entries separated by semicolons, for example
        `5201@COM15;5202@COM16`. If it is empty the legacy single detector
        fields remain the source of truth.
        """
        raw = self.detectors.strip()
        if not raw:
            return [(self.serid, self.serial_port.strip())]

        bindings: list[tuple[int, str]] = []
        seen: set[int] = set()
        for entry in raw.split(";"):
            item = entry.strip()
            if not item or item.count("@") != 1:
                raise ValueError(
                    "RADMON_DETECTORS harus berbentuk SERID@PORT;SERID@PORT"
                )
            serid_text, port = (part.strip() for part in item.split("@", 1))
            if not serid_text.isdigit() or int(serid_text) <= 0 or not port:
                raise ValueError(f"Binding detector tidak valid: {item!r}")
            serid = int(serid_text)
            if serid in seen:
                raise ValueError(f"SERID detector duplikat: {serid}")
            seen.add(serid)
            bindings.append((serid, port))
        return bindings

    def for_dummy(self) -> "Settings":
        return replace(
            self,
            serid=5202,
            building="52",
            room="IS-1 Koridor",
            location="Gd.52",
            warnlevel=8.0,
            alarmlevel=10.0,
            maxidlemin=30,
            unit="µSv/h",
            sample_interval=2.0,
            refresh_interval=2.0,
        )

    @property
    def station_label(self) -> str:
        return f"[{self.serid}] {self.room} ({self.location})"
