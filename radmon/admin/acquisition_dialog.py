from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout


class AcquisitionControlDialog(QDialog):
    def __init__(self, runtime, *, source: str, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.source = source
        self.setWindowTitle("Acquisition Control")
        self.setMinimumWidth(390)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.toggle = QPushButton()
        self.toggle.clicked.connect(self._toggle)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addWidget(self.toggle)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self) -> None:
        if self.source == "lan" or self.runtime is None:
            self.info.setText(
                "LAN acquisition is owned by central_server.py. "
                "This desktop is a monitoring/control client and cannot start a second LAN collector."
            )
            self.toggle.setText("LAN collector controlled by central server")
            self.toggle.setEnabled(False)
            return

        paused = bool(self.runtime.is_paused)
        state = "PAUSED" if paused else "RUNNING"
        self.info.setText(
            f"Local {self.source.upper()} acquisition: {state}. "
            "Pause releases detector acquisition until Resume is selected."
        )
        self.toggle.setText("Resume acquisition" if paused else "Pause acquisition")
        self.toggle.setEnabled(True)

    def _toggle(self) -> None:
        if self.runtime is None or self.source == "lan":
            return
        if self.runtime.is_paused:
            self.runtime.resume()
        else:
            self.runtime.pause()
        self._refresh()
