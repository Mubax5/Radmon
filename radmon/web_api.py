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


def _fallback_last_measurement(repository: Any, serid: int) -> dict[str, Any] | None:
    """Fetch last measurement from historical table when recent/vrecent is empty.

    This is the offline-last-known fallback: even year-old measurement must be
    shown so the Perhatian table never displays "—" when history exists.
    """
    try:
        # Prefer `latest` fallback (already does vrecent->measurement)
        latest_fn = getattr(repository, "latest", None)
        if callable(latest_fn):
            try:
                row = latest_fn(int(serid))
                if row and row.get("dtom") is not None and row.get("doserate") is not None:
                    return row
            except Exception:
                pass
        # Direct history fallback (most authoritative, no staleness filter)
        hist_fn = getattr(repository, "history", None)
        if callable(hist_fn):
            rows = hist_fn(int(serid), limit=1)
            if rows:
                row = rows[0]
                if row.get("dtom") is not None and row.get("doserate") is not None:
                    return row
    except Exception:
        pass
    return None


def _station_status(station: dict[str, Any], row: dict[str, Any] | None) -> tuple[str, float | None, Any, str | None]:
    if row is None:
        return "offline", None, None, "Belum ada measurement dari perangkat"
    dose_rate = float(row.get("doserate") or 0.0)
    measured_at = row.get("dtom")
    if _measurement_is_stale(row, station):
        return "offline", dose_rate, measured_at, "Measurement terakhir melewati batas idle perangkat"
    alarm_level = float(station.get("alarmlevel") or 0.0)
    warn_level = float(station.get("warnlevel") or 0.0)
    if alarm_level > 0 and dose_rate >= alarm_level:
        return "alarm", dose_rate, measured_at, None
    if warn_level > 0 and dose_rate >= warn_level:
        return "warning", dose_rate, measured_at, None
    return "normal", dose_rate, measured_at, None


def _station_response(station: dict[str, Any], row: dict[str, Any] | None, source_id: str | None) -> dict[str, Any]:
    status, dose_rate, measured_at, offline_reason = _station_status(station, row)
    description = str(station.get("description") or "")
    return {
        **station,
        "description": description,
        "status": status,
        "doserate": dose_rate,
        "dtom": measured_at,
        "latest_timestamp": measured_at,
        "offline_reason": offline_reason,
        "offline_context": description if status == "offline" else None,
        "offline_description": description if status == "offline" else None,
        "source_id": source_id,
        "ownership": "source" if source_id else "central",
    }


def attach_web_api_routes(
    app: FastAPI,
    *,
    security: SecurityStore,
    repository: Any,
    source_health: Any | None = None,
    event_broker: Any | None = None,
    alarm_policy: Any | None = None,
    alarm_mirror: Any | None = None,
) -> FastAPI:
    """Authenticated read models and lightweight browser refresh events."""

    viewer = require_role(security, Role.VIEWER)
    admin = require_role(security, Role.ADMINISTRATOR)

    def with_policy_status(item: dict[str, Any]) -> dict[str, Any]:
        """Expose the safe current policy projection to authenticated viewers."""
        if alarm_policy is None:
            return item
        try:
            policy = alarm_policy.get_policy(int(item["serid"]))
        except Exception:
            return item
        return {
            **item,
            "policy_state": policy.get("policy_state"),
            "underlying_dose_status": policy.get("underlying_dose_status"),
            "active_event_id": policy.get("active_event_id"),
            "active_event_lifecycle": policy.get("active_event_lifecycle"),
            "last_event_id": policy.get("last_event_id"),
            "last_event_status": policy.get("last_event_status"),
            "last_event_resolved_at": policy.get("last_event_resolved_at"),
            "policy_measured_value": policy.get("measured_value"),
            "policy_threshold": policy.get("threshold"),
        }

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
                    for key in ("serid", "name", "location", "description", "warnlevel", "alarmlevel", "maxidlemin", "unit")
                }
                row = None if snapshot.get("dtom") is None else snapshot
                # Offline-last-known fallback: if snapshot has no dtom but history exists,
                # use last measurement so dose/diPerbarui never hides.
                if row is None:
                    fallback = _fallback_last_measurement(repository, int(station["serid"]))
                    if fallback is not None:
                        row = fallback
                station_rows.append((station, row))
        else:
            # No snapshot reader (e.g., legacy repo): rely on repository.latest
            # which already falls back to measurement. Do not invent history
            # fallback here that would resurrect dummy test data for stations
            # that truly have no measurement (e.g., 5203 in test_web_api).
            station_rows = [
                (station, repository.latest(int(station["serid"])))
                for station in repository.stations()
            ]

        source_map = security.station_source_ids_map()
        for station, row in station_rows:
            source_ids = source_map.get(int(station["serid"]), ())
            item = with_policy_status(_station_response(station, row, ", ".join(source_ids) or None))
            counts[item["status"]] += 1
            items.append(item)
        return {"counts": counts, "stations": items, "role": identity.role.value}

    @app.get("/api/v1/web/stations")
    def stations(identity: UserIdentity = Depends(viewer)):
        source_map = security.station_source_ids_map()
        return [
            with_policy_status(_station_response(
                station,
                _fallback_last_measurement(repository, int(station["serid"])),
                ", ".join(source_map.get(int(station["serid"]), ())) or None,
            ))
            for station in repository.stations()
        ]

    @app.get("/api/v1/web/stations/{serid}")
    def station_detail(serid: int, identity: UserIdentity = Depends(viewer)):
        station = next((row for row in repository.stations() if int(row["serid"]) == int(serid)), None)
        if station is None:
            raise HTTPException(status_code=404, detail="station tidak ditemukan")
        source_ids = security.station_source_ids_map().get(int(serid), ())
        return with_policy_status(_station_response(
            station,
            _fallback_last_measurement(repository, int(serid)),
            ", ".join(source_ids) or None,
        ))

    @app.get("/api/v1/web/stations/{serid}/history")
    def station_history(
        serid: int,
        limit: int = Query(default=240, ge=1, le=2000),
        identity: UserIdentity = Depends(viewer),
    ):
        return repository.history(serid, limit=limit)

    @app.get("/api/v1/web/alarm-history")
    def alarm_history(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), identity: UserIdentity = Depends(viewer)):
        """Paginated merged source alarm rows and central policy lifecycle."""
        source_fields = {"source_id", "serid", "remote_serid", "event_time", "level", "measured_value", "threshold", "hit_count", "is_active", "source_i_flag", "source_observed_at", "source_observation_version"}
        policy_fields = {"event_id", "source_id", "serid", "remote_serid", "remote_event_time", "surfaced_at", "event_time", "kind", "status", "reason", "resolution_code", "measured_value", "threshold", "hit_count", "policy_decision"}

        def project(raw: dict[str, Any], fields: set[str]) -> dict[str, Any]:
            return {key: raw[key] for key in fields if key in raw}

        sources = []
        if alarm_mirror is not None:
            for raw in alarm_mirror.list_alarms(limit=5000):
                raw_item = dict(raw)
                item = project(raw_item, source_fields)
                if "source_i_flag" not in item and "i_flag" in raw_item:
                    item["source_i_flag"] = raw_item["i_flag"]
                item.update({"event_type": "source_alarm", "status": "ACTIVE" if item.get("is_active") else "ACKNOWLEDGED", "acknowledged": bool(raw_item.get("acknowledged_at")) or not bool(item.get("is_active")), "suppressed": False})
                sources.append(item)
        policies = []
        if alarm_policy is not None:
            for raw in alarm_policy.list_events(limit=5000):
                item = project(dict(raw), policy_fields)
                item.update({"event_type": "policy_lifecycle", "event_time": item.get("surfaced_at"), "acknowledged": item.get("status") == "RESPONDED", "suppressed": item.get("kind") == "SUPPRESSED"})
                policies.append(item)

        def time_key(item):
            value = item.get("event_time") or item.get("surfaced_at")
            return value.isoformat() if isinstance(value, datetime) else str(value or "")

        def as_datetime(value):
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return None
            return None

        merged = list(sources)
        for item in policies:
            remote_time = item.get("remote_event_time")
            policy_time = as_datetime(remote_time)
            candidates = []
            if policy_time is not None and item.get("source_id") is not None and item.get("remote_serid") is not None:
                for source in sources:
                    source_time = as_datetime(source.get("event_time"))
                    if (str(source.get("source_id")) == str(item.get("source_id"))
                            and int(source.get("serid") or -1) == int(item.get("serid") or -1)
                            and int(source.get("remote_serid") or -1) == int(item.get("remote_serid") or -1)
                            and source_time is not None):
                        try:
                            delta = abs((source_time - policy_time).total_seconds())
                        except TypeError:
                            delta = abs((source_time.replace(tzinfo=None) - policy_time.replace(tzinfo=None)).total_seconds())
                        if delta <= 5:
                            candidates.append((delta, source))
            candidates.sort(key=lambda pair: pair[0])
            source = candidates[0][1] if candidates and (len(candidates) == 1 or candidates[0][0] < candidates[1][0]) else None
            if source is not None:
                source["policy_event"] = item
                source["status"] = item.get("status")
            else:
                merged.append(item)
        merged.sort(key=time_key, reverse=True)
        total = len(merged)
        return {"items": merged[offset:offset + limit], "total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}

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
