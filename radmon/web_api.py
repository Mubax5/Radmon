from __future__ import annotations

from datetime import datetime, timedelta
import json
import queue
import sqlite3
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


def _offline_last_readings(repository: Any, serid: int, *, limit: int) -> list[dict[str, Any]] | None:
    """Use the bounded cache only for an offline station.

    Online History keeps its existing historical query contract. Once the
    latest station sample is stale, the UI receives up to N genuine samples
    from ``recent_last`` instead of causing an unbounded historical fallback.
    """
    cache_fn = getattr(repository, "last_readings", None)
    if not callable(cache_fn):
        return None
    station: dict[str, Any] | None = None
    snapshot_fn = getattr(repository, "overview_rows", None)
    if callable(snapshot_fn):
        try:
            station = next(
                (dict(item) for item in snapshot_fn() if int(item.get("serid")) == int(serid)),
                None,
            )
        except Exception:
            station = None
    if station is None:
        stations_fn = getattr(repository, "stations", None)
        if callable(stations_fn):
            try:
                station = next(
                    (dict(item) for item in stations_fn() if int(item.get("serid")) == int(serid)),
                    None,
                )
            except Exception:
                station = None
    if station is None:
        return None

    row = None
    if station.get("dtom") is not None:
        row = station
    else:
        latest_fn = getattr(repository, "latest", None)
        if callable(latest_fn):
            try:
                row = latest_fn(int(serid))
            except Exception:
                row = None
    status, _dose_rate, _measured_at, _reason = _station_status(station, row)
    if status != "offline":
        return None
    try:
        rows = cache_fn(int(serid), limit=limit)
    except Exception:
        return None
    return list(rows) if rows else None


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
    age_seconds = None
    age_label = None
    if measured_at is not None:
        parsed = measured_at
        if isinstance(parsed, str):
            try:
                parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        if isinstance(parsed, datetime):
            now = datetime.now(parsed.tzinfo) if parsed.tzinfo is not None else datetime.now()
            age_seconds = max(0, int((now - parsed).total_seconds()))
            if age_seconds < 60:
                age_label = f"{age_seconds} detik"
            elif age_seconds < 3600:
                age_label = f"{age_seconds // 60} menit"
            elif age_seconds < 86400:
                age_label = f"{age_seconds // 3600} jam"
            else:
                age_label = f"{age_seconds // 86400} hari"
    return {
        **station,
        "description": description,
        "status": status,
        "doserate": dose_rate,
        "dtom": measured_at,
        "latest_timestamp": measured_at,
        "last_data_age_seconds": age_seconds,
        "last_data_age_label": age_label,
        "last_reading_source": "historical-measurement" if measured_at is not None else None,
        "offline_reason": offline_reason,
        "offline_context": description if status == "offline" else None,
        "offline_description": description if status == "offline" else None,
        "source_id": source_id,
        "ownership": "source" if source_id else "central",
    }


_SOURCE_FIELDS = {
    "source_id", "serid", "remote_serid", "event_time", "level",
    "measured_value", "threshold", "hit_count", "is_active", "source_i_flag",
    "source_observed_at", "source_observation_version",
}
_VIEWER_POLICY_FIELDS = {
    "event_id", "source_id", "serid", "remote_serid", "remote_event_time",
    "surfaced_at", "event_time", "kind", "status", "resolution_code",
    "resolved_at", "measured_value", "threshold", "hit_count", "policy_decision",
    "suppression_id",
}
_PRIVILEGED_POLICY_FIELDS = _VIEWER_POLICY_FIELDS | {
    "resolution_reason",
}


def _project_alarm_response(raw: dict[str, Any], *, privileged: bool) -> dict[str, Any]:
    """Expose persisted response fields only to operator/admin identities."""
    if not privileged:
        return {}
    return {
        "response_actor": raw.get("pic"),
        "response_action": raw.get("action"),
        "response_note": raw.get("note"),
        "acknowledged_at": raw.get("acknowledged_at"),
    }


def _project_policy_response(raw: dict[str, Any], *, privileged: bool) -> dict[str, Any]:
    if not privileged:
        return {}
    # ``reason`` is also used for the original central trigger reason. It is
    # an operator note only after a persisted policy response was recorded.
    responded = raw.get("responded_at") is not None or raw.get("status") == "RESPONDED"
    return {
        "response_actor": raw.get("pic"),
        "response_action": raw.get("action"),
        "response_note": raw.get("reason") if responded else None,
        "acknowledged_at": raw.get("responded_at"),
    }


def _canonical_station_metadata(
    repository: Any,
    security: SecurityStore,
    *,
    serid: Any,
    source_id: Any = None,
    remote_serid: Any = None,
) -> dict[str, Any]:
    """Return station labels only after canonical source ownership checks."""
    try:
        central_serid = int(serid)
    except (TypeError, ValueError):
        return {}
    stations_fn = getattr(repository, "stations", None)
    if not callable(stations_fn):
        return {}
    try:
        station = next(
            (dict(item) for item in stations_fn() if int(item.get("serid")) == central_serid),
            None,
        )
    except (TypeError, ValueError, KeyError):
        return {}
    if station is None:
        return {}

    if source_id is not None:
        source_text = str(source_id)
        if remote_serid is not None:
            binding_fn = getattr(security, "station_binding", None)
            if callable(binding_fn):
                try:
                    if binding_fn(source_text, int(remote_serid)) != central_serid:
                        return {}
                except (TypeError, ValueError, sqlite3.Error):
                    return {}
            else:
                try:
                    bound_sources = security.station_source_ids_map().get(central_serid, ())
                except Exception:
                    return {}
                if source_text not in {str(value) for value in bound_sources}:
                    return {}
        else:
            try:
                bound_sources = security.station_source_ids_map().get(central_serid, ())
            except Exception:
                return {}
            if source_text not in {str(value) for value in bound_sources}:
                return {}

    return {
        "station_name": station.get("name"),
        "location": station.get("location"),
        "unit": station.get("unit"),
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
        cached = _offline_last_readings(repository, serid, limit=limit)
        if cached is not None:
            return cached
        history_fn = getattr(repository, "history", None)
        if callable(history_fn):
            return history_fn(serid, limit=limit)
        last_readings_fn = getattr(repository, "last_readings", None)
        if callable(last_readings_fn):
            return last_readings_fn(serid, limit=limit)
        raise HTTPException(status_code=503, detail="station history is unavailable")

    @app.get("/api/v1/web/active-alarms")
    def current_alarms(identity: UserIdentity = Depends(viewer)):
        from .active_alarms import active_alarm_snapshot
        try:
            snapshot = active_alarm_snapshot(alarm_mirror, alarm_policy)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        privileged = identity.role in {Role.OPERATOR, Role.ADMINISTRATOR}

        def enrich_active(item: dict[str, Any]) -> dict[str, Any]:
            result = dict(item)
            result.update(_canonical_station_metadata(
                repository,
                security,
                serid=result.get("serid"),
                source_id=result.get("source_id"),
                remote_serid=result.get("remote_serid"),
            ))
            # Active rows normally have no response yet, but preserve the
            # explicit role boundary if an adapter supplies persisted fields.
            response = _project_alarm_response(result, privileged=privileged)
            for field in ("pic", "note", "action", "operator", "operator_id", "user_id"):
                result.pop(field, None)
            if privileged:
                result.update(response)
            return result

        for key in ("items", "source_items"):
            snapshot[key] = [enrich_active(dict(item)) for item in snapshot.get(key, [])]
        return {
            **snapshot,
            "total": len(snapshot["items"]),
            "observed_at": datetime.now().astimezone(),
        }

    @app.get("/api/v1/web/alarm-history")
    def alarm_history(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=1000000), identity: UserIdentity = Depends(viewer)):
        """Paginated merged source alarm rows and central policy lifecycle."""
        privileged = identity.role in {Role.OPERATOR, Role.ADMINISTRATOR}

        # Viewer history is an operational read model, not an operator journal.
        # Operator/admin detail gets only the explicitly renamed persisted
        # response fields; raw PIC/note/action/user IDs never cross this route.
        def project_source(raw: dict[str, Any]) -> dict[str, Any]:
            item = {key: raw[key] for key in _SOURCE_FIELDS if key in raw}
            if "source_i_flag" not in item and "i_flag" in raw:
                item["source_i_flag"] = raw["i_flag"]
            try:
                source_i_flag = int(item.get("source_i_flag")) if item.get("source_i_flag") is not None else None
            except (TypeError, ValueError):
                source_i_flag = None
            if source_i_flag in (0, 1):
                item["source_i_flag"] = source_i_flag
                item["is_active"] = source_i_flag == 0
            if privileged:
                item.update(_project_alarm_response(raw, privileged=True))
            return item

        def project_policy(raw: dict[str, Any]) -> dict[str, Any]:
            fields = _PRIVILEGED_POLICY_FIELDS if privileged else _VIEWER_POLICY_FIELDS
            item = {key: raw[key] for key in fields if key in raw}
            if privileged:
                item.update(_project_policy_response(raw, privileged=True))
            return item

        def station_fields(item: dict[str, Any]) -> dict[str, Any]:
            return _canonical_station_metadata(
                repository,
                security,
                serid=item.get("serid"),
                source_id=item.get("source_id"),
                remote_serid=item.get("remote_serid"),
            )

        def enrich(item: dict[str, Any]) -> dict[str, Any]:
            result = dict(item)
            result.update(station_fields(result))
            nested = result.get("policy_event")
            if isinstance(nested, dict):
                nested_item = dict(nested)
                nested_item.update(station_fields(nested_item))
                result["policy_event"] = nested_item
            return result

        sources = []
        if alarm_mirror is not None:
            for raw in alarm_mirror.list_alarms(limit=5000):
                raw_item = dict(raw)
                item = project_source(raw_item)
                # The source latch is the physical alarm truth.  A policy event
                # may be auto-resolved after a normal reading, but it cannot
                # rewrite an i_flag=0 source alarm or make i_flag=1 look active.
                source_active = bool(item.get("is_active"))
                item.update({"event_type": "source_alarm", "status": "ACTIVE" if source_active else "ACKNOWLEDGED", "surfaced_at": item.get("event_time"), "acknowledged": bool(raw_item.get("acknowledged_at")) or not source_active, "suppressed": False})
                sources.append(enrich(item))
        policies = []
        if alarm_policy is not None:
            for raw in alarm_policy.list_events(limit=5000):
                raw_item = dict(raw)
                item = project_policy(raw_item)
                item.update({"event_type": "policy_lifecycle", "event_time": item.get("surfaced_at"), "acknowledged": item.get("status") == "RESPONDED", "suppressed": item.get("kind") == "SUPPRESSED"})
                policies.append(enrich(item))

        policy_store = getattr(alarm_policy, "store", None) if alarm_policy is not None else None
        list_suppressions = getattr(policy_store, "list_suppressions", None)
        if callable(list_suppressions):
            suppression_rows = []
            known_ends = {
                str(item.get("suppression_id"))
                for item in policies
                if item.get("kind") == "SUPPRESSION_END" and item.get("suppression_id")
            }

            def add_persisted_suppression_times(item: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
                """Copy only timestamps/duration that exist in storage.

                In particular, an expired row without ``ended_at`` remains an
                open historical record. The API must not turn the current
                clock or ``expires_at`` into a fabricated resolution.
                """
                started_at = raw.get("started_at")
                expires_at = raw.get("expires_at")
                ended_at = raw.get("ended_at")
                if started_at is not None:
                    item.update({"started_at": started_at, "suppression_started_at": started_at})
                if expires_at is not None:
                    item.update({"expires_at": expires_at, "suppression_expires_at": expires_at})
                if ended_at is not None:
                    item.update({"ended_at": ended_at, "suppression_ended_at": ended_at})
                if raw.get("duration_seconds") is not None:
                    item["duration_seconds"] = raw["duration_seconds"]
                return item

            for suppression in list_suppressions(limit=5000):
                raw = dict(suppression) if isinstance(suppression, dict) else {
                    key: getattr(suppression, key)
                    for key in (
                        "suppression_id", "serid", "started_at", "expires_at", "ended_at",
                        "ended_reason", "reason", "pic", "started_by", "ended_by",
                    )
                }
                suppression_id = str(raw.get("suppression_id") or "")
                start_at = raw.get("started_at")
                if start_at is not None:
                    start_item = {
                        "event_id": f"suppression-start:{suppression_id}", "suppression_id": suppression_id,
                        "serid": int(raw["serid"]), "event_type": "policy_lifecycle",
                        "event_time": start_at, "surfaced_at": start_at, "kind": "SUPPRESSION_START",
                        "status": "SUPPRESSED",
                        "acknowledged": False, "suppressed": True,
                    }
                    add_persisted_suppression_times(start_item, raw)
                    if privileged:
                        start_item.update({
                            "response_actor": raw.get("pic"),
                            "response_note": raw.get("reason"),
                        })
                    suppression_rows.append(enrich(start_item))
                ended_at = raw.get("ended_at")
                ended_reason = raw.get("ended_reason")
                if ended_at is not None and suppression_id not in known_ends:
                    end_reason = str(ended_reason or "EXPIRED")
                    end_item = {
                        "event_id": f"suppression-end:{suppression_id}", "suppression_id": suppression_id,
                        "serid": int(raw["serid"]), "event_type": "policy_lifecycle",
                        "event_time": ended_at, "surfaced_at": ended_at, "kind": "SUPPRESSION_END",
                        "status": "ENDED",
                        "acknowledged": False, "suppressed": False,
                    }
                    add_persisted_suppression_times(end_item, raw)
                    if privileged:
                        end_item.update({
                            "response_actor": raw.get("ended_by") or raw.get("pic"),
                            "response_action": end_reason.split(":", 1)[0],
                            "response_note": end_reason,
                        })
                    suppression_rows.append(enrich(end_item))
            policies.extend(suppression_rows)

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
