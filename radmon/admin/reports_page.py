from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
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
        controls.setContentsMargins(0, 0, 0, 0)
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
        self.preview.setContentsMargins(0, 0, 0, 0)
        self.preview.document().setDocumentMargin(2.0)
        self.preview.setHtml(
            "<h3 style='text-align:center'>Pilih range waktu lalu klik Preview</h3>"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(controls)
        layout.addWidget(self.preview, 1)

    def range(self):
        return self.start.dateTime().toPython(), self.end.dateTime().toPython()

    def _report_directory(self) -> Path:
        directory = Path(self.settings.report_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _output_path(self, suffix: str) -> Path:
        start, end = self.range()
        stamp = f"{start:%Y%m%d-%H%M%S}_to_{end:%Y%m%d-%H%M%S}"
        return self._report_directory() / f"radmon-{self.settings.serid}-{stamp}.{suffix}"

    def build_preview(self) -> None:
        try:
            start, end = self.range()
            self.report_service.settings = self.settings
            html = self.report_service.preview_html(start, end)
            self.preview.setUpdatesEnabled(False)
            self.preview.setHtml(html)
            self.preview.document().setDocumentMargin(2.0)
            self.preview.setUpdatesEnabled(True)
            self.preview_ready = True
            self.print_button.setEnabled(True)
            self.pdf_button.setEnabled(True)
            self.last_error = None
        except Exception as exc:
            self.preview.setUpdatesEnabled(True)
            self.preview_ready = False
            self.print_button.setEnabled(False)
            self.pdf_button.setEnabled(False)
            self.last_error = f"Report preview error: {exc}"

    def refresh_live(self) -> None:
        if self.live.isChecked():
            self.end.setDateTime(QDateTime.currentDateTime())

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
        path = self._output_path("pdf")
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(path))
        self.preview.document().print_(printer)
        QMessageBox.information(self, "PDF exported", str(path))

    def export_csv(self) -> None:
        start, end = self.range()
        path = self._output_path("csv")
        try:
            self.report_service.settings = self.settings
            self.report_service.export_csv(start, end, path)
            QMessageBox.information(self, "CSV exported", str(path))
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))
