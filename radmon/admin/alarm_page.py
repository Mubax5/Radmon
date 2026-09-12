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
from .suppression_dialog import SuppressionDialog


class AlarmPage(QWidget):
    HEADERS = [
        "Tag",
        "Event time",
        "Policy",
        "Underlying",
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
        self.info = QLabel("Alarm policy history")

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

        context = get_context()
        can_operate = bool(
            context and context.identity.role in {Role.ADMINISTRATOR, Role.OPERATOR}
        )
        self.ack_button = QPushButton(app_icon("alarm"), "Response / Silence")
        self.ack_button.setToolTip("Isi Action/PIC/Note lalu submit untuk set i_flag=1 pada source.")
        self.ack_button.clicked.connect(self._ack_selected)
        self.ack_button.setEnabled(can_operate)

        self.suppress_button = QPushButton(app_icon("suppress_alarm"), "Suppress Alarm...")
        self.suppress_button.clicked.connect(self._suppress_alarm)
        self.suppress_button.setEnabled(
            bool(can_operate and context and context.alarm_suppression is not None)
        )

        button_row = QHBoxLayout()
        button_row.addWidget(self.ack_button)
        button_row.addWidget(self.suppress_button)
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
        probe = event_time.replace(tzinfo=None) if event_time.tzinfo is not None else event_time
        return start <= probe < end

    def _policy_rows(self):
        context = get_context()
        if context is None or context.alarm_policy is None:
            return None
        start, end = self._range()
        rows = context.alarm_policy.list_events(serid=int(self.settings.serid), limit=2000)
        return [row for row in rows if self._inside(row.get("surfaced_at"), start, end)]

    def _remote_rows(self):
        context = get_context()
        if context is None:
            return None
        start, end = self._range()
        rows = context.alarm_mirror.list_alarms(limit=2000)
        return [
            row for row in rows
            if int(row.get("serid") or 0) == int(self.settings.serid)
            and self._inside(row.get("event_time"), start, end)
        ]

    def refresh_live(self) -> None:
        try:
            policy = self._policy_rows()
            if policy is not None:
                self._render_policy(policy)
            else:
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

    def _render_policy(self, rows) -> None:
        context = get_context()
        snapshot = None
        if context is not None and context.alarm_policy is not None:
            try:
                snapshot = context.alarm_policy.get_policy(int(self.settings.serid))
            except Exception:
                snapshot = None
        underlying = (snapshot or {}).get("underlying_dose_status") or "-"
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            policy_state = "SUPPRESSED" if row.get("kind") == "SUPPRESSED" else row.get("status")
            values = [
                row.get("serid"), row.get("surfaced_at"), policy_state,
                underlying, row.get("threshold"), row.get("measured_value"),
                row.get("trigger_index"), row.get("responded_at"), row.get("pic"),
                row.get("action"), row.get("reason"),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(self._text(value))
                if c == 0:
                    item.setData(Qt.UserRole, row.get("event_id"))
                    item.setData(Qt.UserRole + 1, row)
                    item.setToolTip(
                        f"kind={row.get('kind')} · source={row.get('source_id') or 'central'}"
                    )
                self.table.setItem(r, c, item)

    def _render_remote(self, rows) -> None:
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row.get("serid"), row.get("event_time"), row.get("level"), row.get("level"),
                row.get("threshold"), row.get("measured_value"), row.get("hit_count"),
                row.get("acknowledged_at"), row.get("pic"), row.get("action"), row.get("note"),
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
        start, end = self._range()
        rows = self.repository.alarm_history(start, end, serid=self.settings.serid, limit=2000)
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row.get("serid") or self.settings.serid, row.get("dtom"), row.get("type") or "",
                row.get("type") or "", "", "", "", "", "", row.get("type") or "",
                row.get("msg") or "",
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
            QMessageBox.information(self, "ACK", "Alarm ini tidak dapat direspons.")
            return
        response = AlarmResponseDialog(self)
        if response.exec() != QDialog.Accepted:
            return
        pin, ok = PinDialog.get_pin(
            self, title="PIN Operator",
            message="ACK/Response adalah aksi sensitif dan akan dicatat ke audit log.",
        )
        if not ok:
            return
        try:
            if context.alarm_policy is not None and isinstance(key, str):
                context.alarm_control.respond_policy_event(
                    context.identity, pin, key,
                    action=response.action.currentText(),
                    pic=response.pic.text().strip(),
                    reason=response.note.toPlainText().strip(),
                )
            else:
                source_id, serid, event_time = key
                context.alarm_control.ack(
                    context.identity, pin, str(source_id), int(serid), event_time,
                    action=response.action.currentText(),
                    pic=response.pic.text().strip(),
                    note=response.note.toPlainText().strip(),
                )
        except Exception as exc:
            QMessageBox.warning(self, "ACK / Response", str(exc))
            return
        QMessageBox.information(self, "ACK / Response", "Alarm response berhasil disimpan.")
        self.refresh_live()

    def _suppress_alarm(self) -> None:
        context = get_context()
        if context is None or context.alarm_policy is None or context.alarm_suppression is None:
            QMessageBox.warning(self, "Suppress Alarm", "Alarm suppression tidak tersedia.")
            return
        if context.identity.role not in {Role.ADMINISTRATOR, Role.OPERATOR}:
            QMessageBox.warning(self, "Suppress Alarm", "Role ini tidak diizinkan.")
            return
        snapshot = context.alarm_policy.get_policy(int(self.settings.serid))
        dose_rate = None
        selected = self.table.currentRow()
        if selected >= 0:
            item = self.table.item(selected, 0)
            payload = item.data(Qt.UserRole + 1) if item is not None else None
            if isinstance(payload, dict):
                dose_rate = payload.get("measured_value")
        dialog = SuppressionDialog(
            serid=int(self.settings.serid),
            station_name=str(getattr(self.settings, "location", self.settings.serid)),
            dose_rate=dose_rate,
            underlying_status=snapshot.get("underlying_dose_status") or "UNKNOWN",
            default_pic=context.identity.display_name,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            context.alarm_suppression.start(
                context.identity, dialog.pin.text().strip(), int(self.settings.serid),
                dialog.duration_seconds(), dialog.pic.text().strip(),
                dialog.reason.toPlainText().strip(), dialog.auto_resume.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Suppress Alarm", str(exc))
            return
        QMessageBox.information(self, "Suppress Alarm", "Suppression aktif; measurements tetap berjalan.")
        self.refresh_live()
