from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ..security import UserIdentity
from .auth_dialogs import PinDialog
from .icons import silk_icon


class StationAdminDialog(QDialog):
    def __init__(self, device_admin, identity: UserIdentity, station: dict, parent=None) -> None:
        super().__init__(parent)
        self.device_admin = device_admin
        self.identity = identity
        self.station = dict(station)
        self.setWindowTitle(f"Edit Station [{station['serid']}]")
        self.setWindowIcon(silk_icon("feed"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(str(station.get("name") or ""))
        self.location = QLineEdit(str(station.get("location") or ""))
        self.description = QLineEdit(str(station.get("description") or ""))
        self.warn = QDoubleSpinBox()
        self.warn.setRange(0, 1_000_000)
        self.warn.setDecimals(4)
        self.warn.setValue(float(station.get("warnlevel") or 0))
        self.alarm = QDoubleSpinBox()
        self.alarm.setRange(0, 1_000_000)
        self.alarm.setDecimals(4)
        self.alarm.setValue(float(station.get("alarmlevel") or 0))
        self.maxidle = QSpinBox()
        self.maxidle.setRange(1, 1440)
        self.maxidle.setValue(int(station.get("maxidlemin") or 30))
        self.unit = QLineEdit(str(station.get("unit") or "µSv/h"))
        self.serid = QSpinBox()
        self.serid.setRange(1, 2_147_483_647)
        self.serid.setValue(int(station["serid"]))

        form.addRow("Tag / SERID", self.serid)
        form.addRow("Name", self.name)
        form.addRow("Location", self.location)
        form.addRow("Description", self.description)
        form.addRow("Alert threshold", self.warn)
        form.addRow("Alarm threshold", self.alarm)
        form.addRow("Max idle (min)", self.maxidle)
        form.addRow("Unit", self.unit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        pin, ok = PinDialog.get_pin(
            self,
            title="PIN Administrator",
            message="Perubahan konfigurasi station adalah aksi sensitif.",
        )
        if not ok:
            return
        old_serid = int(self.station["serid"])
        changes = {
            "name": self.name.text().strip(),
            "location": self.location.text().strip(),
            "description": self.description.text().strip(),
            "warnlevel": self.warn.value(),
            "alarmlevel": self.alarm.value(),
            "maxidlemin": self.maxidle.value(),
            "unit": self.unit.text().strip() or "µSv/h",
        }
        try:
            self.device_admin.update_station(self.identity, pin, old_serid, changes)
            new_serid = self.serid.value()
            if new_serid != old_serid:
                self.device_admin.migrate_serid(self.identity, pin, old_serid, new_serid)
        except Exception as exc:
            QMessageBox.warning(self, "Edit Station", str(exc))
            return
        self.accept()
