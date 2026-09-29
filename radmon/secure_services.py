from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
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
from .security_migration import migrate_legacy_users
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


def _copy_sqlite_database(source: Path, target: Path) -> None:
    """Copy a live SQLite store (including WAL contents) without changing source."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".migration", dir=target.parent)
    import os

    os.close(fd)
    temporary = Path(temporary_name)
    try:
        origin = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            copy = sqlite3.connect(temporary)
            try:
                origin.backup(copy)
                result = copy.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError(f"SQLite integrity check failed while migrating {source}: {result}")
            finally:
                copy.close()
        finally:
            origin.close()
        check = sqlite3.connect(temporary)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(f"SQLite integrity check failed for migration copy of {source}: {result}")
        finally:
            check.close()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def security_db_path(settings) -> Path:
    """Resolve the security store once from installation-root settings.

    Older builds interpreted a relative RADMON_SECURITY_DB against process cwd.
    Check only the known install/app cwd variants; retain every source and refuse
    to pick between multiple stores rather than silently splitting identities.
    """
    configured_value = getattr(settings, "security_db", None)
    if configured_value is None:
        configured_value = os.getenv("RADMON_SECURITY_DB", "").strip()
    if configured_value:
        configured = Path(configured_value).expanduser()
        if not configured.is_absolute():
            configured = Path(settings.runtime_dir).parent / configured
    else:
        configured = Path(settings.runtime_dir) / "radmon-security.db"
    configured = configured.resolve()
    candidates = {
        (Path.cwd() / "runtime" / configured.name).resolve(),
        (Path(sys.executable).resolve().parent / "runtime" / configured.name).resolve(),
    }
    application_dir = getattr(settings, "application_dir", None)
    if application_dir:
        candidates.add((Path(application_dir) / "runtime" / configured.name).resolve())
    candidates.discard(configured)
    existing = sorted(path for path in candidates if path.is_file())
    if configured.is_file() and existing:
        raise RuntimeError(
            f"Multiple RadMon security databases exist ({configured} and {', '.join(map(str, existing))}). "
            "Stop RadMon and consolidate/identify the authoritative database before starting; no data was changed."
        )
    if len(existing) > 1:
        raise RuntimeError(
            f"Multiple legacy RadMon security databases exist ({', '.join(map(str, existing))}). "
            "Stop RadMon and identify the authoritative database before starting; no data was changed."
        )
    if existing:
        _copy_sqlite_database(existing[0], configured)
    configured.parent.mkdir(parents=True, exist_ok=True)
    return configured


def build_secure_services(settings) -> SecureServices:
    security = SecurityStore(security_db_path(settings))
    migrate_legacy_users(security)
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

    # Persisted mappings remain the ownership authority whether a LAN source is
    # connected or not. Station administration never writes remote records.
    device_admin.station_source = security.station_source

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
