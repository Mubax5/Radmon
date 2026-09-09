from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from radmon.admin.auth_dialogs import BootstrapAdminDialog, LoginDialog
from radmon.admin.main_window import MainWindow
from radmon.alarm import AlarmService
from radmon.archive import ArchiveCatalog
from radmon.archive_reports import ArchiveReportRepository, CompositeReportRepository
from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.report_queries import DatabaseReportSummaryReader
from radmon.repository import MariaDBRepository
from radmon.reports import ReportService
from radmon.runtime import ApplicationRuntime
from radmon.secure_context import SecurityContext, install_window_security, set_context
from radmon.secure_services import build_secure_services
from radmon.single_instance import SingleInstanceLock


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Radiation monitoring runtime")
    value.add_argument("--source", choices=("detector", "dummy", "lan"), default="detector")
    return value


def main() -> int:
    args = parser().parse_args()
    base_settings = Settings.from_env()
    settings = base_settings.for_dummy() if args.source == "dummy" else base_settings
    log_path = configure_logging(settings.log_dir)
    app = QApplication(sys.argv)
    app.setApplicationName("Radiation Monitoring")

    lock = SingleInstanceLock(settings.single_instance_port)
    if not lock.acquire():
        QMessageBox.critical(
            None,
            "Radiation Monitoring",
            "Radiation Monitoring sudah berjalan. Tutup aplikasi yang aktif sebelum membuka mode lain.",
        )
        return 2

    repository = MariaDBRepository(settings)
    try:
        repository.require_schema()
        if args.source != "lan":
            repository.ensure_station_catalog()
        station = repository.station_config(settings.serid)
    except Exception as exc:
        QMessageBox.critical(None, "Database tidak siap", str(exc))
        lock.release()
        return 3

    try:
        secure = build_secure_services(settings)
    except Exception as exc:
        QMessageBox.critical(None, "Security tidak siap", str(exc))
        lock.release()
        return 4

    identity = None
    if not secure.security.list_users():
        bootstrap = BootstrapAdminDialog(secure.security)
        if bootstrap.exec() != QDialog.Accepted or bootstrap.identity is None:
            lock.release()
            return 5
        identity = bootstrap.identity
        secure.audit.record("BOOTSTRAP_ADMIN_CREATE", identity, "user", identity.username)
    else:
        login = LoginDialog(secure.security)
        if login.exec() != QDialog.Accepted or login.identity is None:
            lock.release()
            return 5
        identity = login.identity
        secure.audit.record("LOGIN_SUCCESS", identity, "user", identity.username)

    set_context(
        SecurityContext(
            identity=identity,
            security=secure.security,
            audit=secure.audit,
            alarm_mirror=secure.alarm_mirror,
            alarm_control=secure.alarm_control,
            device_admin=secure.device_admin,
            user_admin=secure.user_admin,
            source_health=secure.source_health,
        )
    )

    alarm_service = AlarmService(repository, station)
    archive_catalog = None
    active_summary_reader = DatabaseReportSummaryReader(settings)
    if args.source == "lan":
        archive_catalog = ArchiveCatalog(
            secure.security,
            settings.archive_dir,
            timezone_name=settings.archive_timezone,
        )
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
    else:
        report_service = ReportService(
            repository,
            settings,
            summary_reader=active_summary_reader,
        )

    runtime = None
    if args.source != "lan":
        runtime = ApplicationRuntime(repository, settings, alarm_service, args.source)

    window = MainWindow(
        repository,
        report_service,
        alarm_service,
        settings,
        log_path,
        source=args.source,
        archive_catalog=archive_catalog,
        runtime=runtime,
    )
    install_window_security(window)

    if runtime is not None:
        app.aboutToQuit.connect(runtime.stop)
    app.aboutToQuit.connect(lock.release)
    if runtime is not None:
        runtime.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
