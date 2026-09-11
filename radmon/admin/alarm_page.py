from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..secure_context import get_context
from ..security import Role
from .alarm_response_dialog import AlarmResponseDialog
from .auth_dialogs import PinDialog
from .icons import app_icon


class AlarmPage(QWidget):
    HEADERS = [
        "Tag",
        "Event time",
        "Threshold",
        "Dose rate",
        "Hit count",
        "Action Time",
        "PIC",
        "Action",
        "Note",
    ]

    def __init__(self, repository, alarm_service, settings, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.last_error: str | None = None
        self.info = QLabel("Alarm history")

        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.days = QSpinBox()
        self.days.setRange(1, 3660)
        self.days.setValue(1)
        self.days.setSuffix(" day(s)")
        self.date.dateChanged.connect(lambda _value: self.refresh_live())
        self.days.valueChanged.connect(lambda _value: self.refresh_live())

        range_row = QHBoxLayout()
        range_row.addWidget(self.info)
        range_row.addStretch(1)
        range_row.addWidget(self.date)
        range_row.addWidget(self.days)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.ack_button = QPushButton(app_icon("alarm"), "ACK / Response")
        self.ack_button.clicked.connect(self._ack_selected)
        context = get_context()
        self.ack_button.setEnabled(
            bool(context and context.identity.role in {Role.ADMINISTRATOR, Role.OPERATOR})
        )

        button_row = QHBoxLayout()
        button_row.addWidget(self.ack_button)
        button_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(range_row)
        layout.addLayout(button_row)
        layout.addWidget(self.table, 1)
        self.refresh_live()

    @staticmethod
    def _text(value) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    def _range(self) -> tuple[datetime, datetime]:
        start = self.date.date().startOfDay().toPython()
        end = start + timedelta(days=self.days.value())
        return start, end

    @staticmethod
    def _inside(event_time, start: datetime, end: datetime) -> bool:
        if not isinstance(event_time, datetime):
            return True
        return start <= event_time < end

    def _remote_rows(self):
        context = get_context()
        if context is None:
            return None
        start, end = self._range()
        rows = context.alarm_mirror.list_alarms(limit=2000)
        return [
            row
            for row in rows
            if int(row.get("serid") or 0) == int(self.settings.serid)
            and self._inside(row.get("event_time"), start, end)
        ]

    def refresh_live(self) -> None:
        try:
            remote = self._remote_rows()
            if remote is not None:
                self._render_remote(remote)
            else:
                self._render_local()
            start, end = self._range()
            self.info.setText(
                f"Load {self.table.rowCount()} record(s) between {start:%Y-%m-%d} and {end:%Y-%m-%d}"
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Alarm read error: {exc}"
            self.info.setText(self.last_error)

    def _render_remote(self, rows) -> None:
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row.get("serid"),
                row.get("event_time"),
                row.get("threshold"),
                row.get("measured_value"),
                row.get("hit_count"),
                row.get("acknowledged_at"),
                row.get("pic"),
                row.get("action"),
                row.get("note"),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(self._text(value))
                if c == 0:
                    item.setData(
                        Qt.UserRole,
                        (row.get("source_id"), int(row.get("serid")), row.get("event_time")),
                    )
                    item.setToolTip(
                        f"source={row.get('source_id')} · level={row.get('level') or '-'}"
                    )
                self.table.setItem(r, c, item)

    def _render_local(self) -> None:
        start, end = self._range()
        rows = self.repository.alarm_history(
            start,
            end,
            serid=self.settings.serid,
            limit=2000,
        )
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            message = row.get("msg") or ""
            values = [
                row.get("serid") or self.settings.serid,
                row.get("dtom"),
                "",
                "",
                "",
                "",
                "",
                row.get("type") or "",
                message,
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(self._text(value)))

    def _ack_selected(self) -> None:
        context = get_context()
        if context is None:
            QMessageBox.warning(self, "ACK", "Security context tidak aktif.")
            return
        if context.identity.role not in {Role.ADMINISTRATOR, Role.OPERATOR}:
            QMessageBox.warning(self, "ACK", "Role ini tidak diizinkan melakukan ACK.")
            return
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "ACK", "Pilih alarm yang akan direspons.")
            return
        first = self.table.item(row, 0)
        key = first.data(Qt.UserRole) if first is not None else None
        if not key:
            QMessageBox.information(self, "ACK", "Alarm ini bukan alarm LAN yang dapat di-ACK.")
            return
        source_id, serid, event_time = key
        response = AlarmResponseDialog(self)
        if response.exec() != QDialog.Accepted:
            return
        pin, ok = PinDialog.get_pin(
            self,
            title="PIN Operator",
            message="ACK/Response adalah aksi sensitif dan akan dicatat ke audit log.",
        )
        if not ok:
            return
        try:
            context.alarm_control.ack(
                context.identity,
                pin,
                str(source_id),
                int(serid),
                event_time,
                action=response.action.currentText(),
                pic=response.pic.text().strip(),
                note=response.note.toPlainText().strip(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "ACK / Response", str(exc))
            return
        QMessageBox.information(
            self,
            "ACK / Response",
            "Alarm response berhasil disimpan ke source dan audit log.",
        )
        self.refresh_live()
