from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from radmon.secure_context import get_context
from radmon.status import classify_status
from radmon.formatting import format_dose_value


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

        self.last_readings_table = QTableWidget(0, 4)
        self.last_readings_table.setObjectName("recentLastReadingsTable")
        self.last_readings_table.setHorizontalHeaderLabels(
            ["Station", "Original Measurement Time", "Dose Rate [µSv/h]", "Data Status"]
        )
        self.last_readings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.last_readings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.last_readings_table.verticalHeader().setVisible(False)
        self.last_readings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.last_readings_table.horizontalHeader().setStretchLastSection(True)
        self.last_readings_table.setMinimumHeight(130)
        self.last_readings_table.setMaximumHeight(260)

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
        layout.addWidget(QLabel("Last readings (up to 30 genuine samples per station; original timestamps)"))
        layout.addWidget(self.last_readings_table, 0)
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
                QTableWidgetItem("" if dose_rate is None else format_dose_value(dose_rate)),
                QTableWidgetItem("" if average is None else format_dose_value(average)),
                QTableWidgetItem("" if stored_dose is None else format_dose_value(stored_dose)),
                QTableWidgetItem(format_dose_value(warnlevel)),
                QTableWidgetItem(format_dose_value(alarmlevel)),
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
                        f"Dose={'' if dose_rate is None else f'{format_dose_value(dose_rate)} µSv/h'}"
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

        self._refresh_last_readings(rows, now)
        self.last_error = None if not errors else "Recent load partial error: " + "; ".join(errors[:3])

    def _refresh_last_readings(self, live_rows: list[dict], now: datetime) -> None:
        """Render several genuine timestamped readings, including stale ones."""
        reader = getattr(self.repository, "last_readings", None)
        if not callable(reader):
            self.last_readings_table.setRowCount(0)
            return
        try:
            readings = list(reader(limit=30))
        except Exception as exc:
            self.last_readings_table.setRowCount(0)
            self.last_error = f"Last readings load error: {exc}"
            return
        station_meta = {
            int(row["serid"]): row for row in live_rows if row.get("serid") is not None
        }
        self.last_readings_table.setRowCount(len(readings))
        for index, reading in enumerate(readings):
            serid = int(reading["serid"])
            station = station_meta.get(serid, {})
            measured_at = reading.get("dtom")
            try:
                status = classify_status(
                    float(reading.get("doserate")) if reading.get("doserate") is not None else None,
                    measured_at,
                    now,
                    float(station.get("warnlevel") or 0),
                    float(station.get("alarmlevel") or 0),
                    int(station.get("maxidlemin") or 30),
                ).value
            except Exception:
                status = "OFFLINE"
            if status == "OFFLINE":
                status = "OFFLINE · LAST READING"
            values = (
                str(station.get("name") or serid),
                self._text_time(measured_at),
                "" if reading.get("doserate") is None else format_dose_value(reading["doserate"]),
                status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if status.startswith("OFFLINE"):
                    item.setForeground(QColor("#777777"))
                self.last_readings_table.setItem(index, column, item)
