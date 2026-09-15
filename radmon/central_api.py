from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .db import connect_mariadb
from .recent_read_model import RollingRecentManager


LOG = logging.getLogger(__name__)


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
    def overview_rows(self) -> list[dict[str, Any]]: ...
    def latest(self, serid: int) -> dict[str, Any] | None: ...
    def history(self, serid: int, limit: int = 240) -> list[dict[str, Any]]: ...


class CentralMariaDBRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._recent_manager = RollingRecentManager(
            settings,
            connection_factory=lambda: self._connect(),
        )

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
        inserted_items: list[dict[str, Any]] = []
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
                        "INSERT IGNORE INTO measurement (serid, dtom, doserate, dose, previnterval, stat) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            item["serid"], item["dtom"], item["doserate"],
                            item.get("dose", 0.0), item["previnterval"], item["stat"],
                        ),
                    )
                    if getattr(cursor, "rowcount", 0) == 1:
                        inserted_items.append(item)
            # Commit authoritative history first. recent/vrecent is disposable and must
            # never be able to roll back a valid historical measurement.
            connection.commit()

            if inserted_items:
                try:
                    with connection.cursor() as cursor:
                        self._recent_manager.mirror_samples(cursor, inserted_items)
                        self._recent_manager.cleanup_with_cursor(cursor)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    LOG.exception(
                        "historical ingest tersimpan tetapi mirror rolling recent gagal source=%s",
                        source_name,
                    )
            return len(inserted_items)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def stations(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT serid, name, location, warnlevel, alarmlevel, maxidlemin, unit "
                    "FROM device ORDER BY location, name"
                )
                rows = cursor.fetchall()
            keys = ("serid", "name", "location", "warnlevel", "alarmlevel", "maxidlemin", "unit")
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def overview_rows(self) -> list[dict[str, Any]]:
        """Read one newest bounded monitoring sample per station."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT d.serid, d.name, d.location, d.warnlevel, d.alarmlevel, d.maxidlemin, d.unit,
       v.dtom, v.doserate, v.dose, v.previnterval, v.stat
FROM device d
LEFT JOIN (
  SELECT current.*
  FROM vrecent current
  JOIN (
    SELECT serid, MAX(dtom) AS dtom
    FROM vrecent
    WHERE dtom IS NOT NULL
    GROUP BY serid
  ) newest ON newest.serid = current.serid AND newest.dtom = current.dtom
) v ON v.serid = d.serid
ORDER BY d.location, d.name
"""
                )
                rows = cursor.fetchall()
            keys = (
                "serid", "name", "location", "warnlevel", "alarmlevel", "maxidlemin", "unit",
                "dtom", "doserate", "dose", "previnterval", "stat",
            )
            return [dict(row) if isinstance(row, dict) else dict(zip(keys, row)) for row in rows]
        finally:
            connection.close()

    def latest(self, serid: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT serid, dtom, doserate, dose, previnterval, stat "
                    "FROM vrecent WHERE serid = ? AND dtom IS NOT NULL "
                    "ORDER BY dtom DESC LIMIT 1",
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
