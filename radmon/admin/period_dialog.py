from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QVBoxLayout,
)


def _midnight(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def period_preset(name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now()).replace(microsecond=0)
    today = _midnight(current)
    if name == "Today":
        return today, current
    if name == "Yesterday":
        return today - timedelta(days=1), today
    if name == "Last 7 days":
        return today - timedelta(days=6), current
    if name == "This month":
        return today.replace(day=1), current
    if name == "Last month":
        this_month = today.replace(day=1)
        previous_day = this_month - timedelta(days=1)
        return previous_day.replace(day=1), this_month
    if name == "This year":
        return today.replace(month=1, day=1), current
    if name == "Last year":
        this_year = today.replace(month=1, day=1)
        return this_year.replace(year=this_year.year - 1), this_year
    raise ValueError(f"preset periode tidak dikenal: {name}")


class PeriodSelectionDialog(QDialog):
    PRESETS = (
        "Today",
        "Yesterday",
        "Last 7 days",
        "This month",
        "Last month",
        "This year",
        "Last year",
    )

    def __init__(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        grouping: str = "Hourly",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Period selection")
        self.setMinimumWidth(430)

        now = datetime.now().replace(microsecond=0)
        start_value = start or _midnight(now)
        end_value = end or now

        period_box = QGroupBox("Period")
        period_layout = QGridLayout(period_box)
        self.start = QDateTimeEdit(QDateTime(start_value))
        self.end = QDateTimeEdit(QDateTime(end_value))
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("dd/MM/yyyy HH:mm:ss")
        form = QFormLayout()
        form.addRow("From", self.start)
        form.addRow("To", self.end)
        period_layout.addLayout(form, 0, 0, len(self.PRESETS), 1)
        for row, name in enumerate(self.PRESETS):
            button = QPushButton(name)
            button.clicked.connect(lambda _checked=False, key=name: self.apply_preset(key))
            period_layout.addWidget(button, row, 1)

        grouping_box = QGroupBox("Grouping")
        grouping_layout = QFormLayout(grouping_box)
        self.grouping = QComboBox()
        self.grouping.addItems(["Raw", "Hourly", "Daily", "Monthly"])
        index = self.grouping.findText(grouping)
        if index >= 0:
            self.grouping.setCurrentIndex(index)
        grouping_layout.addRow("Interval", self.grouping)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_validated)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(period_box)
        layout.addWidget(grouping_box)
        layout.addWidget(buttons)

    def apply_preset(self, name: str, *, now: datetime | None = None) -> None:
        start, end = period_preset(name, now)
        self.start.setDateTime(QDateTime(start))
        self.end.setDateTime(QDateTime(end))

    def _accept_validated(self) -> None:
        start, end, _ = self.selection()
        if start >= end:
            self.end.setFocus()
            return
        self.accept()

    def selection(self) -> tuple[datetime, datetime, str]:
        return (
            self.start.dateTime().toPython(),
            self.end.dateTime().toPython(),
            self.grouping.currentText(),
        )
