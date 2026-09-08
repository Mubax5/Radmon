from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..secure_context import get_context
from ..security import Role
from .alarm_response_dialog import AlarmResponseDialog
from .auth_dialogs import PinDialog
from .icons import silk_icon


class AlarmPage(QWidget):
    def __init__(self, repository, alarm_service, settings, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.last_error: str | None = None
        self.info = QLabel("Alarm events dari central ipradmon dan source LAN")
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "Source", "Event time", "Level", "Dose rate", "Threshold", "Hit",
            "Action Time", "PIC", "Action", "Note", "Tag",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.ack_button = QPushButton(silk_icon("lock"), "ACK / Response")
        self.ack_button.clicked.connect(self._ack_selected)
        context = get_context()
        self.ack_button.setEnabled(
            bool(context and context.identity.role in {Role.ADMINISTRATOR, Role.OPERATOR})
        )

        button_row = QHBoxLayout()
        button_row.addWidget(self.ack_button)
        button_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
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

    def _remote_rows(self):
        context = get_context()
        if context is None:
            return None
        rows = context.alarm_mirror.list_alarms(limit=500)
        return [row for row in rows if int(row.get("serid") or 0) == int(self.settings.serid)]

    def refresh_live(self) -> None:
        try:
            remote = self._remote_rows()
            if remote is not None:
                self._render_remote(remote)
            else:
                self._render_local()
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Alarm read error: {exc}"

    def _render_remote(self, rows) -> None:
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "Source", "Event time", "Level", "Dose rate", "Threshold", "Hit",
            "Action Time", "PIC", "Action", "Note", "Tag",
        ])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row.get("source_id"),
                row.get("event_time"),
                row.get("level"),
                row.get("measured_value"),
                row.get("threshold"),
                row.get("hit_count"),
                row.get("acknowledged_at"),
                row.get("pic"),
                row.get("action"),
                row.get("note"),
                row.get("serid"),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(self._text(value))
                if c == 0:
                    item.setData(
                        Qt.UserRole,
                        (row.get("source_id"), int(row.get("serid")), row.get("event_time")),
                    )
                self.table.setItem(r, c, item)

    def _render_local(self) -> None:
        rows = self.repository.alarm_history(serid=self.settings.serid, limit=500)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Alarm ID", "Time", "Type", "Message"])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [row.get("alarmid"), row.get("dtom"), row.get("type"), row.get("msg")]
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
        QMessageBox.information(self, "ACK / Response", "Alarm response berhasil disimpan ke source dan audit log.")
        self.refresh_live()
