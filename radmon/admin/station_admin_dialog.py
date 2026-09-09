from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..security import UserIdentity
from .auth_dialogs import PinDialog
from .icons import silk_icon


class StationAdminDialog(QDialog):
    def __init__(
        self,
        device_admin,
        identity: UserIdentity,
        station: dict,
        parent=None,
        *,
        source: str = "detector",
        is_new: bool = False,
    ) -> None:
        super().__init__(parent)
        self.device_admin = device_admin
        self.identity = identity
        self.station = dict(station)
        self.source = source
        self.is_new = bool(is_new)
        self.setWindowTitle("New station..." if self.is_new else "Station properties")
        self.setWindowIcon(silk_icon("feed"))
        self.setMinimumWidth(430)

        self.serid = QSpinBox()
        self.serid.setRange(1, 2_147_483_647)
        self.serid.setValue(max(1, int(station.get("serid") or 1)))
        if source == "lan":
            self.serid.setEnabled(False)
            self.serid.setToolTip("LAN SERID is authoritative from the production device table.")
        self.name = QLineEdit(str(station.get("name") or ""))
        self.location = QLineEdit(str(station.get("location") or ""))
        self.description = QPlainTextEdit(str(station.get("description") or ""))
        self.description.setMaximumHeight(90)

        self.warn = QDoubleSpinBox()
        self.warn.setRange(0, 1_000_000)
        self.warn.setDecimals(6)
        self.warn.setValue(float(station.get("warnlevel") or 0))
        self.alarm = QDoubleSpinBox()
        self.alarm.setRange(0, 1_000_000)
        self.alarm.setDecimals(6)
        self.alarm.setValue(float(station.get("alarmlevel") or 0))
        self.maxidle = QSpinBox()
        self.maxidle.setRange(1, 1440)
        self.maxidle.setValue(int(station.get("maxidlemin") or 30))
        self.audio_path = QLineEdit(str(station.get("audiopath") or ""))
        audio_browse = QPushButton("...")
        audio_browse.clicked.connect(self._choose_audio)
        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(self.audio_path, 1)
        audio_layout.addWidget(audio_browse)

        self.hw_type = QLineEdit(str(station.get("hwtype") or "detector"))
        self.hw_address = QLineEdit(str(station.get("hwaddress") or ""))
        self.unit = QLineEdit(str(station.get("unit") or "µSv/h"))

        tabs = QTabWidget()
        tabs.addTab(self._attributes_tab(), "Attributes")
        tabs.addTab(self._alarm_tab(audio_row), "Alarm")
        tabs.addTab(self._hardware_tab(), "Hardware")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _attributes_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Tag / SERID", self.serid)
        form.addRow("Name", self.name)
        form.addRow("Location", self.location)
        form.addRow("Description", self.description)
        return page

    def _alarm_tab(self, audio_row: QWidget) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Low Threshold", self.warn)
        form.addRow("High Threshold", self.alarm)
        form.addRow("Max Idle", self.maxidle)
        form.addRow("Audio path", audio_row)
        return page

    def _hardware_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Type", self.hw_type)
        form.addRow("Address", self.hw_address)
        form.addRow("Unit", self.unit)
        return page

    def _choose_audio(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Audio path",
            self.audio_path.text(),
            "Audio (*.wav *.mp3);;All files (*.*)",
        )
        if filename:
            self.audio_path.setText(filename)

    def _values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "location": self.location.text().strip(),
            "description": self.description.toPlainText().strip(),
            "warnlevel": self.warn.value(),
            "alarmlevel": self.alarm.value(),
            "maxidlemin": self.maxidle.value(),
            "unit": self.unit.text().strip() or "µSv/h",
            "audiopath": self.audio_path.text().strip(),
            "hwaddress": self.hw_address.text().strip(),
            "hwtype": self.hw_type.text().strip() or "detector",
        }

    def _save(self) -> None:
        if self.warn.value() > self.alarm.value() and self.alarm.value() > 0:
            QMessageBox.warning(self, "Station properties", "Low Threshold harus <= High Threshold.")
            return
        if self.source == "lan" and self.is_new:
            QMessageBox.warning(
                self,
                "New station",
                "LAN station dibuat dari device.serid production dan tidak boleh dibuat manual.",
            )
            return
        pin, ok = PinDialog.get_pin(
            self,
            title="PIN Administrator",
            message="Perubahan konfigurasi station adalah aksi sensitif.",
        )
        if not ok:
            return
        values = self._values()
        try:
            if self.is_new:
                self.device_admin.create_station(
                    self.identity,
                    pin,
                    self.serid.value(),
                    values,
                )
            else:
                old_serid = int(self.station["serid"])
                self.device_admin.update_station(self.identity, pin, old_serid, values)
                new_serid = self.serid.value()
                if self.source != "lan" and new_serid != old_serid:
                    self.device_admin.migrate_serid(self.identity, pin, old_serid, new_serid)
        except Exception as exc:
            QMessageBox.warning(self, "Station properties", str(exc))
            return
        self.accept()
