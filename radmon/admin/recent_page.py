from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from radmon.status import classify_status


class RecentPage(QWidget):
    """Legacy-compatible multi-station overview with an embedded Message panel."""

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

    def _stations(self):
        try:
            stations = list(self.repository.station_configs())
        except Exception:
            stations = [self.repository.station_config(self.settings.serid)]
        if not stations:
            stations = [self.repository.station_config(self.settings.serid)]
        return stations

    @staticmethod
    def _history_metrics(rows) -> tuple[float | None, float | None]:
        rates = [float(row["doserate"]) for row in rows if row.get("doserate") is not None]
        average = (sum(rates) / len(rates)) if rates else None
        stored_dose = None
        for row in reversed(rows):
            if row.get("dose") is not None:
                stored_dose = float(row["dose"])
                break
        return average, stored_dose

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

    def refresh_live(self) -> None:
        now = datetime.now()
        stations = self._stations()
        self.table.setRowCount(len(stations))
        errors: list[str] = []

        for row_index, station in enumerate(stations):
            try:
                reading = self.repository.latest_reading(station.serid)
                measured_at = reading.measured_at
                dose_rate = reading.dose_rate
                status = classify_status(
                    dose_rate,
                    measured_at,
                    now,
                    station.warnlevel,
                    station.alarmlevel,
                    station.maxidlemin,
                )
                try:
                    history = self.repository.measurement_history(
                        now - timedelta(minutes=10),
                        now,
                        serid=station.serid,
                        limit=300,
                    )
                except Exception:
                    history = []
                average, stored_dose = self._history_metrics(history)
            except Exception as exc:
                measured_at = None
                dose_rate = None
                average = None
                stored_dose = None
                status = None
                errors.append(f"{station.serid}: {exc}")

            station_item = QTableWidgetItem(station.room)
            station_item.setData(Qt.UserRole, station.serid)
            if int(station.serid) == int(self.settings.serid):
                font = QFont(station_item.font())
                font.setBold(True)
                station_item.setFont(font)

            values = [
                station_item,
                QTableWidgetItem(self._text_time(measured_at)),
                QTableWidgetItem("" if dose_rate is None else f"{float(dose_rate):.2f}"),
                QTableWidgetItem("" if average is None else f"{average:.2f}"),
                QTableWidgetItem("" if stored_dose is None else f"{stored_dose:.7f}"),
                QTableWidgetItem(f"{station.warnlevel:g}"),
                QTableWidgetItem(f"{station.alarmlevel:g}"),
                QTableWidgetItem("●" if status is not None else "—"),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row_index, column, item)

            alarm_item = self.table.item(row_index, 7)
            if status is not None and alarm_item is not None:
                color = {
                    "NORMAL": QColor("#25c83a"),
                    "ALERT": QColor("#e6a700"),
                    "ALARM": QColor("#d92525"),
                    "OFFLINE": QColor("#777777"),
                }[status.value]
                alarm_item.setForeground(color)
                alarm_item.setTextAlignment(Qt.AlignCenter)
                alarm_item.setToolTip(status.value)

        self.last_error = None if not errors else "Recent load partial error: " + "; ".join(errors[:3])
