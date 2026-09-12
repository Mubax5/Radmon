from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from .icons import app_icon


ACTIONS = (
    "Confirm to Location",
    "Checked / Condition Normal",
    "Follow-up Required",
    "Other",
)


class AlarmResponseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Alarm Response / Silence")
        self.setWindowIcon(app_icon("alarm"))
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.action = QComboBox()
        self.action.addItems(ACTIONS)
        self.pic = QLineEdit()
        self.pic.returnPressed.connect(self.accept)
        self.note = QPlainTextEdit()
        self.note.setMaximumHeight(100)
        form.addRow("Action", self.action)
        form.addRow("PIC", self.pic)
        form.addRow("Note", self.note)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button = buttons.button(QDialogButtonBox.Ok)
        if button is not None:
            button.setText("Submit / Silence")
            button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
