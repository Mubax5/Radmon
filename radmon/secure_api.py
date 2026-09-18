from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from .audit import AuditTrail
from .remote_alarm import RemoteAlarmMirror
from .security import Role, SecurityError, SecurityStore, UserIdentity


SESSION_COOKIE = "radmon_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
STATION_EDIT_FIELDS = frozenset({
    "name", "location", "description", "warnlevel", "alarmlevel", "maxidlemin",
})


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AckRequest(BaseModel):
    event_time: datetime
    action: str = Field(min_length=1, max_length=128)
    pic: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=1000)
    pin: str = Field(min_length=4, max_length=8)


class SuppressionRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    duration_seconds: int = Field(ge=60, le=86400)
    pic: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    auto_resume_on_normal: bool = True


class SuppressionCancelRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    reason: str = Field(min_length=1, max_length=1000)


class PolicyResponseRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    action: str = Field(min_length=1, max_length=128)
    pic: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=1000)


class StationUpdateRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    changes: dict[str, Any]


class StationCreateRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    serid: int = Field(gt=0)
    values: dict[str, Any]


class PinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


class CreateUserRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    role: Role
    password: str = Field(min_length=8, max_length=256)
    user_pin: str = Field(min_length=4, max_length=8)


class UpdateUserRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: Role | None = None


class UserEnabledRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    enabled: bool


class ResetPasswordRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    password: str = Field(min_length=8, max_length=256)


class ResetPinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    new_pin: str = Field(min_length=4, max_length=8)


class ReportCreateRequest(BaseModel):
    serid: int = Field(gt=0)
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def validate_range(self):
        start = self.start_at if self.start_at.tzinfo else self.start_at.replace(tzinfo=timezone.utc)
        end = self.end_at if self.end_at.tzinfo else self.end_at.replace(tzinfo=timezone.utc)
        if end <= start:
            raise ValueError("report end must be after start")
        if end - start > timedelta(days=366):
            raise ValueError("rentang report terlalu panjang")
        return self


class ArchiveRetryRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


def _report_response(item: dict[str, Any]) -> dict[str, Any]:
    """Return only browser-safe persisted job metadata, never owner internals."""
    fields = (
        "job_id", "serid", "start_at", "end_at", "status", "artifact_name",
        "error", "created_at", "completed_at",
    )
    return {field: item.get(field) for field in fields}


def attach_secure_routes(
    app: FastAPI,
    *,
    security: SecurityStore,
    audit: AuditTrail,
    alarm_mirror: RemoteAlarmMirror,
    alarm_control: Any,
    device_admin: Any,
    user_admin: Any | None = None,
    report_jobs: Any | None = None,
    cookie_secure: bool = False,
    archive_catalog: Any | None = None,
    archive_service: Any | None = None,
    source_health: Any | None = None,
    alarm_policy: Any | None = None,
    alarm_suppression: Any | None = None,
) -> FastAPI:
    def current_user(request: Request) -> UserIdentity:
        identity = security.session_user(request.cookies.get(SESSION_COOKIE))
        if identity is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return identity

    def require_operator(identity: UserIdentity = Depends(current_user)) -> UserIdentity:
        if not security.role_allows(identity.role, "ack_alarm"):
            raise HTTPException(status_code=403, detail="operator permission required")
        return identity

    def require_admin(identity: UserIdentity = Depends(current_user)) -> UserIdentity:
        if identity.role is not Role.ADMINISTRATOR:
            raise HTTPException(status_code=403, detail="administrator required")
        return identity

    def require_station_editor(identity: UserIdentity = Depends(current_user)) -> UserIdentity:
        if not security.role_allows(identity.role, "edit_station"):
            raise HTTPException(status_code=403, detail="station editor permission required")
        return identity

    def user_error(exc: Exception) -> HTTPException:
        if isinstance(exc, SecurityError):
            return HTTPException(status_code=403, detail=str(exc))
        if isinstance(exc, sqlite3.IntegrityError):
            return HTTPException(status_code=409, detail="username sudah digunakan")
        if isinstance(exc, ValueError):
            detail = str(exc)
            if detail == "user tidak ditemukan":
                return HTTPException(status_code=404, detail=detail)
            if "terakhir" in detail or "sedang dipakai" in detail:
                return HTTPException(status_code=409, detail=detail)
            return HTTPException(status_code=422, detail=detail)
        return HTTPException(status_code=409, detail="perubahan pengguna tidak dapat disimpan")

    @app.post("/auth/login")
    def login(payload: LoginRequest, response: Response):
        identity = security.authenticate(payload.username, payload.password)
        if identity is None:
            audit.record(
                "LOGIN_FAILED", None, "user", payload.username.strip().lower(),
                success=False, reason="invalid credentials",
            )
            raise HTTPException(status_code=401, detail="invalid credentials")
        token = security.create_session(identity.username, SESSION_TTL_SECONDS)
        response.set_cookie(
            SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS,
            httponly=True, secure=cookie_secure, samesite="strict", path="/",
        )
        audit.record("LOGIN_SUCCESS", identity, "user", identity.username)
        return {
            "username": identity.username,
            "display_name": identity.display_name,
            "role": identity.role.value,
        }

    @app.post("/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE)
        identity = security.session_user(token)
        security.revoke_session(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        audit.record("LOGOUT", identity, "user", identity.username if identity else None)
        return {"status": "ok"}

    @app.get("/auth/me")
    def me(identity: UserIdentity = Depends(current_user)):
        return {
            "username": identity.username,
            "display_name": identity.display_name,
            "role": identity.role.value,
        }

    # Compatibility raw-alarm route remains intentionally available for
    # diagnostics/history. Operator-facing alarm workflow uses policy events.
    @app.get("/api/v1/control/alarms")
    def alarms(identity: UserIdentity = Depends(current_user)):
        return alarm_mirror.list_alarms(limit=500)

    @app.get("/api/v1/control/alarm-events")
    def alarm_events(identity: UserIdentity = Depends(require_operator)):
        if alarm_policy is None:
            raise HTTPException(status_code=404, detail="alarm policy unavailable")
        return alarm_policy.list_events(limit=500)

    @app.get("/api/v1/control/alarm-policy/{serid}")
    def alarm_policy_status(serid: int, identity: UserIdentity = Depends(require_operator)):
        if alarm_policy is None:
            raise HTTPException(status_code=404, detail="alarm policy unavailable")
        try:
            return alarm_policy.get_policy(serid)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/control/alarm-events/{event_id}/response")
    def respond_policy_event(
        event_id: str,
        payload: PolicyResponseRequest,
        identity: UserIdentity = Depends(require_operator),
    ):
        if alarm_policy is None:
            raise HTTPException(status_code=404, detail="alarm policy unavailable")
        try:
            return alarm_control.respond_policy_event(
                identity, payload.pin, event_id,
                action=payload.action, pic=payload.pic, reason=payload.reason,
            )
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            code = 404 if "tidak ditemukan" in str(exc).lower() else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.get("/api/v1/control/suppressions")
    def suppressions(active_only: bool = False, identity: UserIdentity = Depends(require_operator)):
        if alarm_suppression is None:
            raise HTTPException(status_code=404, detail="alarm suppression unavailable")
        return alarm_suppression.list(active_only=active_only)

    @app.post("/api/v1/control/suppressions/{serid}")
    def start_suppression(
        serid: int,
        payload: SuppressionRequest,
        identity: UserIdentity = Depends(require_operator),
    ):
        if alarm_suppression is None:
            raise HTTPException(status_code=404, detail="alarm suppression unavailable")
        try:
            return alarm_suppression.start(
                identity,
                payload.pin,
                serid,
                payload.duration_seconds,
                payload.pic,
                payload.reason,
                payload.auto_resume_on_normal,
            )
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/control/suppressions/{suppression_id}/cancel")
    def cancel_suppression(
        suppression_id: str,
        payload: SuppressionCancelRequest,
        identity: UserIdentity = Depends(require_operator),
    ):
        if alarm_suppression is None:
            raise HTTPException(status_code=404, detail="alarm suppression unavailable")
        try:
            return alarm_suppression.cancel(identity, payload.pin, suppression_id, payload.reason)
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            code = 404 if "tidak ditemukan" in str(exc).lower() else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.get("/api/v1/control/sources/health")
    def sources_health(identity: UserIdentity = Depends(current_user)):
        if source_health is None:
            return []
        return source_health.list_states()

    @app.post("/api/v1/control/alarms/{source_id}/{serid}/ack")
    def ack_alarm(
        source_id: str,
        serid: int,
        payload: AckRequest,
        identity: UserIdentity = Depends(require_operator),
    ):
        try:
            return alarm_control.ack(
                identity, payload.pin, source_id, serid, payload.event_time,
                action=payload.action, pic=payload.pic, note=payload.note,
            )
        except (PermissionError, SecurityError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/control/stations/{serid}")
    def update_station(
        serid: int,
        payload: StationUpdateRequest,
        identity: UserIdentity = Depends(require_station_editor),
    ):
        disallowed = set(payload.changes) - STATION_EDIT_FIELDS
        if disallowed:
            raise HTTPException(
                status_code=422,
                detail="field station tidak diizinkan: " + ", ".join(sorted(disallowed)),
            )
        try:
            return device_admin.update_station(identity, payload.pin, serid, payload.changes)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/control/stations")
    def create_station(payload: StationCreateRequest, identity: UserIdentity = Depends(require_station_editor)):
        disallowed = set(payload.values) - STATION_EDIT_FIELDS
        if disallowed:
            raise HTTPException(
                status_code=422,
                detail="field station tidak diizinkan: " + ", ".join(sorted(disallowed)),
            )
        try:
            return device_admin.create_station(identity, payload.pin, payload.serid, payload.values)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/v1/control/stations/{serid}")
    def delete_station(serid: int, payload: PinRequest, identity: UserIdentity = Depends(require_station_editor)):
        try:
            device_admin.delete_station(identity, payload.pin, serid)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "deleted", "serid": serid}

    @app.get("/api/v1/control/users")
    def users(identity: UserIdentity = Depends(require_admin)):
        return security.list_users()

    @app.post("/api/v1/control/users")
    def create_user(
        payload: CreateUserRequest,
        identity: UserIdentity = Depends(require_admin),
    ):
        from .user_admin import UserAdminService
        manager = user_admin or UserAdminService(security, audit)
        try:
            created = manager.create_user(
                identity, payload.pin, payload.username, payload.display_name,
                payload.role, payload.password, payload.user_pin,
            )
        except Exception as exc:
            raise user_error(exc) from exc
        return security.get_user(created.username)

    def user_manager():
        from .user_admin import UserAdminService
        return user_admin or UserAdminService(security, audit)

    @app.patch("/api/v1/control/users/{username}")
    def update_user(username: str, payload: UpdateUserRequest, identity: UserIdentity = Depends(require_admin)):
        try:
            return user_manager().update_user(identity, payload.pin, username, display_name=payload.display_name, role=payload.role)
        except Exception as exc:
            raise user_error(exc) from exc

    @app.post("/api/v1/control/users/{username}/enabled")
    def set_user_enabled(username: str, payload: UserEnabledRequest, identity: UserIdentity = Depends(require_admin)):
        try:
            user_manager().set_enabled(identity, payload.pin, username, payload.enabled)
            return security.get_user(username)
        except Exception as exc:
            raise user_error(exc) from exc

    @app.post("/api/v1/control/users/{username}/password")
    def reset_user_password(username: str, payload: ResetPasswordRequest, identity: UserIdentity = Depends(require_admin)):
        try:
            user_manager().reset_password(identity, payload.pin, username, payload.password)
        except Exception as exc:
            raise user_error(exc) from exc
        return {"status": "reset"}

    @app.post("/api/v1/control/users/{username}/pin")
    def reset_user_pin(username: str, payload: ResetPinRequest, identity: UserIdentity = Depends(require_admin)):
        try:
            user_manager().reset_pin(identity, payload.pin, username, payload.new_pin)
        except Exception as exc:
            raise user_error(exc) from exc
        return {"status": "reset"}

    @app.delete("/api/v1/control/users/{username}")
    def delete_user(username: str, payload: PinRequest, identity: UserIdentity = Depends(require_admin)):
        try:
            user_manager().delete_user(identity, payload.pin, username)
        except Exception as exc:
            raise user_error(exc) from exc
        return {"status": "deactivated", "user": security.get_user(username)}

    @app.get("/api/v1/control/reports")
    def reports(identity: UserIdentity = Depends(require_operator)):
        if report_jobs is None:
            raise HTTPException(status_code=404, detail="report service unavailable")
        username = None if identity.role is Role.ADMINISTRATOR else identity.username
        return [_report_response(item) for item in report_jobs.list(username=username)]

    @app.post("/api/v1/control/reports")
    def create_report(payload: ReportCreateRequest, identity: UserIdentity = Depends(require_operator)):
        if report_jobs is None:
            raise HTTPException(status_code=404, detail="report service unavailable")
        try:
            return _report_response(report_jobs.create(identity, serid=payload.serid, start=payload.start_at, end=payload.end_at))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail="pembuatan report tidak dapat dimulai") from exc

    def authorised_report(job_id: str, identity: UserIdentity) -> dict[str, Any]:
        item = report_jobs.get(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="report job tidak ditemukan")
        owner = item.get("username")
        if owner != identity.username and identity.role is not Role.ADMINISTRATOR:
            raise HTTPException(status_code=403, detail="report milik pengguna lain")
        return item

    @app.get("/api/v1/control/reports/{job_id}")
    def report_status(job_id: str, identity: UserIdentity = Depends(require_operator)):
        if report_jobs is None:
            raise HTTPException(status_code=404, detail="report service unavailable")
        return _report_response(authorised_report(job_id, identity))

    @app.get("/api/v1/control/reports/{job_id}/download")
    def download_report(job_id: str, identity: UserIdentity = Depends(require_operator)):
        if report_jobs is None:
            raise HTTPException(status_code=404, detail="report service unavailable")
        # Check ownership before touching the filesystem or exposing readiness.
        authorised_report(job_id, identity)
        try:
            item, path = report_jobs.artifact(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit.record("REPORT_DOWNLOAD", identity, "report", job_id)
        return FileResponse(path, media_type="application/pdf", filename=f"radmon-report-{job_id}.pdf")

    @app.get("/api/v1/control/audit")
    def audit_events(identity: UserIdentity = Depends(current_user)):
        return audit.list_events(limit=500)

    @app.get("/api/v1/control/archives")
    def archives(identity: UserIdentity = Depends(current_user)):
        if archive_catalog is None:
            return []
        return archive_catalog.list_archives(limit=1000)

    @app.get("/api/v1/control/archives/{quarter_id}/recap")
    def archive_recap(quarter_id: str, identity: UserIdentity = Depends(current_user)):
        if archive_catalog is None:
            raise HTTPException(status_code=404, detail="archive catalog unavailable")
        try:
            return archive_catalog.recap(quarter_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/control/archives/{quarter_id}/retry")
    def retry_archive(
        quarter_id: str,
        payload: ArchiveRetryRequest,
        identity: UserIdentity = Depends(require_admin),
    ):
        if archive_service is None:
            raise HTTPException(status_code=404, detail="archive service unavailable")
        try:
            security.require_sensitive(identity, "manage_sources", payload.pin)
            result = archive_service.retry(quarter_id)
        except Exception as exc:
            audit.record(
                "ARCHIVE_MANUAL_RETRY", identity, "archive", quarter_id,
                success=False, reason=str(exc), source="central",
            )
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit.record(
            "ARCHIVE_MANUAL_RETRY", identity, "archive", quarter_id,
            after=result, source="central",
        )
        return result

    return app
