from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from radmon.admin.main_window import MainWindow
from radmon.alarm import AlarmService
from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.report_queries import DatabaseReportSummaryReader
from radmon.repository import MariaDBRepository
from radmon.reports import ReportService
from radmon.runtime import ApplicationRuntime
from radmon.single_instance import SingleInstanceLock


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Radiation monitoring runtime")
    value.add_argument("--source", choices=("detector", "dummy"), default="detector")
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
        repository.ensure_station_catalog()
        station = repository.station_config(settings.serid)
    except Exception as exc:
        QMessageBox.critical(None, "Database tidak siap", str(exc))
        lock.release()
        return 3

    alarm_service = AlarmService(repository, station)
    report_service = ReportService(
        repository,
        settings,
        summary_reader=DatabaseReportSummaryReader(settings),
    )
    runtime = ApplicationRuntime(repository, settings, alarm_service, args.source)
    window = MainWindow(
        repository,
        report_service,
        alarm_service,
        settings,
        log_path,
        source=args.source,
    )

    app.aboutToQuit.connect(runtime.stop)
    app.aboutToQuit.connect(lock.release)
    runtime.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
