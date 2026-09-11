from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from radmon.secure_context import get_context
from radmon.status import classify_status


class RecentPage(QWidget):
    """Legacy-compatible multi-station live overview backed by ``vrecent``."""

    stationSelected = Signal(int)

    HEADERS = [
        "Station",
        "Measurement Time",
        "Dose Rate [µSv/h]",
        "Avg. Dose Rate [µSv/h]",
        "Approx. Dose [µSv]",
        "Low Threshold",
        "High Threshold",
        "Alarm",
    ]

    def __init__(self, repository, settings, parent=None, *, preferences=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.preferences = preferences
        self.last_error: str | None = None

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("recentOverviewTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._row_clicked)

        self.message_table = QTableWidget(0, 2)
        self.message_table.setObjectName("recentMessageTable")
        self.message_table.setHorizontalHeaderLabels(["Date/Time", "Message"])
        self.message_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.message_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.message_table.verticalHeader().setVisible(False)
        self.message_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.message_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.message_table.setMinimumHeight(130)
        self.message_table.setMaximumHeight(210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("Message"))
        layout.addWidget(self.message_table, 0)
        self.refresh_live()

    @staticmethod
    def _text_time(value) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return "" if value is None else str(value)

    def _row_clicked(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        serid = item.data(Qt.UserRole)
        if serid is not None:
            self.stationSelected.emit(int(serid))

    def set_message_rows(self, rows: list[tuple[object, str]]) -> None:
        self.message_table.setRowCount(len(rows))
        for row_index, (when, message) in enumerate(rows):
            self.message_table.setItem(row_index, 0, QTableWidgetItem(self._text_time(when)))
            self.message_table.setItem(row_index, 1, QTableWidgetItem(str(message)))

    def _policy_snapshot(self, serid: int) -> dict | None:
        context = get_context()
        if context is None or context.alarm_policy is None:
            return None
        try:
            return context.alarm_policy.get_policy(int(serid))
        except Exception:
            return None

    def refresh_live(self) -> None:
        now = datetime.now()
        try:
            rows = list(self.repository.live_rows())
        except Exception as exc:
            self.table.setRowCount(0)
            self.last_error = f"Recent load error: {exc}"
            return

        self.table.setRowCount(len(rows))
        errors: list[str] = []
        for row_index, row in enumerate(rows):
            try:
                serid = int(row["serid"])
                measured_at = row.get("dtom")
                # The real dose is always rendered, including while SUPPRESSED.
                dose_rate = float(row["doserate"]) if row.get("doserate") is not None else None
                warnlevel = float(row.get("warnlevel") or 0)
                alarmlevel = float(row.get("alarmlevel") or 0)
                maxidlemin = int(row.get("maxidlemin") or 30)
                average = float(row["avgrate"]) if row.get("avgrate") is not None else None
                stored_dose = float(row["dose"]) if row.get("dose") is not None else None
                status = classify_status(
                    dose_rate, measured_at, now, warnlevel, alarmlevel, maxidlemin,
                )
            except Exception as exc:
                errors.append(f"row {row_index}: {exc}")
                continue

            station_item = QTableWidgetItem(str(row.get("name") or serid))
            station_item.setData(Qt.UserRole, serid)
            if serid == int(self.settings.serid):
                font = QFont(station_item.font())
                font.setBold(True)
                station_item.setFont(font)

            values = [
                station_item,
                QTableWidgetItem(self._text_time(measured_at)),
                QTableWidgetItem("" if dose_rate is None else f"{dose_rate:.2f}"),
                QTableWidgetItem("" if average is None else f"{average:.2f}"),
                QTableWidgetItem("" if stored_dose is None else f"{stored_dose:.7f}"),
                QTableWidgetItem(f"{warnlevel:g}"),
                QTableWidgetItem(f"{alarmlevel:g}"),
                QTableWidgetItem("●"),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row_index, column, item)

            alarm_item = self.table.item(row_index, 7)
            if alarm_item is not None:
                snapshot = self._policy_snapshot(serid)
                effective = status.value
                tooltip = effective
                if snapshot and snapshot.get("suppressed"):
                    effective = "SUPPRESSED"
                    tooltip = (
                        f"SUPPRESSED · underlying={snapshot.get('underlying_dose_status') or status.value} · "
                        f"PIC={snapshot.get('suppression_pic') or '-'} · "
                        f"Reason={snapshot.get('suppression_reason') or '-'} · "
                        f"Until={self._text_time(snapshot.get('suppression_expires_at')) or '-'} · "
                        f"Dose={'' if dose_rate is None else f'{dose_rate:.2f} µSv/h'}"
                    )
                elif snapshot and snapshot.get("retrigger_locked"):
                    tooltip = f"RETRIGGER LOCKED · underlying={snapshot.get('underlying_dose_status') or status.value}"

                color = {
                    "NORMAL": QColor("#25c83a"),
                    "ALERT": QColor("#e6a700"),
                    "ALARM": QColor("#d92525"),
                    "OFFLINE": QColor("#777777"),
                    "SUPPRESSED": QColor("#6750a4"),
                }.get(effective, QColor("#777777"))
                alarm_item.setForeground(color)
                alarm_item.setTextAlignment(Qt.AlignCenter)
                alarm_item.setText("S" if effective == "SUPPRESSED" else "●")
                alarm_item.setToolTip(tooltip)

        self.last_error = None if not errors else "Recent load partial error: " + "; ".join(errors[:3])
