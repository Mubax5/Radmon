from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDateTimeEdit, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class ReportsPage(QWidget):
    def __init__(self, report_service, settings, parent=None):
        super().__init__(parent); self.report_service = report_service; self.settings = settings; self.last_pdf = None
        self.start = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1)); self.end = QDateTimeEdit(QDateTime.currentDateTime())
        for w in (self.start, self.end): w.setCalendarPopup(True); w.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        preview = QPushButton("Preview recap"); preview.clicked.connect(self.refresh)
        export = QPushButton("Export PDF"); export.clicked.connect(self.export_pdf)
        open_pdf = QPushButton("Open / Print last PDF"); open_pdf.clicked.connect(self.open_pdf)
        controls = QHBoxLayout(); controls.addWidget(QLabel("From")); controls.addWidget(self.start); controls.addWidget(QLabel("To")); controls.addWidget(self.end); controls.addWidget(preview); controls.addWidget(export); controls.addWidget(open_pdf); controls.addStretch(1)
        self.summary = QTableWidget(1, 7); self.summary.setHorizontalHeaderLabels(["First", "Last", "Min", "Average", "Max", "Samples", "Approx. Dose"])
        self.detail = QTableWidget(0, 3); self.detail.setHorizontalHeaderLabels(["Measurement", "Dose rate", "Stat"]); self.detail.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self); layout.addLayout(controls); layout.addWidget(QLabel("Summary")); layout.addWidget(self.summary); layout.addWidget(QLabel("Measurement preview")); layout.addWidget(self.detail, 1)
        self.refresh()

    def range(self): return self.start.dateTime().toPython(), self.end.dateTime().toPython()

    def refresh(self):
        try:
            start, end = self.range(); summary = self.report_service.summary(start, end); rows = self.report_service.rows(start, end, limit=500)
            values = [summary.first_measurement, summary.last_measurement, summary.minimum, summary.average, summary.maximum, summary.sample_count, summary.approximate_dose]
            for c, value in enumerate(values):
                if hasattr(value, "strftime"): text = value.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(value, float): text = f"{value:.6f}"
                else: text = str(value) if value is not None else "-"
                self.summary.setItem(0, c, QTableWidgetItem(text))
            self.detail.setRowCount(len(rows))
            for r, row in enumerate(rows):
                vals = [row.get("dtom"), row.get("doserate"), row.get("stat")]
                for c, value in enumerate(vals):
                    text = value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else str(value)
                    self.detail.setItem(r, c, QTableWidgetItem(text))
        except Exception as exc: QMessageBox.critical(self, "Report error", str(exc))

    def export_pdf(self):
        start, end = self.range(); filename, _ = QFileDialog.getSaveFileName(self, "Export PDF", f"radmon-{self.settings.serid}.pdf", "PDF (*.pdf)")
        if filename:
            try:
                self.last_pdf = self.report_service.export_pdf(start, end, Path(filename)); QMessageBox.information(self, "PDF exported", str(self.last_pdf))
            except Exception as exc: QMessageBox.critical(self, "Export error", str(exc))

    def open_pdf(self):
        if self.last_pdf and Path(self.last_pdf).is_file(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.last_pdf).resolve())))
        else: QMessageBox.information(self, "Report", "Belum ada PDF yang diekspor pada sesi ini.")
