from __future__ import annotations

from dataclasses import replace
import os
import threading
import webbrowser
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..grafana_bootstrap import GrafanaBootstrap
from .alarm_page import AlarmPage
from .chart_page import ChartPage
from .icons import silk_icon
from .logs_page import LogsPage
from .recent_page import RecentPage
from .reports_page import ReportsPage
from .tabular_page import TabularPage


def open_external_url(
    url: str,
    *,
    platform_name: str | None = None,
    native_open: Callable[[str], object] | None = None,
    qt_open: Callable[[QUrl], bool] | None = None,
    browser_open: Callable[[str], bool] | None = None,
) -> bool:
    """Open a monitoring URL without silently swallowing launcher failures."""
    platform = platform_name or os.name

    if platform == "nt":
        opener = native_open
        if opener is None and hasattr(os, "startfile"):
            opener = os.startfile
        if opener is not None:
            try:
                opener(url)
                return True
            except (OSError, ValueError):
                pass

    qt_launcher = qt_open or QDesktopServices.openUrl
    try:
        if bool(qt_launcher(QUrl(url))):
            return True
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

    fallback = browser_open or webbrowser.open_new_tab
    try:
        return bool(fallback(url))
    except (OSError, webbrowser.Error):
        return False


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
        self.repository = repository
        self.report_service = report_service
        self.base_settings = settings
        self.settings = settings
        self.source = source
        self._grafana_bootstrap = GrafanaBootstrap(settings)
        self._grafana_ready_url: str | None = None
        self._grafana_error: str | None = None
        self._grafana_thread: threading.Thread | None = None
        self._monitoring_open_pending = False
        self.setWindowTitle("Radiation Monitoring")
        self.resize(1400, 850)

        self.tabs = QTabWidget()
        self.tabs.setIconSize(QSize(16, 16))
        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        self.tabs.addTab(RecentPage(repository, settings), silk_icon("clock"), "Recent")
        self.tabs.addTab(TabularPage(repository, settings), silk_icon("table"), "Tabular")
        self.tabs.addTab(ChartPage(repository, settings), silk_icon("chart_line"), "Chart")
        self.tabs.addTab(ReportsPage(report_service, settings), silk_icon("report"), "Reports")
        self.tabs.addTab(AlarmPage(repository, alarm_service, settings), silk_icon("lock"), "Alarm")
        self.tabs.addTab(LogsPage(log_path), silk_icon("page_white_text"), "Logs")

        sidebar = self._build_station_sidebar()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar)
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

        self._monitoring_poll_timer = QTimer(self)
        self._monitoring_poll_timer.setInterval(250)
        self._monitoring_poll_timer.timeout.connect(self._open_monitoring_if_ready)

        self._start_grafana_bootstrap()
        self.refresh_current_page()

    def _build_station_sidebar(self) -> QWidget:
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)

        self.station_tree = QTreeWidget()
        self.station_tree.setObjectName("stationTree")
        self.station_tree.setHeaderHidden(True)
        self.station_tree.setMinimumWidth(240)
        root = QTreeWidgetItem(self.station_tree, ["Station"])
        root.setIcon(0, silk_icon("feed"))
        root.setExpanded(True)

        selected_item = None
        for station in self.repository.station_configs():
            child = QTreeWidgetItem(root, [station.room])
            child.setIcon(0, silk_icon("feed"))
            child.setData(0, Qt.UserRole, station.serid)
            child.setToolTip(
                0,
                f"[{station.serid}] {station.room} ({station.location}) · "
                f"Alert {station.warnlevel:g} {station.unit}, "
                f"Alarm {station.alarmlevel:g} {station.unit}",
            )
            if station.serid == self.settings.serid:
                selected_item = child

        details = QWidget()
        form = QFormLayout(details)
        form.setContentsMargins(6, 6, 6, 6)
        self.station_tag = QLabel("-")
        self.station_name = QLabel("-")
        self.station_location = QLabel("-")
        self.station_description = QLabel("-")
        self.station_description.setWordWrap(True)
        form.addRow("Tag", self.station_tag)
        form.addRow("Name", self.station_name)
        form.addRow("Location", self.station_location)
        form.addRow("Description", self.station_description)
        update = QPushButton("Update")
        update.clicked.connect(self.refresh_current_page)
        form.addRow("", update)

        layout.addWidget(self.station_tree, 1)
        layout.addWidget(details)
        self.station_tree.currentItemChanged.connect(self._station_changed)
        if selected_item is None and root.childCount():
            selected_item = root.child(0)
        if selected_item is not None:
            self.station_tree.setCurrentItem(selected_item)
        return sidebar

    def _station_changed(self, current, previous=None) -> None:
        if current is None:
            return
        serid = current.data(0, Qt.UserRole)
        if serid is None:
            return
        try:
            station = self.repository.station_config(int(serid))
        except Exception as exc:
            self.statusBar().showMessage(f"Station read error: {exc}")
            return
        selected = replace(
            self.base_settings,
            serid=station.serid,
            building=station.building,
            room=station.room,
            location=station.location,
            warnlevel=station.warnlevel,
            alarmlevel=station.alarmlevel,
            maxidlemin=station.maxidlemin,
            unit=station.unit,
        )
        self.settings = selected
        self.report_service.settings = selected
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if hasattr(page, "settings"):
                page.settings = selected
        self.station_tag.setText(str(station.serid))
        self.station_name.setText(station.room)
        self.station_location.setText(station.location)
        self.station_description.setText(
            f"Alert {station.warnlevel:g} {station.unit}, "
            f"Alarm {station.alarmlevel:g} {station.unit}"
        )
        self.refresh_current_page()

    def _build_actions(self) -> None:
        self.monitoring_action = QAction(silk_icon("monitor"), "Monitoring", self)
        self.monitoring_action.setStatusTip("Open Grafana monitoring")
        self.monitoring_action.triggered.connect(self.open_monitoring)

        self.refresh_action = QAction(silk_icon("arrow_refresh"), "Refresh", self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_current_page)

        self.report_action = QAction(silk_icon("report"), "Reports", self)
        self.report_action.triggered.connect(lambda: self.tabs.setCurrentIndex(self.REPORT_TAB_INDEX))

        self.print_action = QAction(silk_icon("printer"), "Print report", self)
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

    def _start_grafana_bootstrap(self) -> None:
        if self._grafana_thread is not None and self._grafana_thread.is_alive():
            return
        self._grafana_error = None
        self._grafana_thread = threading.Thread(
            target=self._prepare_grafana,
            name="radmon-grafana-bootstrap",
            daemon=True,
        )
        self._grafana_thread.start()

    def _prepare_grafana(self) -> None:
        try:
            self._grafana_ready_url = self._grafana_bootstrap.ensure()
            self._grafana_error = None
        except Exception as exc:
            self._grafana_ready_url = None
            self._grafana_error = str(exc)

    def _open_monitoring_url(self) -> bool:
        if not self._grafana_ready_url:
            return False
        opened = open_external_url(self._grafana_ready_url)
        if opened:
            self.statusBar().showMessage("Monitoring Grafana dibuka di browser.", 5000)
            return True
        QMessageBox.warning(
            self,
            "Monitoring",
            "Browser gagal membuka dashboard Grafana. Periksa default browser Windows.",
        )
        return False

    def open_monitoring(self) -> None:
        if self._grafana_ready_url:
            self._open_monitoring_url()
            return
        self._monitoring_open_pending = True
        self._start_grafana_bootstrap()
        if not self._monitoring_poll_timer.isActive():
            self._monitoring_poll_timer.start()
        self.statusBar().showMessage("Grafana sedang disiapkan dan diverifikasi...")

    def _open_monitoring_if_ready(self) -> None:
        if not self._monitoring_open_pending:
            if self._monitoring_poll_timer.isActive():
                self._monitoring_poll_timer.stop()
            return
        if self._grafana_ready_url:
            self._monitoring_open_pending = False
            self._monitoring_poll_timer.stop()
            self._open_monitoring_url()
        elif self._grafana_error:
            self._monitoring_open_pending = False
            self._monitoring_poll_timer.stop()
            message = f"Grafana setup error: {self._grafana_error}"
            self.statusBar().showMessage(message)
            QMessageBox.warning(self, "Monitoring", message)

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

        self._open_monitoring_if_ready()
        if self._monitoring_open_pending:
            self.statusBar().showMessage("Grafana sedang disiapkan dan diverifikasi...")
            return

        error = getattr(page, "last_error", None) if page is not None else None
        mode = "DEMO" if self.source == "dummy" else "DETECTOR"
        if error:
            self.statusBar().showMessage(f"{mode} · {error}")
        else:
            self.statusBar().showMessage(f"{mode} · {self.settings.station_label} · refresh 2s")
