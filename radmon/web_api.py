from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, Request

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


def attach_web_api_routes(
    app: FastAPI,
    *,
    security: SecurityStore,
    repository: Any,
    source_health: Any | None = None,
) -> FastAPI:
    """Authenticated read models for the browser UI."""

    viewer = require_role(security, Role.VIEWER)
    admin = require_role(security, Role.ADMINISTRATOR)

    @app.get("/api/v1/web/overview")
    def overview(identity: UserIdentity = Depends(viewer)):
        items: list[dict[str, Any]] = []
        counts = {"normal": 0, "warning": 0, "alarm": 0, "offline": 0}
        for station in repository.stations():
            row = repository.latest(int(station["serid"]))
            status = "offline"
            dose_rate = None
            measured_at = None
            if row is not None:
                dose_rate = float(row.get("doserate") or 0.0)
                measured_at = row.get("dtom")
                if dose_rate >= float(station.get("alarmlevel") or 0.0):
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
