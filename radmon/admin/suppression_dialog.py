from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)


class SuppressionDialog(QDialog):
    PRESETS = {"5 menit": 5, "15 menit": 15, "30 menit": 30, "60 menit": 60}

    def __init__(
        self,
        *,
        serid: int,
        station_name: str,
        dose_rate: float | None,
        underlying_status: str,
        default_pic: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Suppress Alarm")
        self.setMinimumWidth(480)
        self.serid = int(serid)

        self.detector = QLineEdit(f"{station_name} · SERID {self.serid}")
        self.detector.setReadOnly(True)
        self.dose = QLineEdit("-" if dose_rate is None else f"{float(dose_rate):.4f}")
        self.dose.setReadOnly(True)
        self.status = QLineEdit(str(underlying_status or "-").upper())
        self.status.setReadOnly(True)

        self.duration = QComboBox()
        for label in self.PRESETS:
            self.duration.addItem(label)
        self.duration.addItem("Custom")
        self.custom_minutes = QSpinBox()
        self.custom_minutes.setRange(1, 1440)
        self.custom_minutes.setValue(5)
        self.custom_minutes.setEnabled(False)
        self.duration.currentTextChanged.connect(
            lambda text: self.custom_minutes.setEnabled(text == "Custom")
        )

        self.pic = QLineEdit(default_pic)
        self.pic.setPlaceholderText("PIC / penanggung jawab")
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText("Alasan suppression, mis. calibration/maintenance")
        self.reason.setMaximumHeight(100)

        self.auto_resume = QCheckBox(
            "Aktifkan kembali otomatis saat laju dosis kembali NORMAL"
        )
        self.auto_resume.setChecked(True)

        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setMaxLength(8)
        self.pin.setPlaceholderText("PIN 4-8 digit")

        self.notice = QLabel(
            "Measurements continue during suppression. Nilai dose dan kondisi "
            "aktual tetap direkam/ditampilkan; hanya alarm surfacing dan "
            "notification yang ditekan sementara."
        )
        self.notice.setWordWrap(True)
        self.notice.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("Detector", self.detector)
        form.addRow("Current dose", self.dose)
        form.addRow("Dose status", self.status)
        form.addRow("Duration", self.duration)
        form.addRow("Custom minutes", self.custom_minutes)
        form.addRow("PIC", self.pic)
        form.addRow("Reason", self.reason)
        form.addRow("", self.auto_resume)
        form.addRow("PIN", self.pin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.notice)
        layout.addWidget(buttons)

    def duration_seconds(self) -> int:
        text = self.duration.currentText()
        minutes = self.custom_minutes.value() if text == "Custom" else self.PRESETS[text]
        return int(minutes) * 60

    def _accept_if_valid(self) -> None:
        if not self.pic.text().strip():
            self.pic.setFocus()
            return
        if not self.reason.toPlainText().strip():
            self.reason.setFocus()
            return
        value = self.pin.text().strip()
        if not value.isdigit() or not 4 <= len(value) <= 8:
            self.pin.setFocus()
            return
        self.accept()
