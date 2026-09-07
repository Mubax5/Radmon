from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QListWidget, QMainWindow, QSplitter, QTabWidget, QVBoxLayout, QWidget

from .recent_page import RecentPage
from .tabular_page import TabularPage
from .chart_page import ChartPage
from .reports_page import ReportsPage
from .alarm_page import AlarmPage
from .logs_page import LogsPage


class MainWindow(QMainWindow):
    def __init__(self, repository, report_service, alarm_service, settings, log_path, *, source: str, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.source = source
        self.setWindowTitle("Radiation Monitoring")
        self.resize(1400, 850)
        stations = QListWidget()
        stations.addItem(f"{settings.room}  [{settings.serid}]")
        stations.setCurrentRow(0)
        stations.setMinimumWidth(220)
        self.tabs = QTabWidget()
        self.tabs.addTab(RecentPage(repository, settings), "Recent")
        self.tabs.addTab(TabularPage(repository, settings), "Tabular")
        self.tabs.addTab(ChartPage(repository, settings), "Chart")
        self.tabs.addTab(ReportsPage(report_service, settings), "Reports")
        self.tabs.addTab(AlarmPage(repository, alarm_service, settings), "Alarm")
        self.tabs.addTab(LogsPage(log_path), "Logs")
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(stations)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(splitter)
        self.setCentralWidget(container)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_current_page)
        self.refresh_timer.start(2000)
        self.refresh_current_page()

    def refresh_current_page(self) -> None:
        page = self.tabs.currentWidget()
        if page is not None and hasattr(page, "refresh_live"):
            page.refresh_live()
        error = getattr(page, "last_error", None) if page is not None else None
        mode = "DEMO" if self.source == "dummy" else "DETECTOR"
        if error:
            self.statusBar().showMessage(f"{mode} · {error}")
        else:
            sync = "SYNC ON" if self.settings.sync_enabled else "SYNC OFF"
            self.statusBar().showMessage(f"{mode} · {self.settings.station_label} · {sync} · refresh 2s")
