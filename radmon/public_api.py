from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings
from .status import classify_status, trend_code, trend_symbol


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def latest_payload(repository: Any, settings: Settings) -> dict[str, Any]:
    reading = repository.latest_reading(settings.serid)
    station = reading.station
    now = datetime.now()
    status = classify_status(
        reading.dose_rate,
        reading.measured_at,
        now,
        station.warnlevel,
        station.alarmlevel,
        station.maxidlemin,
    )
    trend = "OFFLINE" if status.value == "OFFLINE" else trend_code(reading.dose_rate, reading.previous_dose_rate)
    age_seconds = None
    if reading.measured_at is not None:
        age_seconds = max(0, int((now - reading.measured_at).total_seconds()))
    return {
        "serid": station.serid,
        "building": station.building,
        "room": station.room,
        "location": station.location,
        "label": f"[{station.serid}] {station.room} (Gd. {station.building})",
        "dose_rate": reading.dose_rate,
        "unit": station.unit,
        "status": status.value,
        "trend": trend,
        "trend_symbol": trend_symbol(trend),
        "last_update": reading.measured_at.strftime("%Y-%m-%d %H:%M:%S") if reading.measured_at else None,
        "age_seconds": age_seconds,
        "warnlevel": station.warnlevel,
        "alarmlevel": station.alarmlevel,
        "maxidlemin": station.maxidlemin,
    }


def create_public_app(repository: Any, settings: Settings) -> FastAPI:
    root = _project_root()
    templates = Jinja2Templates(directory=str(root / "monitoring/templates"))
    app = FastAPI(title="Radmon DPFK Public Monitoring", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(root / "monitoring/static")), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/latest")
    def api_latest() -> dict[str, Any]:
        return latest_payload(repository, settings)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"settings": settings, "initial": latest_payload(repository, settings)},
        )

    return app
