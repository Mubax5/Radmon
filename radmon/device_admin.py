from __future__ import annotations

from typing import Any

from .audit import AuditTrail
from .security import SecurityStore, UserIdentity


_ALLOWED_FIELDS = {
    "name", "location", "description", "warnlevel", "alarmlevel", "maxidlemin", "unit"
}


class DeviceAdminService:
    def __init__(self, security: SecurityStore, repository: Any, audit: AuditTrail) -> None:
        self.security = security
        self.repository = repository
        self.audit = audit

    def update_station(
        self,
        identity: UserIdentity,
        pin: str,
        serid: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        self.security.require_sensitive(identity, "edit_station", pin)
        unknown = set(changes) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError("field station tidak diizinkan: " + ", ".join(sorted(unknown)))
        before = self.repository.get_device(int(serid))
        if not before:
            raise ValueError("station tidak ditemukan")
        merged = dict(before)
        merged.update(changes)
        warn = float(merged.get("warnlevel") or 0)
        alarm = float(merged.get("alarmlevel") or 0)
        if warn < 0 or alarm < 0 or (alarm > 0 and warn > alarm):
            raise ValueError("threshold tidak valid: Alert harus <= Alarm")
        if int(merged.get("maxidlemin") or 0) < 1:
            raise ValueError("max idle minimal 1 menit")
        target = f"station:{serid}"
        try:
            after = self.repository.update_device(int(serid), changes)
        except Exception as exc:
            self.audit.record(
                "DEVICE_UPDATE", identity, "station", target,
                before=before, after=changes, success=False, reason=str(exc)
            )
            raise
        self.audit.record(
            "DEVICE_UPDATE", identity, "station", target,
            before=before, after=after
        )
        return after

    def migrate_serid(
        self,
        identity: UserIdentity,
        pin: str,
        old_serid: int,
        new_serid: int,
    ) -> dict[str, Any]:
        self.security.require_sensitive(identity, "edit_station", pin)
        if int(new_serid) <= 0 or int(old_serid) == int(new_serid):
            raise ValueError("Tag/SERID baru tidak valid")
        before = self.repository.get_device(int(old_serid))
        if not before:
            raise ValueError("station lama tidak ditemukan")
        target = f"station:{old_serid}->{new_serid}"
        try:
            after = self.repository.migrate_serid(int(old_serid), int(new_serid))
        except Exception as exc:
            self.audit.record(
                "DEVICE_SERID_MIGRATE", identity, "station", target,
                before=before, success=False, reason=str(exc)
            )
            raise
        self.audit.record(
            "DEVICE_SERID_MIGRATE", identity, "station", target,
            before=before, after=after
        )
        return after


class MariaDeviceAdminRepository:
    def __init__(self, settings, *, connection_factory=None) -> None:
        self.settings = settings
        self.connection_factory = connection_factory

    def _connect(self):
        if self.connection_factory is not None:
            return self.connection_factory()
        from .db import connect_mariadb
        return connect_mariadb(self.settings)

    def get_device(self, serid: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, name, location, description, warnlevel, alarmlevel, maxidlemin, unit
FROM device WHERE serid = ?
""",
                    (int(serid),),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            keys = ("serid", "name", "location", "description", "warnlevel", "alarmlevel", "maxidlemin", "unit")
            return dict(row) if isinstance(row, dict) else dict(zip(keys, row))
        finally:
            connection.close()

    def update_device(self, serid: int, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes:
            current = self.get_device(serid)
            if current is None:
                raise ValueError("station tidak ditemukan")
            return current
        fields = list(changes)
        sql = "UPDATE device SET " + ", ".join(f"{field} = ?" for field in fields) + " WHERE serid = ?"
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(changes[field] for field in fields) + (int(serid),))
                if int(getattr(cursor, "rowcount", 0)) < 1:
                    raise ValueError("station tidak ditemukan atau tidak berubah")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        current = self.get_device(serid)
        if current is None:
            raise RuntimeError("station hilang setelah update")
        return current

    def migrate_serid(self, old_serid: int, new_serid: int) -> dict[str, Any]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM device WHERE serid = ?", (int(new_serid),))
                if cursor.fetchone() is not None:
                    raise ValueError("Tag/SERID baru sudah digunakan")
                cursor.execute("SELECT 1 FROM device WHERE serid = ?", (int(old_serid),))
                if cursor.fetchone() is None:
                    raise ValueError("station lama tidak ditemukan")

                # Existing deployments may or may not declare foreign keys. Migrate
                # child rows first and device last inside one transaction.
                for table in ("measurement", "recent", "alarm", "rawdata"):
                    cursor.execute(f"UPDATE {table} SET serid = ? WHERE serid = ?", (int(new_serid), int(old_serid)))
                cursor.execute("UPDATE device SET serid = ? WHERE serid = ?", (int(new_serid), int(old_serid)))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        current = self.get_device(new_serid)
        if current is None:
            raise RuntimeError("station tidak ditemukan setelah migrasi Tag")
        return current
