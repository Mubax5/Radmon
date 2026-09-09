from __future__ import annotations

import calendar
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime
from PySide6.QtPrintSupport import QPageSetupDialog, QPrintDialog, QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .period_dialog import PeriodSelectionDialog


class ReportsPage(QWidget):
    """Range-based report preview; preview is mandatory before print/PDF."""

    def __init__(
        self,
        report_service,
        settings,
        parent=None,
        *,
        archive_catalog=None,
    ) -> None:
        super().__init__(parent)
        self.report_service = report_service
        self.settings = settings
        self.archive_catalog = archive_catalog
        self.last_error: str | None = None
        self.preview_ready = False
        self._printer = QPrinter(QPrinter.HighResolution)

        self.start = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.end = QDateTimeEdit(QDateTime.currentDateTime())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        self.live = QCheckBox("Live")
        self.live.setChecked(False)

        self.archive_selector = QComboBox()
        self.archive_selector.setMinimumWidth(300)
        self.archive_selector.addItem("Active", None)
        self.archive_status = QLabel("Active")
        self._populate_archives()
        self.archive_selector.currentIndexChanged.connect(self._archive_selection_changed)

        period_button = QPushButton("Select period...")
        period_button.clicked.connect(self.select_period)
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
        controls.addWidget(QLabel("Archive"))
        controls.addWidget(self.archive_selector)
        controls.addWidget(self.archive_status)
        controls.addWidget(QLabel("From"))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("To"))
        controls.addWidget(self.end)
        controls.addWidget(self.live)
        controls.addWidget(period_button)
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

    @staticmethod
    def _archive_label(item: dict) -> str:
        quarter_id = str(item.get("quarter_id") or "Archive")
        start_text = str(item.get("start_at") or "")
        try:
            start = datetime.fromisoformat(start_text)
            months = ", ".join(calendar.month_name[month] for month in range(start.month, start.month + 3))
        except (TypeError, ValueError):
            months = "Unknown months"
        state = str(item.get("state") or "UNKNOWN")
        state_label = state.replace("_", " ").title()
        quarter_label = quarter_id.replace("-Q", " Q")
        return f"{quarter_label} · {months} · {state_label}"

    def _populate_archives(self) -> None:
        if self.archive_catalog is None:
            return
        try:
            items = self.archive_catalog.list_archives(limit=1000)
        except Exception as exc:
            self.archive_status.setText(f"Archive index error: {exc}")
            return
        for item in items:
            self.archive_selector.addItem(self._archive_label(item), dict(item))

    def _archive_selection_changed(self, index: int) -> None:
        item = self.archive_selector.itemData(index)
        self.preview_ready = False
        self.print_button.setEnabled(False)
        self.pdf_button.setEnabled(False)
        if not item:
            self.archive_status.setText("Active")
            return
        try:
            start = datetime.fromisoformat(str(item["start_at"]))
            end = datetime.fromisoformat(str(item["end_at"]))
        except (KeyError, TypeError, ValueError):
            self.archive_status.setText("Archive metadata invalid")
            return
        self.start.setDateTime(QDateTime(start.replace(tzinfo=None)))
        self.end.setDateTime(QDateTime(end.replace(tzinfo=None)))
        state = str(item.get("state") or "UNKNOWN")
        self.archive_status.setText(f"Archive · {state}")
        self.live.setChecked(False)

    def range(self):
        return self.start.dateTime().toPython(), self.end.dateTime().toPython()

    def select_period(self) -> None:
        start, end = self.range()
        dialog = PeriodSelectionDialog(start, end, parent=self)
        if not dialog.exec():
            return
        start, end, _grouping = dialog.selection()
        self.live.setChecked(False)
        self.archive_selector.setCurrentIndex(0)
        self.start.setDateTime(QDateTime(start))
        self.end.setDateTime(QDateTime(end))
        self.preview_ready = False
        self.print_button.setEnabled(False)
        self.pdf_button.setEnabled(False)

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
            self.archive_status.setText(self.last_error)

    def refresh_live(self) -> None:
        if self.live.isChecked():
            self.end.setDateTime(QDateTime.currentDateTime())

    def printer_setup(self) -> None:
        QPageSetupDialog(self._printer, self).exec()

    def print_preview(self) -> None:
        if not self.preview_ready:
            self.build_preview()
        if not self.preview_ready:
            return
        dialog = QPrintPreviewDialog(self._printer, self)
        dialog.paintRequested.connect(lambda printer: self.preview.document().print_(printer))
        dialog.exec()

    def print_report(self) -> None:
        if not self.preview_ready:
            return
        dialog = QPrintDialog(self._printer, self)
        if dialog.exec():
            self.preview.document().print_(self._printer)

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

    def save_as(self) -> None:
        self.export_pdf()
