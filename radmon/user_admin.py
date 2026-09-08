from __future__ import annotations

from .audit import AuditTrail
from .security import Role, SecurityStore, UserIdentity


class UserAdminService:
    def __init__(self, security: SecurityStore, audit: AuditTrail) -> None:
        self.security = security
        self.audit = audit

    def create_user(
        self,
        identity: UserIdentity,
        pin: str,
        username: str,
        display_name: str,
        role: Role | str,
        password: str,
        user_pin: str,
    ):
        self.security.require_sensitive(identity, "manage_users", pin)
        selected_role = role if isinstance(role, Role) else Role(role)
        safe_after = {"display_name": display_name, "role": selected_role.value, "enabled": True}
        try:
            created = self.security.create_user(
                username, display_name, selected_role, password, user_pin, actor=identity.username
            )
        except Exception as exc:
            self.audit.record(
                "USER_CREATE", identity, "user", username,
                after=safe_after, success=False, reason=str(exc)
            )
            raise
        self.audit.record("USER_CREATE", identity, "user", created.username, after=safe_after)
        return created

    def set_enabled(self, identity: UserIdentity, pin: str, username: str, enabled: bool) -> None:
        self.security.require_sensitive(identity, "manage_users", pin)
        before = next((row for row in self.security.list_users() if row["username"] == username), None)
        if before is None:
            raise ValueError("user tidak ditemukan")
        if identity.username == username and not enabled:
            raise ValueError("Administrator tidak dapat menonaktifkan akun yang sedang dipakai")
        self.security.set_user_enabled(username, enabled)
        after = next(row for row in self.security.list_users() if row["username"] == username)
        self.audit.record("USER_ENABLE" if enabled else "USER_DISABLE", identity, "user", username, before=before, after=after)

    def reset_password(self, identity: UserIdentity, pin: str, username: str, new_password: str) -> None:
        self.security.require_sensitive(identity, "manage_users", pin)
        self.security.reset_password(username, new_password)
        self.audit.record("PASSWORD_RESET", identity, "user", username, after={"password": "changed"})

    def reset_pin(self, identity: UserIdentity, pin: str, username: str, new_pin: str) -> None:
        self.security.require_sensitive(identity, "manage_users", pin)
        self.security.reset_pin(username, new_pin)
        self.audit.record("PIN_RESET", identity, "user", username, after={"pin": "changed"})
