from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class AlarmPage(QWidget):
    def __init__(self, repository, alarm_service, settings, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.last_error: str | None = None
        self.info = QLabel("Alarm events dari tabel ipradmon.alarm")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Alarm ID", "Time", "Type", "Message"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addWidget(self.table, 1)
        self.refresh_live()

    def refresh_live(self) -> None:
        try:
            rows = self.repository.alarm_history(serid=self.settings.serid, limit=500)
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                values = [row.get("alarmid"), row.get("dtom"), row.get("type"), row.get("msg")]
                for c, value in enumerate(values):
                    text = value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else ("" if value is None else str(value))
                    self.table.setItem(r, c, QTableWidgetItem(text))
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Alarm read error: {exc}"
