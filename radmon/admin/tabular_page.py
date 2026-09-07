from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QCheckBox, QDateTimeEdit, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from radmon.reports import ReportService


class TabularPage(QWidget):
    def __init__(self, repository, settings, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.report_service = ReportService(repository, settings)
        self.last_error: str | None = None
        self.start = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self.end = QDateTimeEdit(QDateTime.currentDateTime())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.live = QCheckBox("Live")
        self.live.setChecked(True)
        self.limit = QSpinBox()
        self.limit.setRange(10, 100000)
        self.limit.setValue(1000)
        export = QPushButton("Export CSV")
        export.clicked.connect(self.export_csv)
        controls = QHBoxLayout()
        for label, widget in (("From", self.start), ("To", self.end), ("Limit", self.limit)):
            controls.addWidget(QLabel(label)); controls.addWidget(widget)
        controls.addWidget(self.live); controls.addWidget(export); controls.addStretch(1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["SERID", "Measurement", "Dose rate", "Dose", "Prev interval", "Stat"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self); layout.addLayout(controls); layout.addWidget(self.table, 1)
        self.refresh_live()

    def range(self):
        return self.start.dateTime().toPython(), self.end.dateTime().toPython()

    def refresh_live(self) -> None:
        if self.live.isChecked():
            self.end.setDateTime(QDateTime.currentDateTime())
        try:
            start, end = self.range()
            rows = self.repository.measurement_history(start, end, serid=self.settings.serid, limit=self.limit.value())
            self.table.setRowCount(len(rows))
            fields = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
            for r, row in enumerate(rows):
                for c, field in enumerate(fields):
                    value = row.get(field)
                    text = value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else ("" if value is None else str(value))
                    self.table.setItem(r, c, QTableWidgetItem(text))
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Tabular load error: {exc}"

    def export_csv(self) -> None:
        start, end = self.range()
        filename, _ = QFileDialog.getSaveFileName(self, "Export CSV", f"measurement-{self.settings.serid}.csv", "CSV (*.csv)")
        if filename:
            try:
                path = self.report_service.export_csv(start, end, Path(filename))
                QMessageBox.information(self, "CSV exported", str(path))
            except Exception as exc:
                QMessageBox.critical(self, "Export error", str(exc))
