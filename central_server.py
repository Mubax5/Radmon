from __future__ import annotations

import argparse
import os
import uvicorn

from radmon.archive import ArchiveCatalog, QuarterArchiveService
from radmon.archive_store import CentralArchiveStore
from radmon.central_api import CentralMariaDBRepository, create_central_app
from radmon.config import Settings
from radmon.lan_runtime import LanRuntime
from radmon.logging_setup import configure_logging
from radmon.repository import MariaDBRepository
from radmon.secure_api import attach_secure_routes
from radmon.secure_services import build_secure_services
from radmon.whatsapp import SeleniumWhatsAppSender, WhatsAppAlarmDispatcher


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Central measurement ingest and secure control server")
    value.add_argument("--host", default="0.0.0.0")
    value.add_argument("--port", type=int, default=8090)
    return value


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    args = parser().parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_dir)
    MariaDBRepository(settings).require_schema()

    services = build_secure_services(settings)
    services.runtime_status_projector.ensure_schema()
    services.alarm_policy.restore_and_reconcile_current_state()

    archive_catalog = ArchiveCatalog(
        services.security,
        settings.archive_dir,
        timezone_name=settings.archive_timezone,
    )
    archive_catalog.reconcile()
    archive_service = None
    if settings.archive_enabled:
        archive_service = QuarterArchiveService(
            CentralArchiveStore(settings),
            archive_catalog,
            services.audit,
            settings.archive_dir,
            timezone_name=settings.archive_timezone,
        )

    lan_enabled = _enabled("RADMON_LAN_ENABLED")
    app = create_central_app(CentralMariaDBRepository(settings), settings)
    app.state.radmon_lan_enabled = lan_enabled
    app.state.radmon_lan_source_count = len(services.sources) if lan_enabled else 0
    attach_secure_routes(
        app,
        security=services.security,
        audit=services.audit,
        alarm_mirror=services.alarm_mirror,
        alarm_control=services.alarm_control,
        device_admin=services.device_admin,
        cookie_secure=_enabled("RADMON_WEB_COOKIE_SECURE"),
        archive_catalog=archive_catalog,
        archive_service=archive_service,
        source_health=services.source_health,
        alarm_policy=services.alarm_policy,
        alarm_suppression=services.alarm_suppression,
    )

    whatsapp = None
    if _enabled("RADMON_WHATSAPP_ENABLED"):
        whatsapp = WhatsAppAlarmDispatcher(
            services.alarm_mirror,
            SeleniumWhatsAppSender.from_env(),
        )

    lan_runtime = None
    if lan_enabled:
        lan_runtime = LanRuntime(
            settings,
            services,
            whatsapp_dispatcher=whatsapp,
            archive_service=archive_service,
        )
        lan_runtime.start()

    try:
        uvicorn.run(app, host=args.host, port=args.port, reload=False)
    finally:
        if lan_runtime is not None:
            lan_runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
