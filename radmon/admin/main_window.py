from __future__ import annotations

import csv
from dataclasses import replace
import os
from pathlib import Path
import threading
import time
import webbrowser
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
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
from ..paths import ApplicationPaths
from ..secure_context import get_context
from ..security import Role
from .about_dialog import AboutDialog
from .acquisition_dialog import AcquisitionControlDialog
from .alarm_page import AlarmPage
from .chart_page import ChartPage
from .diagnostics_dialogs import HardwareTestDialog, ServerTestDialog
from .icons import app_icon
from .logs_page import LogsPage
from .options_dialog import OptionsDialog
from .recent_page import RecentPage
from .reports_page import ReportsPage
from .station_admin_dialog import StationAdminDialog
from .tabular_page import TabularPage
from .ui_preferences import DesktopPreferences


INSTALLATION_MANUAL_PATH = "docs/manual/installation.html"
USER_MANUAL_PATH = "docs/manual/user-manual.html"


def group_stations_by_source(stations, station_source_by_serid, sources, health_by_source):
    groups = []
    for source_id, source in sources.items():
        members = [
            station for station in stations
            if station_source_by_serid.get(int(station.serid)) == source_id
        ]
        groups.append({
            "source_id": source_id,
            "host": str(getattr(source, "host", "")),
            "state": str(health_by_source.get(source_id, "UNKNOWN")),
            "stations": members,
        })
    return groups


def _source_label(source_id: str) -> str:
    text = str(source_id)
    lower = text.lower()
    if lower.startswith("gd") and lower[2:].isdigit():
        return f"Gd.{lower[2:]}"
    return text


def _source_health_map() -> dict[str, str]:
    context = get_context()
    if context is None:
        return {}
    try:
        return {
            str(row["source_id"]): str(row.get("state") or "UNKNOWN")
            for row in context.source_health.list_states()
        }
    except Exception:
        return {}


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
    """Operator-facing desktop shell with legacy workflow parity."""

    RECENT_TAB_INDEX = 0
    TABULAR_TAB_INDEX = 1
    CHART_TAB_INDEX = 2
    REPORT_TAB_INDEX = 3
    ALARM_TAB_INDEX = 4
    LOG_TAB_INDEX = 5

    def __init__(
        self,
        repository,
        report_service,
        alarm_service,
        settings,
        log_path,
        *,
        source: str,
        archive_catalog=None,
        runtime=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.report_service = report_service
        self.base_settings = settings
        self.settings = settings
        self.source = source
        self.runtime = runtime
        self.archive_catalog = archive_catalog
        self.preferences = DesktopPreferences.load(settings)
        self._grafana_bootstrap = GrafanaBootstrap(settings)
        self._grafana_ready_url: str | None = None
        self._grafana_error: str | None = None
        self._grafana_thread: threading.Thread | None = None
        self._monitoring_open_pending = False
        self.setWindowTitle("Radiation Monitoring")
        self.resize(1400, 850)

        self.tabs = QTabWidget()
        self.tabs.setIconSize(QSize(16, 16))

        self.recent_page = RecentPage(repository, settings, preferences=self.preferences)
        self.tabular_page = TabularPage(repository, settings)
        self.chart_page = ChartPage(repository, settings)
        self.reports_page = ReportsPage(
            report_service,
            settings,
            archive_catalog=archive_catalog,
        )
        self.alarm_page = AlarmPage(repository, alarm_service, settings)
        self.logs_page = LogsPage(log_path)

        self.tabs.addTab(self.recent_page, app_icon("recent"), "Recent")
        self.tabs.addTab(self.tabular_page, app_icon("tabular"), "Tabular")
        self.tabs.addTab(self.chart_page, app_icon("chart"), "Chart")
        self.tabs.addTab(self.reports_page, app_icon("reports"), "Reports")
        self.tabs.addTab(self.alarm_page, app_icon("alarm"), "Alarm")
        self.tabs.addTab(self.logs_page, app_icon("logs"), "Logs")
        self.recent_page.stationSelected.connect(self._select_station_from_recent)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        # Station selection can refresh the current page while the sidebar is
        # still being constructed. The monitoring poll timer therefore must
        # exist before _build_station_sidebar() triggers that first refresh.
        self._monitoring_poll_timer = QTimer(self)
        self._monitoring_poll_timer.setInterval(250)
        self._monitoring_poll_timer.timeout.connect(self._open_monitoring_if_ready)

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
        self.refresh_timer.setInterval(max(250, int(self.preferences.refresh_interval * 1000)))

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

        details = QWidget()
        form = QFormLayout(details)
        form.setContentsMargins(6, 6, 6, 6)
        self.station_tag = QLineEdit()
        self.station_name = QLineEdit()
        self.station_location = QLineEdit()
        self.station_description = QPlainTextEdit()
        self.station_description.setMaximumHeight(90)
        for widget in (self.station_tag, self.station_name, self.station_location):
            widget.setReadOnly(True)
        self.station_description.setReadOnly(True)
        form.addRow("Tag", self.station_tag)
        form.addRow("Name", self.station_name)
        form.addRow("Location", self.station_location)
        form.addRow("Description", self.station_description)
        self.station_update = QPushButton("Update")
        self.station_update.clicked.connect(self._open_station_editor)
        context = get_context()
        self.station_update.setEnabled(
            bool(context and context.identity.role is Role.ADMINISTRATOR)
        )
        form.addRow("", self.station_update)

        layout.addWidget(self.station_tree, 1)
        layout.addWidget(details)
        self.station_tree.currentItemChanged.connect(self._station_changed)
        self.reload_station_sidebar(select_serid=self.settings.serid)
        return sidebar

    def _reload_station_sidebar_base(self, *, select_serid: int | None = None) -> None:
        self.station_tree.blockSignals(True)
        self.station_tree.clear()
        root = QTreeWidgetItem(self.station_tree, ["Station"])
        root.setIcon(0, app_icon("station_group"))
        root.setExpanded(True)
        selected_item = None
        try:
            stations = list(self.repository.station_configs())
        except Exception as exc:
            self.statusBar().showMessage(f"Station list error: {exc}")
            stations = []
        for station in stations:
            child = QTreeWidgetItem(root, [station.room])
            child.setIcon(0, app_icon("detector"))
            child.setData(0, Qt.UserRole, station.serid)
            child.setToolTip(
                0,
                f"[{station.serid}] {station.room} ({station.location}) · "
                f"Alert {station.warnlevel:g} {station.unit}, "
                f"Alarm {station.alarmlevel:g} {station.unit}",
            )
            if select_serid is not None and int(station.serid) == int(select_serid):
                selected_item = child
        if selected_item is None and root.childCount():
            selected_item = root.child(0)
        self.station_tree.blockSignals(False)
        if selected_item is not None:
            self.station_tree.setCurrentItem(selected_item)
            self._station_changed(selected_item)

    def _select_station_from_recent_base(self, serid: int) -> None:
        root = self.station_tree.topLevelItem(0)
        if root is None:
            return
        for index in range(root.childCount()):
            item = root.child(index)
            if int(item.data(0, Qt.UserRole) or 0) == int(serid):
                self.station_tree.setCurrentItem(item)
                return

    def _device_description(self, serid: int, fallback: str) -> str:
        context = get_context()
        if context is None:
            return fallback
        try:
            item = context.device_admin.repository.get_device(int(serid))
        except Exception:
            return fallback
        return str((item or {}).get("description") or fallback)

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
            report_dir=Path(self.preferences.report_dir),
            refresh_interval=self.preferences.refresh_interval,
        )
        self.settings = selected
        self.report_service.settings = selected
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if hasattr(page, "settings"):
                page.settings = selected
            page_report_service = getattr(page, "report_service", None)
            if page_report_service is not None and hasattr(page_report_service, "settings"):
                page_report_service.settings = selected
        self.station_tag.setText(str(station.serid))
        self.station_name.setText(station.room)
        self.station_location.setText(station.location)
        fallback = (
            f"Alert {station.warnlevel:g} {station.unit}, "
            f"Alarm {station.alarmlevel:g} {station.unit}"
        )
        self.station_description.setPlainText(self._device_description(station.serid, fallback))
        self.refresh_current_page()

    def _build_actions_base(self) -> None:
        self.monitoring_action = QAction(app_icon("monitoring"), "Monitoring", self)
        self.monitoring_action.setStatusTip("Open Grafana monitoring")
        self.monitoring_action.triggered.connect(self.open_monitoring)

        self.refresh_action = QAction(app_icon("refresh"), "Refresh", self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_current_page)

        self.save_as_action = QAction(app_icon("save_as"), "Save As...", self)
        self.save_as_action.triggered.connect(self._save_as)
        self.save_csv_action = QAction(app_icon("save_csv"), "Save As CSV...", self)
        self.save_csv_action.triggered.connect(self._save_as_csv)
        self.printer_setup_action = QAction(app_icon("printer_setup"), "Printer Setup...", self)
        self.printer_setup_action.triggered.connect(self._printer_setup)
        self.print_preview_action = QAction(app_icon("print_preview"), "Print Preview...", self)
        self.print_preview_action.triggered.connect(self._print_preview)
        self.print_action = QAction(app_icon("print"), "Print...", self)
        self.print_action.triggered.connect(self._print_current_report)

        self.exit_action = QAction(app_icon("exit"), "Exit", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.triggered.connect(self.close)

        self.view_actions: list[QAction] = []
        for index, (label, slot) in enumerate(
            (
                ("Recent Values", "recent"),
                ("Tabular View", "tabular"),
                ("Chart Display", "chart"),
                ("Reports", "reports"),
                ("Alarm", "alarm"),
                ("Log", "logs"),
            )
        ):
            action = QAction(app_icon(slot), label, self)
            action.triggered.connect(
                lambda _checked=False, tab_index=index: self.tabs.setCurrentIndex(tab_index)
            )
            self.view_actions.append(action)
        self.report_action = self.view_actions[self.REPORT_TAB_INDEX]

        self.select_period_action = QAction(app_icon("select_period"), "Select period...", self)
        self.select_period_action.triggered.connect(self._select_period_current)

        self.new_station_action = QAction(app_icon("new_station"), "New station...", self)
        self.new_station_action.triggered.connect(self._new_station)

        self.options_action = QAction(app_icon("application_options"), "Options...", self)
        self.options_action.triggered.connect(self._open_options)
        self.server_test_action = QAction(app_icon("server_test"), "Test Server...", self)
        self.server_test_action.triggered.connect(self._open_server_test)
        self.hardware_test_action = QAction(app_icon("hardware_test"), "Test Hardware...", self)
        self.hardware_test_action.triggered.connect(self._open_hardware_test)
        self.acquisition_action = QAction(app_icon("acquisition"), "Acquisition Control...", self)
        self.acquisition_action.triggered.connect(self._open_acquisition)

        self.install_manual_action = QAction(app_icon("installation_manual"), "Installation Manual...", self)
        self.install_manual_action.triggered.connect(lambda: self._open_manual("docs/INSTALLATION.md"))
        self.user_manual_action = QAction(app_icon("user_manual"), "User Manual...", self)
        self.user_manual_action.triggered.connect(lambda: self._open_manual("docs/USER-MANUAL.md"))
        self.about_action = QAction(app_icon("about"), "About...", self)
        self.about_action.triggered.connect(self._show_about)

        context = get_context()
        is_admin = bool(context and context.identity.role is Role.ADMINISTRATOR)
        self.options_action.setEnabled(is_admin)
        self.acquisition_action.setEnabled(is_admin)
        self.new_station_action.setEnabled(is_admin and self.source != "lan")

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.save_as_action)
        file_menu.addAction(self.save_csv_action)
        file_menu.addSeparator()
        file_menu.addAction(self.printer_setup_action)
        file_menu.addAction(self.print_preview_action)
        file_menu.addAction(self.print_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        view_menu = self.menuBar().addMenu("View")
        for action in self.view_actions:
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.refresh_action)
        view_menu.addAction(self.monitoring_action)

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(self.options_action)
        tools_menu.addAction(self.server_test_action)
        tools_menu.addAction(self.hardware_test_action)
        tools_menu.addAction(self.acquisition_action)

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(self.install_manual_action)
        help_menu.addAction(self.user_manual_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)
        toolbar.addAction(self.exit_action)
        toolbar.addAction(self.save_as_action)
        toolbar.addAction(self.save_csv_action)
        toolbar.addAction(self.print_action)
        toolbar.addSeparator()
        toolbar.addAction(self.new_station_action)
        toolbar.addAction(self.select_period_action)
        toolbar.addAction(self.options_action)
        toolbar.addSeparator()
        toolbar.addAction(self.refresh_action)
        toolbar.addAction(self.monitoring_action)

    def _current_page(self):
        return self.tabs.currentWidget()

    def _save_as(self) -> None:
        page = self._current_page()
        handler = getattr(page, "save_as", None)
        if callable(handler):
            handler()
            return
        self._save_as_csv()

    def _save_as_csv(self) -> None:
        page = self._current_page()
        handler = getattr(page, "export_csv", None)
        if callable(handler):
            handler()
            return
        table = getattr(page, "table", None)
        if table is None:
            QMessageBox.information(self, "Save As CSV", "Tab ini tidak memiliki data tabel untuk diekspor.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Save As CSV", "radmon.csv", "CSV (*.csv)")
        if not filename:
            return
        try:
            with Path(filename).open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=self.preferences.csv_delimiter[:1] or ";")
                writer.writerow(
                    [
                        table.horizontalHeaderItem(column).text()
                        if table.horizontalHeaderItem(column) is not None else ""
                        for column in range(table.columnCount())
                    ]
                )
                for row in range(table.rowCount()):
                    writer.writerow(
                        [
                            table.item(row, column).text() if table.item(row, column) is not None else ""
                            for column in range(table.columnCount())
                        ]
                    )
            QMessageBox.information(self, "Save As CSV", filename)
        except Exception as exc:
            QMessageBox.warning(self, "Save As CSV", str(exc))

    def _printer_setup(self) -> None:
        handler = getattr(self._current_page(), "printer_setup", None)
        if not callable(handler):
            self.tabs.setCurrentIndex(self.REPORT_TAB_INDEX)
            handler = getattr(self.reports_page, "printer_setup", None)
        if callable(handler):
            handler()

    def _print_preview(self) -> None:
        handler = getattr(self._current_page(), "print_preview", None)
        if not callable(handler):
            self.tabs.setCurrentIndex(self.REPORT_TAB_INDEX)
            handler = getattr(self.reports_page, "print_preview", None)
        if callable(handler):
            handler()

    def _select_period_current(self) -> None:
        page = self._current_page()
        handler = getattr(page, "select_period", None)
        if callable(handler):
            handler()
            return
        if page is self.chart_page and hasattr(page, "start") and hasattr(page, "end"):
            from .period_dialog import PeriodSelectionDialog

            dialog = PeriodSelectionDialog(
                page.start.dateTime().toPython(),
                page.end.dateTime().toPython(),
                parent=self,
            )
            if dialog.exec():
                start, end, _grouping = dialog.selection()
                if hasattr(page, "live"):
                    page.live.setChecked(False)
                from PySide6.QtCore import QDateTime

                page.start.setDateTime(QDateTime(start))
                page.end.setDateTime(QDateTime(end))
                if hasattr(page, "apply_range"):
                    page.apply_range()

    def _open_station_editor(self) -> None:
        context = get_context()
        if context is None or context.identity.role is not Role.ADMINISTRATOR:
            QMessageBox.warning(self, "Station properties", "Administrator access required.")
            return
        try:
            station = context.device_admin.repository.get_device(self.settings.serid)
            if station is None:
                raise RuntimeError("station tidak ditemukan")
            dialog = StationAdminDialog(
                context.device_admin,
                context.identity,
                station,
                self,
                source=self.source,
            )
            if dialog.exec():
                self.reload_station_sidebar(select_serid=dialog.serid.value())
                self.recent_page.refresh_live()
        except Exception as exc:
            QMessageBox.warning(self, "Station properties", str(exc))

    def _new_station(self) -> None:
        context = get_context()
        if self.source == "lan":
            QMessageBox.information(
                self,
                "New station",
                "LAN station identity comes directly from the production device table.",
            )
            return
        if context is None or context.identity.role is not Role.ADMINISTRATOR:
            QMessageBox.warning(self, "New station", "Administrator access required.")
            return
        stations = list(self.repository.station_configs())
        candidate = max((station.serid for station in stations), default=0) + 1
        dialog = StationAdminDialog(
            context.device_admin,
            context.identity,
            {
                "serid": candidate,
                "name": "",
                "location": "",
                "description": "",
                "warnlevel": 0,
                "alarmlevel": 0,
                "maxidlemin": 30,
                "unit": "µSv/h",
                "audiopath": "",
                "hwaddress": "",
                "hwtype": "detector",
            },
            self,
            source=self.source,
            is_new=True,
        )
        if dialog.exec():
            self.reload_station_sidebar(select_serid=dialog.serid.value())
            self.recent_page.refresh_live()
            QMessageBox.information(
                self,
                "New station",
                "Station metadata dibuat. Restart local acquisition jika station baru perlu masuk acquisition fleet.",
            )

    def _open_options(self) -> None:
        context = get_context()
        if context is None or context.identity.role is not Role.ADMINISTRATOR:
            QMessageBox.warning(self, "Options", "Administrator access required.")
            return
        dialog = OptionsDialog(self.preferences, self)
        if not dialog.exec():
            return
        self.refresh_timer.setInterval(max(250, int(self.preferences.refresh_interval * 1000)))
        report_dir = Path(self.preferences.report_dir)
        self.base_settings = replace(
            self.base_settings,
            refresh_interval=self.preferences.refresh_interval,
            report_dir=report_dir,
        )
        self.settings = replace(
            self.settings,
            refresh_interval=self.preferences.refresh_interval,
            report_dir=report_dir,
        )
        self.report_service.settings = self.settings
        self.reports_page.settings = self.settings
        self.tabular_page.settings = self.settings
        self.tabular_page.report_service.settings = self.settings
        self.statusBar().showMessage("Options saved.", 4000)

    def _open_server_test(self) -> None:
        ServerTestDialog(self.preferences.server_uri, self).exec()

    def _open_hardware_test(self) -> None:
        HardwareTestDialog(self.base_settings, source=self.source, parent=self).exec()

    def _open_acquisition(self) -> None:
        context = get_context()
        if context is None or context.identity.role is not Role.ADMINISTRATOR:
            QMessageBox.warning(self, "Acquisition Control", "Administrator access required.")
            return
        AcquisitionControlDialog(self.runtime, source=self.source, parent=self).exec()

    def _open_manual(self, relative_path: str) -> None:
        path = (ApplicationPaths.discover().app_dir / relative_path).resolve()
        if not path.is_file():
            QMessageBox.information(self, "Manual", f"Manual belum tersedia: {relative_path}")
            return
        url = QUrl.fromLocalFile(str(path)).toString()
        if not open_external_url(url):
            QMessageBox.warning(self, "Manual", f"Gagal membuka manual di browser: {path}")

    def _show_about(self) -> None:
        AboutDialog(self).exec()

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
            if not getattr(page, "preview_ready", False) and hasattr(page, "build_preview"):
                page.build_preview()
            page.print_report()


    def reload_station_sidebar(self, *, select_serid: int | None = None) -> None:
        context = get_context()
        source_definitions = dict(
            getattr(getattr(context, "device_admin", None), "source_definitions", {})
            if context is not None else {}
        )
        if self.source != "lan" or not source_definitions:
            return self._reload_station_sidebar_base(select_serid=select_serid)

        expanded: dict[str, bool] = {}
        old_root = self.station_tree.topLevelItem(0)
        if old_root is not None:
            for index in range(old_root.childCount()):
                item = old_root.child(index)
                sid = item.data(0, Qt.UserRole + 1)
                if sid:
                    expanded[str(sid)] = item.isExpanded()

        self.station_tree.blockSignals(True)
        self.station_tree.clear()
        root = QTreeWidgetItem(self.station_tree, ["Station"])
        root.setIcon(0, app_icon("station_group"))
        root.setExpanded(True)
        selected_item = None
        try:
            stations = list(self.repository.station_configs())
            mapping = context.device_admin.security.station_source_map()
            groups = group_stations_by_source(
                stations, mapping, source_definitions, _source_health_map()
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Station list error: {exc}")
            groups = []

        for group in groups:
            sid = str(group["source_id"])
            state = str(group["state"])
            host = str(group["host"])
            parent = QTreeWidgetItem(root, [f"Server {_source_label(sid)} · {host} [{state}]"])
            parent.setIcon(0, app_icon("station_group"))
            parent.setData(0, Qt.UserRole + 1, sid)
            parent.setToolTip(0, f"source={sid} · host={host} · state={state}")
            parent.setExpanded(expanded.get(sid, True))
            for station in group["stations"]:
                child = QTreeWidgetItem(parent, [f"[{station.serid}] {station.room}"])
                child.setIcon(0, app_icon("detector"))
                child.setData(0, Qt.UserRole, station.serid)
                child.setToolTip(
                    0,
                    f"[{station.serid}] {station.room} ({station.location}) · "
                    f"Alert {station.warnlevel:g} {station.unit}, "
                    f"Alarm {station.alarmlevel:g} {station.unit}",
                )
                if select_serid is not None and int(station.serid) == int(select_serid):
                    selected_item = child

        if selected_item is None:
            for index in range(root.childCount()):
                parent = root.child(index)
                if parent.childCount():
                    selected_item = parent.child(0)
                    break
        self.station_tree.blockSignals(False)
        if selected_item is not None:
            self.station_tree.setCurrentItem(selected_item)
            self._station_changed(selected_item)

    def _select_station_from_recent(self, serid: int) -> None:
        if self.source != "lan":
            return self._select_station_from_recent_base(serid)
        root = self.station_tree.topLevelItem(0)
        if root is None:
            return
        for group_index in range(root.childCount()):
            parent = root.child(group_index)
            for index in range(parent.childCount()):
                item = parent.child(index)
                if int(item.data(0, Qt.UserRole) or 0) == int(serid):
                    parent.setExpanded(True)
                    self.station_tree.setCurrentItem(item)
                    return

    def _refresh_source_parent_states(self) -> None:
        if self.source != "lan":
            return
        states = _source_health_map()
        context = get_context()
        sources = dict(
            getattr(getattr(context, "device_admin", None), "source_definitions", {})
            if context is not None else {}
        )
        root = self.station_tree.topLevelItem(0)
        if root is None:
            return
        for index in range(root.childCount()):
            parent = root.child(index)
            sid = parent.data(0, Qt.UserRole + 1)
            if not sid:
                continue
            source = sources.get(str(sid))
            host = str(getattr(source, "host", ""))
            state = states.get(str(sid), "UNKNOWN")
            parent.setText(0, f"Server {_source_label(str(sid))} · {host} [{state}]")

    def refresh_all(self) -> None:
        current_serid = getattr(self.settings, "serid", None)
        self.reload_station_sidebar(select_serid=current_serid)
        self._refresh_source_parent_states()
        self.refresh_current_page()
        context = get_context()
        if context is not None and hasattr(self.recent_page, "set_message_rows"):
            try:
                messages = []
                for item in context.source_health.list_states():
                    state = str(item.get("state") or "UNKNOWN")
                    message = f"[SERVER {state}] {item.get('source_id')} / {item.get('host')}"
                    if item.get("last_error") and state in {"DEGRADED", "OFFLINE"}:
                        message += f" - {item.get('last_error')}"
                    messages.append((item.get("updated_at") or "", message))
                self.recent_page.set_message_rows(messages)
            except Exception:
                pass

    def _build_actions(self) -> None:
        self._build_actions_base()
        try:
            self.refresh_action.triggered.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.refresh_action.triggered.connect(self.refresh_all)
        try:
            self.install_manual_action.triggered.disconnect()
            self.user_manual_action.triggered.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.install_manual_action.triggered.connect(
            lambda: self._open_manual(INSTALLATION_MANUAL_PATH)
        )
        self.user_manual_action.triggered.connect(
            lambda: self._open_manual(USER_MANUAL_PATH)
        )

def refresh_current_page(self) -> None:
    page = self.tabs.currentWidget()
    if page is not None and hasattr(page, "refresh_live"):
        page.refresh_live()

    self._open_monitoring_if_ready()
    if self._monitoring_open_pending:
        self.statusBar().showMessage("Grafana sedang disiapkan dan diverifikasi...")
    else:
        error = getattr(page, "last_error", None) if page is not None else None
        mode = {"dummy": "DEMO", "detector": "DETECTOR", "lan": "LAN"}.get(
            self.source, self.source.upper()
        )
        if error:
            self.statusBar().showMessage(f"{mode} · {error}")
        else:
            self.statusBar().showMessage(
                f"{mode} · {self.settings.station_label} · "
                f"refresh {self.preferences.refresh_interval:g}s"
            )

    self._refresh_source_parent_states()
    context = get_context()
    if context is None:
        return
    try:
        active = context.alarm_mirror.list_alarms(active_only=True, limit=1)
    except Exception:
        active = []
    if active:
        now = time.monotonic()
        last = float(getattr(self, "_last_alarm_beep", 0.0))
        if now - last >= 1.5:
            QApplication.beep()
            self._last_alarm_beep = now
