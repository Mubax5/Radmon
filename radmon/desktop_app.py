from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .admin.auth_dialogs import BootstrapAdminDialog, LoginDialog
from .admin.main_window import MainWindow
from .alarm import AlarmService
from .archive import ArchiveCatalog
from .archive_reports import ArchiveReportRepository, CompositeReportRepository
from .config import Settings
from .report_queries import DatabaseReportSummaryReader
from .repository import MariaDBRepository
from .reports import ReportService
from .secure_context import SecurityContext, install_window_security, set_context


def run_admin_ui(
    settings: Settings,
    services: Any,
    archive_catalog: ArchiveCatalog,
    log_path: Path,
) -> int:
    """Run the LAN Admin desktop using central-owned security/domain services."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Radiation Monitoring")

    repository = MariaDBRepository(settings)
    try:
        repository.require_schema()
        station = repository.station_config(settings.serid)
    except Exception as exc:
        QMessageBox.critical(None, "Database tidak siap", str(exc))
        return 3

    identity = None
    if not services.security.list_users():
        bootstrap = BootstrapAdminDialog(services.security)
        if bootstrap.exec() != QDialog.Accepted or bootstrap.identity is None:
            return 5
        identity = bootstrap.identity
        services.audit.record("BOOTSTRAP_ADMIN_CREATE", identity, "user", identity.username)
    else:
        login = LoginDialog(services.security)
        if login.exec() != QDialog.Accepted or login.identity is None:
            return 5
        identity = login.identity
        services.audit.record("LOGIN_SUCCESS", identity, "user", identity.username)

    set_context(
        SecurityContext(
            identity=identity,
            security=services.security,
            audit=services.audit,
            alarm_mirror=services.alarm_mirror,
            alarm_control=services.alarm_control,
            device_admin=services.device_admin,
            user_admin=services.user_admin,
            source_health=services.source_health,
            alarm_policy=services.alarm_policy,
            alarm_suppression=services.alarm_suppression,
        )
    )

    alarm_service = AlarmService(repository, station)
    active_summary_reader = DatabaseReportSummaryReader(settings)
    report_repository = CompositeReportRepository(
        repository,
        ArchiveReportRepository(
            archive_catalog,
            timezone_name=settings.archive_timezone,
        ),
        timezone_name=settings.archive_timezone,
        active_summary_reader=active_summary_reader,
    )
    report_service = ReportService(report_repository, settings)

    window = MainWindow(
        repository,
        report_service,
        alarm_service,
        settings,
        log_path,
        source="lan",
        archive_catalog=archive_catalog,
        runtime=None,
    )
    install_window_security(window)
    app.aboutToQuit.connect(lambda: set_context(None))
    window.show()
    return app.exec()
