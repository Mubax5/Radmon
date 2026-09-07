from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from radmon.status import classify_status, trend_code, trend_symbol


class RecentPage(QWidget):
    def __init__(self, repository, settings, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.last_error: str | None = None
        self.dose = QLabel("--- µSv/h")
        self.dose.setAlignment(Qt.AlignCenter)
        self.dose.setStyleSheet("font-size: 42px; font-weight: 700;")
        self.state = QLabel("OFFLINE")
        self.state.setAlignment(Qt.AlignCenter)
        self.state.setStyleSheet("font-size: 24px; font-weight: 700; padding: 8px;")
        self.info = QLabel()
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Dose rate (µSv/h)", "Prev interval", "Stat"])
        self.table.horizontalHeader().setStretchLastSection(True)
        cards = QGridLayout()
        cards.addWidget(self._box("Current dose rate", self.dose), 0, 0)
        cards.addWidget(self._box("Status", self.state), 0, 1)
        cards.addWidget(self._box("Station information", self.info), 0, 2)
        layout = QVBoxLayout(self)
        layout.addLayout(cards)
        layout.addWidget(QLabel("Recent measurements"))
        layout.addWidget(self.table, 1)
        self.refresh_live()

    @staticmethod
    def _box(title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.addWidget(widget)
        return box

    def refresh_live(self) -> None:
        try:
            reading = self.repository.latest_reading(self.settings.serid)
            station = reading.station
            now = datetime.now()
            status = classify_status(reading.dose_rate, reading.measured_at, now, station.warnlevel, station.alarmlevel, station.maxidlemin)
            trend = "OFFLINE" if status.value == "OFFLINE" else trend_code(reading.dose_rate, reading.previous_dose_rate)
            self.dose.setText("--- µSv/h" if reading.dose_rate is None else f"{reading.dose_rate:.3f} µSv/h  {trend_symbol(trend)}")
            self.state.setText(status.value)
            colors = {"NORMAL": "#258a45", "ALERT": "#d77b00", "ALARM": "#b51f1f", "OFFLINE": "#6b4380"}
            self.state.setStyleSheet(f"font-size:24px;font-weight:700;padding:8px;color:white;background:{colors[status.value]};")
            if reading.measured_at:
                self.info.setText(
                    f"ID: {station.serid}\nName: {station.room}\nLocation: {station.location}\n"
                    f"Alert: {station.warnlevel:g} µSv/h\nAlarm: {station.alarmlevel:g} µSv/h\n"
                    f"Last: {reading.measured_at:%Y-%m-%d %H:%M:%S}"
                )
            else:
                self.info.setText(f"ID: {station.serid}\nName: {station.room}\nLocation: {station.location}\nNO DATA")
            rows = self.repository.measurement_history(now - timedelta(minutes=10), now, serid=station.serid, limit=20)
            self.table.setRowCount(len(rows))
            for r, row in enumerate(reversed(rows)):
                values = [row.get("dtom"), row.get("doserate"), row.get("previnterval"), row.get("stat")]
                for c, value in enumerate(values):
                    text = value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else (f"{value:.4f}" if isinstance(value, float) else str(value))
                    self.table.setItem(r, c, QTableWidgetItem(text))
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Database/read error: {exc}"
            self.state.setText("OFFLINE")
