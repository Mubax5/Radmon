from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .admin.auth_dialogs import BootstrapAdminDialog, LoginDialog
from .admin.main_window import MainWindow
from .alarm import AlarmService
from .config import Settings
from .logging_setup import configure_logging
from .report_queries import DatabaseReportSummaryReader
from .repository import MariaDBRepository
from .reports import ReportService
from .runtime import ApplicationRuntime
from .secure_context import SecurityContext, install_window_security, set_context
from .secure_services import build_secure_services
from .single_instance import SingleInstanceLock


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="RadMon developer runtime (detector/dummy only)"
    )
    value.add_argument("--source", choices=("detector", "dummy"), default="detector")
    return value


def run_developer_mode(source: str) -> int:
    if source not in {"detector", "dummy"}:
        raise ValueError("developer source harus detector atau dummy")

    base_settings = Settings.from_env()
    settings = base_settings.for_dummy() if source == "dummy" else base_settings
    log_path = configure_logging(settings.log_dir)
    app = QApplication.instance() or QApplication(sys.argv)
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
            alarm_policy=secure.alarm_policy,
            alarm_suppression=secure.alarm_suppression,
        )
    )

    alarm_service = AlarmService(repository, station)
    summary_reader = DatabaseReportSummaryReader(settings)
    report_service = ReportService(repository, settings, summary_reader=summary_reader)
    runtime = ApplicationRuntime(repository, settings, alarm_service, source)
    window = MainWindow(
        repository,
        report_service,
        alarm_service,
        settings,
        log_path,
        source=source,
        archive_catalog=None,
        runtime=runtime,
    )
    install_window_security(window)
    app.aboutToQuit.connect(runtime.stop)
    app.aboutToQuit.connect(lock.release)
    runtime.start()
    window.show()
    return app.exec()


def main() -> int:
    args = parser().parse_args()
    return run_developer_mode(args.source)


if __name__ == "__main__":
    raise SystemExit(main())
