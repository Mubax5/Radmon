from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..security import Role, UserIdentity
from .auth_dialogs import PinDialog
from .icons import silk_icon


class UserAdminDialog(QDialog):
    def __init__(self, user_admin, security, identity: UserIdentity, parent=None) -> None:
        super().__init__(parent)
        self.user_admin = user_admin
        self.security = security
        self.identity = identity
        self.setWindowTitle("User Management")
        self.setWindowIcon(silk_icon("lock"))
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Username", "Name", "Role", "Enabled"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        form = QFormLayout()
        self.username = QLineEdit()
        self.display_name = QLineEdit()
        self.role = QComboBox()
        for role in Role:
            self.role.addItem(role.value, role)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.user_pin = QLineEdit()
        self.user_pin.setEchoMode(QLineEdit.Password)
        self.user_pin.setMaxLength(8)
        form.addRow("New username", self.username)
        form.addRow("Name", self.display_name)
        form.addRow("Role", self.role)
        form.addRow("Password", self.password)
        form.addRow("User PIN", self.user_pin)
        layout.addLayout(form)

        actions = QHBoxLayout()
        create = QPushButton(silk_icon("lock"), "Create User")
        create.clicked.connect(self._create)
        toggle = QPushButton(silk_icon("lock"), "Enable / Disable Selected")
        toggle.clicked.connect(self._toggle)
        actions.addWidget(create)
        actions.addWidget(toggle)
        actions.addStretch(1)
        layout.addLayout(actions)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        users = self.security.list_users()
        self.table.setRowCount(len(users))
        for row_index, user in enumerate(users):
            values = [user["username"], user["display_name"], user["role"], "Yes" if user["enabled"] else "No"]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def _admin_pin(self) -> str | None:
        pin, ok = PinDialog.get_pin(
            self,
            title="PIN Administrator",
            message="User management memerlukan PIN Administrator.",
        )
        return pin if ok else None

    def _create(self) -> None:
        pin = self._admin_pin()
        if pin is None:
            return
        try:
            self.user_admin.create_user(
                self.identity,
                pin,
                self.username.text(),
                self.display_name.text(),
                self.role.currentData(),
                self.password.text(),
                self.user_pin.text(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Create User", str(exc))
            return
        self.password.clear()
        self.user_pin.clear()
        self.username.clear()
        self.display_name.clear()
        self.refresh()

    def _toggle(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "User", "Pilih user terlebih dahulu.")
            return
        username = self.table.item(row, 0).text()
        enabled = self.table.item(row, 3).text() == "Yes"
        pin = self._admin_pin()
        if pin is None:
            return
        try:
            self.user_admin.set_enabled(self.identity, pin, username, not enabled)
        except Exception as exc:
            QMessageBox.warning(self, "User", str(exc))
            return
        self.refresh()
