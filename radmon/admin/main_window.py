from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .alarm_page import AlarmPage
from .chart_page import ChartPage
from .icons import silk_icon
from .logs_page import LogsPage
from .recent_page import RecentPage
from .reports_page import ReportsPage
from .tabular_page import TabularPage


class MainWindow(QMainWindow):
    """Operator-facing desktop shell that mirrors the established DPFK workflow."""

    REPORT_TAB_INDEX = 3

    def __init__(
        self,
        repository,
        report_service,
        alarm_service,
        settings,
        log_path,
        *,
        source: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.source = source
        self.setWindowTitle("Radiation Monitoring")
        self.resize(1400, 850)

        self.tabs = QTabWidget()
        self.tabs.setIconSize(QSize(16, 16))
        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        stations = QListWidget()
        stations.setObjectName("stationList")
        stations.addItem(
            QListWidgetItem(
                silk_icon("feed"),
                f"{settings.room}  [{settings.serid}]",
            )
        )
        stations.setCurrentRow(0)
        stations.setMinimumWidth(220)

        self.tabs.addTab(
            RecentPage(repository, settings), silk_icon("clock"), "Recent"
        )
        self.tabs.addTab(
            TabularPage(repository, settings), silk_icon("table"), "Tabular"
        )
        self.tabs.addTab(
            ChartPage(repository, settings), silk_icon("chart_line"), "Chart"
        )
        self.tabs.addTab(
            ReportsPage(report_service, settings), silk_icon("report"), "Reports"
        )
        self.tabs.addTab(
            AlarmPage(repository, alarm_service, settings), silk_icon("lock"), "Alarm"
        )
        self.tabs.addTab(
            LogsPage(log_path), silk_icon("page_white_text"), "Logs"
        )

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

    def _build_actions(self) -> None:
        self.monitoring_action = QAction(
            silk_icon("monitor"), "Monitoring", self
        )
        self.monitoring_action.setStatusTip("Open Grafana monitoring")
        self.monitoring_action.triggered.connect(self.open_monitoring)

        self.refresh_action = QAction(
            silk_icon("arrow_refresh"), "Refresh", self
        )
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_current_page)

        self.report_action = QAction(silk_icon("report"), "Reports", self)
        self.report_action.triggered.connect(
            lambda: self.tabs.setCurrentIndex(self.REPORT_TAB_INDEX)
        )

        self.print_action = QAction(
            silk_icon("printer"), "Print report", self
        )
        self.print_action.triggered.connect(self._print_current_report)

        self.exit_action = QAction(silk_icon("door_out"), "Exit", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.triggered.connect(self.close)

        self.about_action = QAction(silk_icon("help"), "About", self)
        self.about_action.triggered.connect(self._show_about)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.report_action)
        file_menu.addAction(self.print_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.monitoring_action)
        view_menu.addAction(self.refresh_action)

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(self.monitoring_action)

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(self.about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)
        toolbar.addAction(self.refresh_action)
        toolbar.addSeparator()
        toolbar.addAction(self.monitoring_action)
        toolbar.addAction(self.report_action)
        toolbar.addAction(self.print_action)

    def open_monitoring(self) -> None:
        QDesktopServices.openUrl(QUrl(self.settings.grafana_url))

    def _print_current_report(self) -> None:
        self.tabs.setCurrentIndex(self.REPORT_TAB_INDEX)
        page = self.tabs.currentWidget()
        if page is not None and hasattr(page, "print_report"):
            page.print_report()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "Radiation Monitoring",
            "Radiation Monitoring\nPython admin and Grafana monitoring",
        )

    def refresh_current_page(self) -> None:
        page = self.tabs.currentWidget()
        if page is not None and hasattr(page, "refresh_live"):
            page.refresh_live()
        error = getattr(page, "last_error", None) if page is not None else None
        mode = "DEMO" if self.source == "dummy" else "DETECTOR"
        if error:
            self.statusBar().showMessage(f"{mode} · {error}")
        else:
            self.statusBar().showMessage(
                f"{mode} · {self.settings.station_label} · refresh 2s"
            )
