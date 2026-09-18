from __future__ import annotations

import threading

from .audit import AuditTrail
from .security import Role, SecurityError, SecurityStore, UserIdentity


_USER_MUTATION_LOCK = threading.RLock()


class UserAdminService:
    def __init__(self, security: SecurityStore, audit: AuditTrail) -> None:
        self.security = security
        self.audit = audit

    @staticmethod
    def _failure_reason(exc: Exception) -> str:
        # Do not persist arbitrary exception text because a lower layer may have
        # included a supplied credential in it.
        if isinstance(exc, (SecurityError, ValueError)):
            return str(exc)
        return "perubahan pengguna tidak dapat disimpan"

    def _record_failure(self, action: str, identity: UserIdentity, target: str, exc: Exception) -> None:
        self.audit.record(
            action, identity, "user", target, success=False,
            reason=self._failure_reason(exc),
        )

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
        selected_role = role if isinstance(role, Role) else Role(role)
        safe_after = {"display_name": display_name, "role": selected_role.value, "enabled": True}
        try:
            self.security.require_sensitive(identity, "manage_users", pin)
            created = self.security.create_user(
                username, display_name, selected_role, password, user_pin, actor=identity.username
            )
        except Exception as exc:
            self._record_failure("USER_CREATE", identity, username, exc)
            raise
        self.audit.record("USER_CREATE", identity, "user", created.username, after=safe_after)
        return created

    def set_enabled(self, identity: UserIdentity, pin: str, username: str, enabled: bool) -> None:
        with _USER_MUTATION_LOCK:
            target = str(username).strip().lower()
            try:
                self.security.require_sensitive(identity, "manage_users", pin)
                before = next((row for row in self.security.list_users() if row["username"] == target), None)
                if before is None:
                    raise ValueError("user tidak ditemukan")
                if identity.username == target and not enabled:
                    raise ValueError("Administrator tidak dapat menonaktifkan akun yang sedang dipakai")
                self._ensure_not_final_admin(before, role=Role(str(before["role"])), enabled=enabled)
                self.security.set_user_enabled(username, enabled)
                after = self.security.get_user(target)
            except Exception as exc:
                self._record_failure("USER_ENABLE" if enabled else "USER_DISABLE", identity, target, exc)
                raise
            self.audit.record("USER_ENABLE" if enabled else "USER_DISABLE", identity, "user", target, before=before, after=after)

    def reset_password(self, identity: UserIdentity, pin: str, username: str, new_password: str) -> None:
        target = str(username).strip().lower()
        try:
            self.security.require_sensitive(identity, "manage_users", pin)
            self.security.get_user(target)
            self.security.reset_password(target, new_password)
        except Exception as exc:
            self._record_failure("PASSWORD_RESET", identity, target, exc)
            raise
        self.audit.record("PASSWORD_RESET", identity, "user", target, after={"credential": "password reset"})

    def reset_pin(self, identity: UserIdentity, pin: str, username: str, new_pin: str) -> None:
        target = str(username).strip().lower()
        try:
            self.security.require_sensitive(identity, "manage_users", pin)
            self.security.get_user(target)
            self.security.reset_pin(target, new_pin)
        except Exception as exc:
            self._record_failure("PIN_RESET", identity, target, exc)
            raise
        self.audit.record("PIN_RESET", identity, "user", target, after={"credential": "PIN reset"})

    def update_user(
        self,
        identity: UserIdentity,
        pin: str,
        username: str,
        *,
        display_name: str | None = None,
        role: Role | str | None = None,
    ) -> dict[str, object]:
        with _USER_MUTATION_LOCK:
            target = str(username).strip().lower()
            try:
                self.security.require_sensitive(identity, "manage_users", pin)
                before = self.security.get_user(target)
                selected_role = Role(role) if role is not None and not isinstance(role, Role) else role
                if identity.username == target and selected_role is not None and selected_role is not Role.ADMINISTRATOR:
                    raise ValueError("Administrator tidak dapat menurunkan role akun yang sedang dipakai")
                self._ensure_not_final_admin(before, role=selected_role or Role(str(before["role"])), enabled=bool(before["enabled"]))
                after = self.security.update_user(username, display_name=display_name, role=selected_role)
            except Exception as exc:
                self._record_failure("USER_UPDATE", identity, target, exc)
                raise
            self.audit.record("USER_UPDATE", identity, "user", target, before=before, after=after)
            return after

    def delete_user(self, identity: UserIdentity, pin: str, username: str) -> dict[str, object]:
        with _USER_MUTATION_LOCK:
            target = str(username).strip().lower()
            try:
                self.security.require_sensitive(identity, "manage_users", pin)
                before = self.security.get_user(target)
                if identity.username == target:
                    raise ValueError("Administrator tidak dapat menghapus akun yang sedang dipakai")
                self._ensure_not_final_admin(before, role=Role(str(before["role"])), enabled=False)
                after = self.security.delete_user(target)
            except Exception as exc:
                self._record_failure("USER_DEACTIVATE", identity, target, exc)
                raise
            self.audit.record("USER_DEACTIVATE", identity, "user", target, before=before, after=after)
            return after

    def _ensure_not_final_admin(self, before: dict[str, object], *, role: Role, enabled: bool) -> None:
        was_enabled_admin = bool(before["enabled"]) and before["role"] == Role.ADMINISTRATOR.value
        remains_enabled_admin = bool(enabled) and role is Role.ADMINISTRATOR
        if was_enabled_admin and not remains_enabled_admin:
            enabled_admins = sum(
                1 for user in self.security.list_users()
                if user["enabled"] and user["role"] == Role.ADMINISTRATOR.value
            )
            if enabled_admins <= 1:
                raise ValueError("administrator aktif terakhir tidak dapat diubah")
