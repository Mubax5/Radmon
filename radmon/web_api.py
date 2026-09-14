from __future__ import annotations

from datetime import datetime, timedelta
import json
import queue
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .security import Role, SecurityStore, UserIdentity
from .secure_api import SESSION_COOKIE


ROLE_RANK = {
    Role.VIEWER: 1,
    Role.OPERATOR: 2,
    Role.ADMINISTRATOR: 3,
}


def require_role(security: SecurityStore, minimum: Role) -> Callable[[Request], UserIdentity]:
    """Return a server-side role dependency; browser-supplied roles are ignored."""
    def dependency(request: Request) -> UserIdentity:
        identity = security.session_user(request.cookies.get(SESSION_COOKIE))
        if identity is None:
            raise HTTPException(status_code=401, detail="authentication required")
        if ROLE_RANK[identity.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail=f"{minimum.value} required")
        return identity

    return dependency


def _measurement_is_stale(row: dict[str, Any], station: dict[str, Any]) -> bool:
    """Apply device max-idle semantics when that metadata is available."""
    if "maxidlemin" not in station:
        return False

    measured_at = row.get("dtom")
    if isinstance(measured_at, str):
        try:
            measured_at = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
        except ValueError:
            return True
    if not isinstance(measured_at, datetime):
        return True

    try:
        max_idle_minutes = max(1, int(station.get("maxidlemin") or 30))
    except (TypeError, ValueError):
        max_idle_minutes = 30

    now = datetime.now(measured_at.tzinfo) if measured_at.tzinfo is not None else datetime.now()
    return (now - measured_at) > timedelta(minutes=max_idle_minutes)


def attach_web_api_routes(
    app: FastAPI,
    *,
    security: SecurityStore,
    repository: Any,
    source_health: Any | None = None,
    event_broker: Any | None = None,
) -> FastAPI:
    """Authenticated read models and lightweight browser refresh events."""

    viewer = require_role(security, Role.VIEWER)
    admin = require_role(security, Role.ADMINISTRATOR)

    @app.get("/api/v1/web/overview")
    def overview(identity: UserIdentity = Depends(viewer)):
        items: list[dict[str, Any]] = []
        counts = {"normal": 0, "warning": 0, "alarm": 0, "offline": 0}
        snapshot_reader = getattr(repository, "overview_rows", None)
        if callable(snapshot_reader):
            snapshots = snapshot_reader()
            station_rows = []
            for snapshot in snapshots:
                station = {
                    key: snapshot.get(key)
                    for key in ("serid", "name", "location", "warnlevel", "alarmlevel", "maxidlemin", "unit")
                }
                row = None if snapshot.get("dtom") is None else snapshot
                station_rows.append((station, row))
        else:
            station_rows = [
                (station, repository.latest(int(station["serid"])))
                for station in repository.stations()
            ]

        for station, row in station_rows:
            status = "offline"
            dose_rate = None
            measured_at = None
            if row is not None:
                dose_rate = float(row.get("doserate") or 0.0)
                measured_at = row.get("dtom")
                if _measurement_is_stale(row, station):
                    status = "offline"
                elif dose_rate >= float(station.get("alarmlevel") or 0.0):
                    status = "alarm"
                elif dose_rate >= float(station.get("warnlevel") or 0.0):
                    status = "warning"
                else:
                    status = "normal"
            counts[status] += 1
            items.append({**station, "status": status, "doserate": dose_rate, "dtom": measured_at})
        return {"counts": counts, "stations": items, "role": identity.role.value}

    @app.get("/api/v1/web/stations")
    def stations(identity: UserIdentity = Depends(viewer)):
        return repository.stations()

    @app.get("/api/v1/web/stations/{serid}/history")
    def station_history(
        serid: int,
        limit: int = Query(default=240, ge=1, le=2000),
        identity: UserIdentity = Depends(viewer),
    ):
        return repository.history(serid, limit=limit)

    @app.get("/api/v1/web/events")
    def web_events(identity: UserIdentity = Depends(viewer)):
        if event_broker is None:
            raise HTTPException(status_code=503, detail="web event stream unavailable")
        subscriber = event_broker.subscribe()

        def stream():
            try:
                yield 'event: ready\ndata: {"type":"ready"}\n\n'
                while True:
                    try:
                        event = subscriber.get(timeout=15.0)
                    except queue.Empty:
                        yield ": heartbeat\n\n"
                        continue
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {payload}\n\n"
            finally:
                event_broker.unsubscribe(subscriber)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/v1/web/system")
    def system(identity: UserIdentity = Depends(admin)):
        sources = source_health.list_states() if source_health is not None else []
        return {
            "service": "radmon-central",
            "role": identity.role.value,
            "sources": sources,
            "grafana_admin_url": "http://localhost:3300",
        }

    return app
