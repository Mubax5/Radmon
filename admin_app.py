from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from radmon.admin.main_window import MainWindow
from radmon.alarm import AlarmService
from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.repository import MariaDBRepository
from radmon.reports import ReportService


def main() -> int:
    settings=Settings.from_env(); log_path=configure_logging(settings.log_dir); repository=MariaDBRepository(settings); station=repository.station_config(settings.serid)
    alarm_service=AlarmService(repository,station); report_service=ReportService(repository,settings)
    app=QApplication(sys.argv); app.setApplicationName("Radmon DPFK Admin"); window=MainWindow(repository,report_service,alarm_service,settings,log_path); window.show(); return app.exec()


if __name__ == "__main__": raise SystemExit(main())
