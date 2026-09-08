from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .audit import AuditTrail
from .remote_alarm import RemoteAlarmMirror
from .security import Role, SecurityStore, UserIdentity


SESSION_COOKIE = "radmon_session"
SESSION_TTL_SECONDS = 8 * 60 * 60


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AckRequest(BaseModel):
    event_time: datetime
    action: str = Field(min_length=1, max_length=128)
    pic: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=1000)
    pin: str = Field(min_length=4, max_length=8)


class StationUpdateRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    changes: dict[str, Any]


class CreateUserRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    role: Role
    password: str = Field(min_length=8, max_length=256)
    user_pin: str = Field(min_length=4, max_length=8)


class ArchiveRetryRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


def attach_secure_routes(
    app: FastAPI,
    *,
    security: SecurityStore,
    audit: AuditTrail,
    alarm_mirror: RemoteAlarmMirror,
    alarm_control: Any,
    device_admin: Any,
    cookie_secure: bool = False,
    archive_catalog: Any | None = None,
    archive_service: Any | None = None,
) -> FastAPI:
    def current_user(request: Request) -> UserIdentity:
        identity = security.session_user(request.cookies.get(SESSION_COOKIE))
        if identity is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return identity

    def require_admin(identity: UserIdentity = Depends(current_user)) -> UserIdentity:
        if identity.role is not Role.ADMINISTRATOR:
            raise HTTPException(status_code=403, detail="administrator required")
        return identity

    @app.post("/auth/login")
    def login(payload: LoginRequest, response: Response):
        identity = security.authenticate(payload.username, payload.password)
        if identity is None:
            audit.record(
                "LOGIN_FAILED",
                None,
                "user",
                payload.username.strip().lower(),
                success=False,
                reason="invalid credentials",
            )
            raise HTTPException(status_code=401, detail="invalid credentials")
        token = security.create_session(identity.username, SESSION_TTL_SECONDS)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
            path="/",
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

    @app.get("/api/v1/control/alarms")
    def alarms(identity: UserIdentity = Depends(current_user)):
        return alarm_mirror.list_alarms(limit=500)

    @app.post("/api/v1/control/alarms/{source_id}/{serid}/ack")
    def ack_alarm(
        source_id: str,
        serid: int,
        payload: AckRequest,
        identity: UserIdentity = Depends(current_user),
    ):
        if not security.role_allows(identity.role, "ack_alarm"):
            raise HTTPException(status_code=403, detail="operator permission required")
        try:
            return alarm_control.ack(
                identity,
                payload.pin,
                source_id,
                serid,
                payload.event_time,
                action=payload.action,
                pic=payload.pic,
                note=payload.note,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/control/stations/{serid}")
    def update_station(
        serid: int,
        payload: StationUpdateRequest,
        identity: UserIdentity = Depends(current_user),
    ):
        if identity.role is not Role.ADMINISTRATOR:
            raise HTTPException(status_code=403, detail="administrator required")
        try:
            return device_admin.update_station(identity, payload.pin, serid, payload.changes)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/control/users")
    def users(identity: UserIdentity = Depends(require_admin)):
        return security.list_users()

    @app.post("/api/v1/control/users")
    def create_user(
        payload: CreateUserRequest,
        identity: UserIdentity = Depends(require_admin),
    ):
        try:
            security.require_sensitive(identity, "manage_users", payload.pin)
            created = security.create_user(
                payload.username,
                payload.display_name,
                payload.role,
                payload.password,
                payload.user_pin,
                actor=identity.username,
            )
        except Exception as exc:
            audit.record(
                "USER_CREATE",
                identity,
                "user",
                payload.username,
                after={"display_name": payload.display_name, "role": payload.role.value},
                success=False,
                reason=str(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit.record(
            "USER_CREATE",
            identity,
            "user",
            created.username,
            after={"display_name": created.display_name, "role": created.role.value},
        )
        return {
            "username": created.username,
            "display_name": created.display_name,
            "role": created.role.value,
        }

    @app.get("/api/v1/control/audit")
    def audit_events(identity: UserIdentity = Depends(current_user)):
        return audit.list_events(limit=500)

    @app.get("/api/v1/control/archives")
    def archives(identity: UserIdentity = Depends(current_user)):
        if archive_catalog is None:
            return []
        return archive_catalog.list_archives(limit=1000)

    @app.get("/api/v1/control/archives/{quarter_id}/recap")
    def archive_recap(
        quarter_id: str,
        identity: UserIdentity = Depends(current_user),
    ):
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
                "ARCHIVE_MANUAL_RETRY",
                identity,
                "archive",
                quarter_id,
                success=False,
                reason=str(exc),
                source="central",
            )
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit.record(
            "ARCHIVE_MANUAL_RETRY",
            identity,
            "archive",
            quarter_id,
            after=result,
            source="central",
        )
        return result

    return app
