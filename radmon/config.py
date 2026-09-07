from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional during lightweight tests
    load_dotenv = None


@dataclass(frozen=True, slots=True)
class Settings:
    serial_port: str = "COM15"
    baudrate: int = 2400
    serial_timeout: float = 3.0
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "ipradmon"
    serid: int = 5202
    building: str = "52"
    room: str = "IS-1 Koridor"
    location: str = "Gd.52"
    warnlevel: float = 8.0
    alarmlevel: float = 10.0
    maxidlemin: int = 5
    unit: str = "uSv/h"
    sample_interval: float = 2.0
    public_host: str = "0.0.0.0"
    public_port: int = 8080
    central_host: str = "0.0.0.0"
    central_port: int = 8090
    central_url: str = "http://127.0.0.1:8090"
    central_token: str = "CHANGE-ME"
    sync_batch_size: int = 100
    sync_timeout: float = 10.0
    log_dir: Path = Path("logs")

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Settings":
        if load_dotenv is not None and env_file:
            load_dotenv(env_file, override=False)
        get = os.getenv
        return cls(
            serial_port=get("RADMON_SERIAL_PORT", "COM15"),
            baudrate=int(get("RADMON_BAUDRATE", "2400")),
            serial_timeout=float(get("RADMON_SERIAL_TIMEOUT", "3")),
            db_host=get("RADMON_DB_HOST", "localhost"),
            db_port=int(get("RADMON_DB_PORT", "3306")),
            db_user=get("RADMON_DB_USER", "root"),
            db_password=get("RADMON_DB_PASSWORD", ""),
            db_name=get("RADMON_DB_NAME", "ipradmon"),
            serid=int(get("RADMON_SERID", "5202")),
            building=get("RADMON_BUILDING", "52"),
            room=get("RADMON_ROOM", "IS-1 Koridor"),
            location=get("RADMON_LOCATION", "Gd.52"),
            warnlevel=float(get("RADMON_WARNLEVEL", "8")),
            alarmlevel=float(get("RADMON_ALARMLEVEL", "10")),
            maxidlemin=int(get("RADMON_MAXIDLEMIN", "5")),
            unit=get("RADMON_UNIT", "uSv/h"),
            sample_interval=float(get("RADMON_SAMPLE_INTERVAL", "2")),
            public_host=get("RADMON_PUBLIC_HOST", "0.0.0.0"),
            public_port=int(get("RADMON_PUBLIC_PORT", "8080")),
            central_host=get("RADMON_CENTRAL_HOST", "0.0.0.0"),
            central_port=int(get("RADMON_CENTRAL_PORT", "8090")),
            central_url=get("RADMON_CENTRAL_URL", "http://127.0.0.1:8090"),
            central_token=get("RADMON_CENTRAL_TOKEN", "CHANGE-ME"),
            sync_batch_size=int(get("RADMON_SYNC_BATCH_SIZE", "100")),
            sync_timeout=float(get("RADMON_SYNC_TIMEOUT", "10")),
            log_dir=Path(get("RADMON_LOG_DIR", "logs")),
        )

    @property
    def station_label(self) -> str:
        return f"[{self.serid}] {self.room} (Gd. {self.building})"
