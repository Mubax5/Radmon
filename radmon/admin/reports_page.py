from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class ReportsPage(QWidget):
    """Range-based report preview; preview is mandatory before print/PDF."""

    def __init__(self, report_service, settings, parent=None) -> None:
        super().__init__(parent)
        self.report_service = report_service
        self.settings = settings
        self.last_error: str | None = None
        self.preview_ready = False

        self.start = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.end = QDateTimeEdit(QDateTime.currentDateTime())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        self.live = QCheckBox("Live")
        self.live.setChecked(False)

        preview_button = QPushButton("Preview")
        preview_button.clicked.connect(self.build_preview)
        self.print_button = QPushButton("Print")
        self.print_button.setEnabled(False)
        self.print_button.clicked.connect(self.print_report)
        self.pdf_button = QPushButton("Export PDF")
        self.pdf_button.setEnabled(False)
        self.pdf_button.clicked.connect(self.export_pdf)
        csv_button = QPushButton("Export CSV")
        csv_button.clicked.connect(self.export_csv)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("From"))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("To"))
        controls.addWidget(self.end)
        controls.addWidget(self.live)
        controls.addWidget(preview_button)
        controls.addWidget(self.print_button)
        controls.addWidget(self.pdf_button)
        controls.addWidget(csv_button)
        controls.addStretch(1)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setHtml(
            "<h3 style='text-align:center'>Pilih range waktu lalu klik Preview</h3>"
        )

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.preview, 1)

    def range(self):
        return self.start.dateTime().toPython(), self.end.dateTime().toPython()

    def build_preview(self) -> None:
        try:
            start, end = self.range()
            html = self.report_service.preview_html(start, end)
            self.preview.setHtml(html)
            self.preview_ready = True
            self.print_button.setEnabled(True)
            self.pdf_button.setEnabled(True)
            self.last_error = None
        except Exception as exc:
            self.preview_ready = False
            self.print_button.setEnabled(False)
            self.pdf_button.setEnabled(False)
            self.last_error = f"Report preview error: {exc}"

    def refresh_live(self) -> None:
        if self.live.isChecked() and self.preview_ready:
            self.end.setDateTime(QDateTime.currentDateTime())
            self.build_preview()

    def print_report(self) -> None:
        if not self.preview_ready:
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec():
            self.preview.document().print_(printer)

    def export_pdf(self) -> None:
        if not self.preview_ready:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export PDF",
            f"radmon-{self.settings.serid}.pdf",
            "PDF (*.pdf)",
        )
        if not filename:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(filename)
        self.preview.document().print_(printer)
        QMessageBox.information(self, "PDF exported", filename)

    def export_csv(self) -> None:
        start, end = self.range()
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            f"measurement-{self.settings.serid}.csv",
            "CSV (*.csv)",
        )
        if not filename:
            return
        try:
            self.report_service.export_csv(start, end, Path(filename))
            QMessageBox.information(self, "CSV exported", filename)
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))
