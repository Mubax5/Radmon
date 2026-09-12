from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from .alarm_policy import AlarmPolicyService
from .alarm_policy_store import AlarmPolicyStore
from .alarm_suppression import AlarmSuppressionService
from .application_log import MariaApplicationLogWriter
from .audit import AuditTrail
from .device_admin import DeviceAdminService, MariaDeviceAdminRepository
from .lan import LanSource, RemoteMariaDBSource, parse_lan_sources
from .remote_alarm import AlarmControlService, RemoteAlarmMirror
from .runtime_status import RuntimeStatusProjector
from .security import SecurityStore
from .source_health import SourceHealthService
from .user_admin import UserAdminService


@dataclass(slots=True)
class SecureServices:
    security: SecurityStore
    audit: AuditTrail
    alarm_mirror: RemoteAlarmMirror
    alarm_control: AlarmControlService
    device_admin: DeviceAdminService
    user_admin: UserAdminService
    sources: dict[str, LanSource]
    source_health: SourceHealthService | None = None
    alarm_policy_store: AlarmPolicyStore | None = None
    alarm_policy: AlarmPolicyService | None = None
    alarm_suppression: AlarmSuppressionService | None = None
    runtime_status_projector: RuntimeStatusProjector | None = None


def security_db_path(settings) -> Path:
    raw = os.getenv("RADMON_SECURITY_DB", "").strip()
    return Path(raw) if raw else Path(settings.runtime_dir) / "radmon-security.db"


def build_secure_services(settings) -> SecureServices:
    security = SecurityStore(security_db_path(settings))
    logger = MariaApplicationLogWriter(settings)
    audit = AuditTrail(security, logger)

    policy_store = AlarmPolicyStore(security)
    policy_store.ensure_schema()
    projector = RuntimeStatusProjector(settings)
    policy = AlarmPolicyService(policy_store, audit, projector=projector)

    mirror = RemoteAlarmMirror(security)
    mirror.policy_store = policy_store
    sources = {source.source_id: source for source in parse_lan_sources()}

    def health_transition(item: dict[str, Any]) -> None:
        audit.record(
            "SOURCE_HEALTH_TRANSITION",
            None,
            "lan_source",
            str(item.get("source_id") or "unknown"),
            after={
                "state": item.get("state"),
                "host": item.get("host"),
                "last_error": item.get("last_error"),
                "message": item.get("transition_message"),
            },
            success=str(item.get("state")) not in {"DEGRADED", "OFFLINE"},
            reason=str(item.get("last_error") or "") or None,
            source=str(item.get("source_id") or "central"),
        )

    source_health = SourceHealthService(
        security,
        offline_after_failures=int(os.getenv("RADMON_LAN_OFFLINE_AFTER_FAILURES", "3")),
        transition_sink=health_transition,
    )

    def remote_factory(source_id: str) -> Any:
        source = sources.get(source_id)
        if source is None:
            raise RuntimeError(f"LAN source tidak dikenal: {source_id}")
        return RemoteMariaDBSource(source)

    alarm_control = AlarmControlService(
        security,
        mirror,
        audit,
        remote_factory=remote_factory,
    )
    alarm_control.policy_store = policy_store
    alarm_control.policy = policy

    suppression = AlarmSuppressionService(
        security,
        policy_store,
        policy,
        audit,
        alarm_control=alarm_control,
    )

    device_admin = DeviceAdminService(
        security,
        MariaDeviceAdminRepository(settings),
        audit,
    )
    user_admin = UserAdminService(security, audit)

    device_admin.source_definitions = dict(sources)
    if bool(getattr(settings, "lan_enabled", False)) and sources:
        device_admin.write_through = True
        device_admin.station_source = security.station_source

        def remote_device_factory(source_id: str):
            source = sources.get(str(source_id))
            if source is None:
                raise KeyError(f"LAN source tidak ditemukan: {source_id}")
            return RemoteMariaDBSource(source)

        device_admin.remote_factory = remote_device_factory
    else:
        device_admin.write_through = False
        device_admin.station_source = None
        device_admin.remote_factory = None

    bootstrap_user = os.getenv("RADMON_BOOTSTRAP_ADMIN_USER", "").strip()
    bootstrap_password = os.getenv("RADMON_BOOTSTRAP_ADMIN_PASSWORD", "")
    bootstrap_pin = os.getenv("RADMON_BOOTSTRAP_ADMIN_PIN", "")
    if bootstrap_user and bootstrap_password and bootstrap_pin:
        created = security.bootstrap_admin(bootstrap_user, bootstrap_password, bootstrap_pin)
        if created is not None:
            audit.record("BOOTSTRAP_ADMIN_CREATE", created, "user", created.username)

    return SecureServices(
        security=security,
        audit=audit,
        alarm_mirror=mirror,
        alarm_control=alarm_control,
        device_admin=device_admin,
        user_admin=user_admin,
        sources=sources,
        source_health=source_health,
        alarm_policy_store=policy_store,
        alarm_policy=policy,
        alarm_suppression=suppression,
        runtime_status_projector=projector,
    )
