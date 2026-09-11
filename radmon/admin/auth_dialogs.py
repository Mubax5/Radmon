from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..security import Role, SecurityStore, UserIdentity
from .icons import app_icon


class LoginDialog(QDialog):
    def __init__(self, security: SecurityStore, parent=None) -> None:
        super().__init__(parent)
        self.security = security
        self.identity: UserIdentity | None = None
        self.setWindowTitle("RadMon Login")
        self.setWindowIcon(app_icon("users"))
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Restricted Radiation Monitoring System"))
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password.returnPressed.connect(self._login)

    def _login(self) -> None:
        identity = self.security.authenticate(self.username.text(), self.password.text())
        self.password.clear()
        if identity is None:
            QMessageBox.warning(self, "Login", "Username atau password tidak valid.")
            return
        self.identity = identity
        self.accept()


class BootstrapAdminDialog(QDialog):
    """Local-only first-run bootstrap; no default password/PIN is hard-coded."""

    def __init__(self, security: SecurityStore, parent=None) -> None:
        super().__init__(parent)
        self.security = security
        self.identity: UserIdentity | None = None
        self.setWindowTitle("RadMon - Buat Administrator Pertama")
        self.setWindowIcon(app_icon("users"))
        self.setModal(True)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Belum ada akun RadMon. Buat Administrator pertama. "
            "Password dan PIN akan disimpan sebagai salted hash."
        ))
        form = QFormLayout()
        self.username = QLineEdit("admin")
        self.display_name = QLineEdit("Administrator")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setMaxLength(8)
        form.addRow("Username", self.username)
        form.addRow("Nama", self.display_name)
        form.addRow("Password", self.password)
        form.addRow("PIN 4-8 digit", self.pin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create(self) -> None:
        try:
            self.identity = self.security.create_user(
                self.username.text(),
                self.display_name.text(),
                Role.ADMINISTRATOR,
                self.password.text(),
                self.pin.text(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Administrator", str(exc))
            return
        self.password.clear()
        self.pin.clear()
        self.accept()


class PinDialog(QDialog):
    def __init__(self, title: str = "Verifikasi PIN", message: str = "Masukkan PIN untuk melanjutkan.", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon("users"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(message))
        form = QFormLayout()
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setMaxLength(8)
        form.addRow("PIN", self.pin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.pin.returnPressed.connect(self.accept)

    @classmethod
    def get_pin(cls, parent=None, *, title: str = "Verifikasi PIN", message: str = "Masukkan PIN untuk melanjutkan.") -> tuple[str, bool]:
        dialog = cls(title=title, message=message, parent=parent)
        accepted = dialog.exec() == QDialog.Accepted
        value = dialog.pin.text() if accepted else ""
        dialog.pin.clear()
        return value, accepted
