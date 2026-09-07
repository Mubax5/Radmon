from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QMainWindow, QSplitter, QTabWidget, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from .recent_page import RecentPage
from .tabular_page import TabularPage
from .chart_page import ChartPage
from .reports_page import ReportsPage
from .alarm_page import AlarmPage
from .logs_page import LogsPage


class MainWindow(QMainWindow):
    """Admin-only desktop UI modeled after the legacy Recent/Tabular/Chart/Reports/Alarm/Logs workflow."""
    def __init__(self, repository, report_service, alarm_service, settings, log_path, parent=None):
        super().__init__(parent); self.setWindowTitle("Radiation Monitoring - Python Admin"); self.resize(1400,850)
        stations=QListWidget(); stations.addItem(f"{settings.room}  [{settings.serid}]"); stations.setCurrentRow(0); stations.setMinimumWidth(220)
        tabs=QTabWidget()
        tabs.addTab(RecentPage(repository,settings),"Recent")
        tabs.addTab(TabularPage(repository,settings),"Tabular")
        tabs.addTab(ChartPage(repository,settings),"Chart")
        tabs.addTab(ReportsPage(report_service,settings),"Reports")
        tabs.addTab(AlarmPage(repository,alarm_service,settings),"Alarm")
        tabs.addTab(LogsPage(log_path),"Logs")
        splitter=QSplitter(Qt.Horizontal); splitter.addWidget(stations); splitter.addWidget(tabs); splitter.setStretchFactor(1,1)
        container=QWidget(); layout=QVBoxLayout(container); layout.setContentsMargins(6,6,6,6); layout.addWidget(splitter); self.setCentralWidget(container)
        self.statusBar().showMessage(f"Station {settings.station_label} · Admin desktop")
