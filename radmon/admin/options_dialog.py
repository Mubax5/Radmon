from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .ui_preferences import DesktopPreferences


class OptionsDialog(QDialog):
    def __init__(self, preferences: DesktopPreferences, parent=None) -> None:
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle("Options")
        self.setMinimumWidth(430)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._display_tab(), "Display")
        self.tabs.addTab(self._report_tab(), "File & Report")
        self.tabs.addTab(self._server_tab(), "Server")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def _display_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.refresh_interval = QDoubleSpinBox()
        self.refresh_interval.setRange(0.25, 3600.0)
        self.refresh_interval.setDecimals(2)
        self.refresh_interval.setSuffix(" second(s)")
        self.refresh_interval.setValue(self.preferences.refresh_interval)
        self.date_format = QLineEdit(self.preferences.date_format)
        self.datetime_format = QLineEdit(self.preferences.datetime_format)
        self.dose_rate_format = QLineEdit(self.preferences.dose_rate_format)
        self.dose_format = QLineEdit(self.preferences.dose_format)
        self.threshold_format = QLineEdit(self.preferences.threshold_format)
        self.warning_color = self._color_button(self.preferences.warning_color)
        self.alarm_color = self._color_button(self.preferences.alarm_color)
        form.addRow("Refresh interval", self.refresh_interval)
        form.addRow("Date format", self.date_format)
        form.addRow("Date time format", self.datetime_format)
        form.addRow("Dose rate format", self.dose_rate_format)
        form.addRow("Dose format", self.dose_format)
        form.addRow("Threshold format", self.threshold_format)
        form.addRow("Warning", self.warning_color)
        form.addRow("Alarm", self.alarm_color)
        return page

    def _report_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.csv_delimiter = QLineEdit(self.preferences.csv_delimiter)
        self.csv_delimiter.setMaxLength(4)
        self.report_dir = QLineEdit(self.preferences.report_dir)
        browse = QPushButton("...")
        browse.clicked.connect(self._choose_report_dir)
        report_row = QWidget()
        row_layout = QHBoxLayout(report_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.report_dir, 1)
        row_layout.addWidget(browse)
        self.institution = QLineEdit(self.preferences.institution)
        self.institution_address = QPlainTextEdit(self.preferences.institution_address)
        self.institution_address.setMaximumHeight(80)
        form.addRow("CSV Delimiter", self.csv_delimiter)
        form.addRow("Report Dir", report_row)
        form.addRow("Institution", self.institution)
        form.addRow("Institution Addr.", self.institution_address)
        return page

    def _server_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.server_uri = QLineEdit(self.preferences.server_uri)
        self.api_path = QLineEdit(self.preferences.api_path)
        self.api_version = QLineEdit(self.preferences.api_version)
        self.api_version.setReadOnly(True)
        self.uri_datetime_format = QLineEdit(self.preferences.uri_datetime_format)
        form.addRow("Server URI", self.server_uri)
        form.addRow("API Path", self.api_path)
        form.addRow("API Version", self.api_version)
        form.addRow("URI Date/Time", self.uri_datetime_format)
        return page

    def _color_button(self, value: str) -> QPushButton:
        button = QPushButton(value)
        button.setProperty("radmonColor", value)
        button.setStyleSheet(f"background:{value};")
        button.clicked.connect(lambda _checked=False, active=button: self._choose_color(active))
        return button

    def _choose_color(self, button: QPushButton) -> None:
        current = QColor(str(button.property("radmonColor") or "#ffffff"))
        color = QColorDialog.getColor(current, self, "Color")
        if not color.isValid():
            return
        value = color.name()
        button.setProperty("radmonColor", value)
        button.setText(value)
        button.setStyleSheet(f"background:{value};")

    def _choose_report_dir(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Report directory", self.report_dir.text())
        if value:
            self.report_dir.setText(value)

    def _save(self) -> None:
        self.preferences.refresh_interval = self.refresh_interval.value()
        self.preferences.date_format = self.date_format.text().strip() or "yyyy-MM-dd"
        self.preferences.datetime_format = self.datetime_format.text().strip() or "yyyy-MM-dd HH:mm:ss"
        self.preferences.dose_rate_format = self.dose_rate_format.text().strip() or "0.00"
        self.preferences.dose_format = self.dose_format.text().strip() or "0.0000000"
        self.preferences.threshold_format = self.threshold_format.text().strip() or "0.##"
        self.preferences.warning_color = str(self.warning_color.property("radmonColor") or "#fff3a6")
        self.preferences.alarm_color = str(self.alarm_color.property("radmonColor") or "#ffc4c4")
        self.preferences.csv_delimiter = self.csv_delimiter.text() or ";"
        self.preferences.report_dir = self.report_dir.text().strip() or "!REPORT!"
        self.preferences.institution = self.institution.text().strip() or "Instalasi Pengelolaan Limbah Radioaktif"
        self.preferences.institution_address = self.institution_address.toPlainText().strip()
        self.preferences.server_uri = self.server_uri.text().strip()
        self.preferences.api_path = self.api_path.text().strip() or "/api/v1/control/"
        self.preferences.uri_datetime_format = self.uri_datetime_format.text().strip() or "yyyy-MM-ddTHH:mm:ss"
        self.preferences.save()
        self.accept()
