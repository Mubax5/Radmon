from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .db import connect_mariadb
from .models import Measurement
from .repository import upsert_recent


class StationMetadata(BaseModel):
    serid: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    maxidlemin: int = Field(ge=1)
    warnlevel: float = Field(ge=0)
    alarmlevel: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=20)


class IngestMeasurement(BaseModel):
    sample_key: str = Field(min_length=64, max_length=64)
    serid: int = Field(gt=0)
    dtom: datetime
    doserate: float = Field(ge=0)
    dose: float = Field(default=0.0, ge=0)
    previnterval: int = Field(default=2, ge=0)
    stat: int = 0


class IngestBatch(BaseModel):
    source_name: str = Field(min_length=1, max_length=128)
    station: StationMetadata
    measurements: list[IngestMeasurement] = Field(min_length=1, max_length=1000)


class CentralRepositoryProtocol(Protocol):
    def ping(self) -> bool: ...
    def ingest_batch(self, measurements: list[dict[str, Any]], station: dict[str, Any], source_name: str) -> int: ...
    def stations(self) -> list[dict[str, Any]]: ...
    def latest(self, serid: int) -> dict[str, Any] | None: ...
    def history(self, serid: int, limit: int = 240) -> list[dict[str, Any]]: ...


class CentralMariaDBRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _connect(self):
        return connect_mariadb(self.settings)

    def ping(self) -> bool:
        try:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                return True
            finally:
                connection.close()
        except Exception:
            return False

    def ingest_batch(self, measurements: list[dict[str, Any]], station: dict[str, Any], source_name: str) -> int:
        connection = self._connect()
        inserted = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
INSERT INTO device
  (serid, name, location, maxidlemin, warnlevel, alarmlevel, unit, audiopath, hwaddress, hwtype, description)
VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'remote', ?)
ON DUPLICATE KEY UPDATE
  name = VALUES(name), location = VALUES(location), maxidlemin = VALUES(maxidlemin),
  warnlevel = VALUES(warnlevel), alarmlevel = VALUES(alarmlevel), unit = VALUES(unit),
  hwaddress = VALUES(hwaddress), description = VALUES(description)
""",
                    (
                        station["serid"], station["name"], station["location"], station["maxidlemin"],
                        station["warnlevel"], station["alarmlevel"], station["unit"], source_name[:50],
                        f"Synced from {source_name}"[:255],
                    ),
                )
                for item in measurements:
                    cursor.execute(
                        "SELECT dtom, doserate, dose FROM measurement WHERE serid = ? AND dtom < ? ORDER BY dtom DESC LIMIT 1",
                        (item["serid"], item["dtom"]),
                    )
                    previous = cursor.fetchone()
                    cursor.execute(
                        "INSERT IGNORE INTO measurement (serid, dtom, doserate, dose, previnterval, stat) VALUES (?, ?, ?, ?, ?, ?)",
                        (item["serid"], item["dtom"], item["doserate"], item.get("dose", 0.0), item["previnterval"], item["stat"]),
                    )
                    if getattr(cursor, "rowcount", 0) == 1:
                        inserted += 1
                        cursor.execute("SELECT dtom FROM recent WHERE serid = ?", (item["serid"],))
                        recent_row = cursor.fetchone()
                        recent_time = recent_row.get("dtom") if isinstance(recent_row, dict) else (recent_row[0] if recent_row else None)
                        if recent_time is None or item["dtom"] >= recent_time:
                            previous_time = previous.get("dtom") if isinstance(previous, dict) else (previous[0] if previous else None)
                            previous_rate = previous.get("doserate") if isinstance(previous, dict) else (previous[1] if previous else None)
                            previous_dose = previous.get("dose") if isinstance(previous, dict) else (previous[2] if previous else None)
                            measurement = Measurement(
                                serid=int(item["serid"]), measured_at=item["dtom"], dose_rate=float(item["doserate"]),
                                previnterval=int(item["previnterval"]), stat=int(item["stat"]),
                            )
                            upsert_recent(
                                cursor, measurement, dose=float(item.get("dose") or 0.0), previous_time=previous_time,
                                previous_rate=float(previous_rate) if previous_rate is not None else None,
                                previous_dose=float(previous_dose) if previous_dose is not None else None,
                                interval=int(item["previnterval"]),
                            )
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def stations(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT serid, name, location, warnlevel, alarmlevel, unit FROM device ORDER BY location, name")
                rows = cursor.fetchall()
            keys = ("serid", "name", "location", "warnlevel", "alarmlevel", "unit")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def latest(self, serid: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT serid, dtom, doserate, dose, previnterval, stat FROM measurement WHERE serid = ? ORDER BY dtom DESC LIMIT 1",
                    (serid,),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            keys = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
            return dict(row) if isinstance(row, dict) else dict(zip(keys, row))
        finally:
            connection.close()

    def history(self, serid: int, limit: int = 240) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 2000))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT serid, dtom, doserate, dose, previnterval, stat FROM measurement WHERE serid = ? ORDER BY dtom DESC LIMIT ?",
                    (int(serid), bounded),
                )
                rows = cursor.fetchall()
            keys = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()


def create_central_app(repository: CentralRepositoryProtocol, settings: Settings) -> FastAPI:
    app = FastAPI(title="Radmon Central API", docs_url=None, redoc_url=None)
    app.state.radmon_repository = repository

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.central_token}"
        if not settings.central_token or authorization != expected:
            raise HTTPException(status_code=401, detail="invalid bearer token")

    @app.get("/health")
    def health():
        return {
            "service": "radmon-central",
            "status": "ok" if repository.ping() else "error",
            "lan_enabled": bool(getattr(app.state, "radmon_lan_enabled", False)),
            "lan_source_count": int(getattr(app.state, "radmon_lan_source_count", 0)),
        }

    @app.post("/api/v1/measurements/batch", dependencies=[Depends(require_token)])
    def ingest(batch: IngestBatch):
        items = [item.model_dump() for item in batch.measurements]
        inserted = repository.ingest_batch(items, batch.station.model_dump(), batch.source_name)
        return {"received": len(items), "inserted": inserted, "duplicates": len(items) - inserted}

    @app.get("/api/v1/stations", dependencies=[Depends(require_token)])
    def stations():
        return repository.stations()

    @app.get("/api/v1/latest/{serid}", dependencies=[Depends(require_token)])
    def latest(serid: int):
        row = repository.latest(serid)
        if row is None:
            raise HTTPException(status_code=404, detail="station has no measurements")
        return row

    return app
