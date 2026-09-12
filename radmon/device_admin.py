from __future__ import annotations

from typing import Any

from .audit import AuditTrail
from .security import SecurityStore, UserIdentity


_ALLOWED_FIELDS = {
    "name",
    "location",
    "description",
    "warnlevel",
    "alarmlevel",
    "maxidlemin",
    "unit",
    "audiopath",
    "hwaddress",
    "hwtype",
}



LAN_EDITABLE_FIELDS = {
    "name", "location", "description", "warnlevel", "alarmlevel",
    "maxidlemin", "unit", "audiopath",
}

class DeviceAdminService:
    def __init__(
        self,
        security,
        repository,
        audit,
        *,
        station_source=None,
        remote_factory=None,
        write_through: bool = False,
    ) -> None:
        self._init_base(security, repository, audit)
        self.station_source = station_source
        self.remote_factory = remote_factory
        self.write_through = bool(write_through)
        self.source_definitions: dict[str, Any] = {}

    @staticmethod
    def _validate(changes: dict[str, Any]) -> None:
        unknown = set(changes) - _ALLOWED_FIELDS - {"serid"}
        if unknown:
            raise ValueError("field station tidak diizinkan: " + ", ".join(sorted(unknown)))
        warn = float(changes.get("warnlevel") or 0)
        alarm = float(changes.get("alarmlevel") or 0)
        if warn < 0 or alarm < 0 or (alarm > 0 and warn > alarm):
            raise ValueError("threshold tidak valid: Alert harus <= Alarm")
        if int(changes.get("maxidlemin") or 0) < 1:
            raise ValueError("max idle minimal 1 menit")

    def create_station(
        self,
        identity: UserIdentity,
        pin: str,
        serid: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        self.security.require_sensitive(identity, "edit_station", pin)
        if int(serid) <= 0:
            raise ValueError("Tag/SERID tidak valid")
        self._validate(values)
        target = f"station:{int(serid)}"
        try:
            after = self.repository.create_device(int(serid), values)
        except Exception as exc:
            self.audit.record(
                "DEVICE_CREATE", identity, "station", target,
                after=values, success=False, reason=str(exc)
            )
            raise
        self.audit.record("DEVICE_CREATE", identity, "station", target, after=after)
        return after

    def update_station(self, identity, pin: str, serid: int, changes: dict[str, Any]):
        if not self.write_through:
            return self._update_station_base(identity, pin, serid, changes)
        self.security.require_sensitive(identity, 'edit_station', pin)
        forbidden = set(changes) - LAN_EDITABLE_FIELDS
        if forbidden:
            raise ValueError('field identity/hardware LAN tidak dapat diedit: ' + ', '.join(sorted(forbidden)))
        before = self.repository.get_device(int(serid))
        if not before:
            raise ValueError('station tidak ditemukan')
        merged = dict(before)
        merged.update(changes)
        self._validate(merged)
        if self.station_source is None or self.remote_factory is None:
            raise RuntimeError('source station LAN belum dikonfigurasi')
        mapping = self.station_source(int(serid))
        if mapping is None:
            raise RuntimeError(f'source station untuk SERID {int(serid)} tidak ditemukan')
        source_id, remote_serid = mapping
        target = f'station:{int(serid)}'
        try:
            remote = self.remote_factory(source_id)
            confirmed = remote.update_device(int(remote_serid), dict(changes))
            central_changes = {key: confirmed.get(key, changes.get(key)) for key in LAN_EDITABLE_FIELDS if key in changes}
            actual_changes = {key: value for key, value in central_changes.items() if before.get(key) != value}
            after = self.repository.update_device(int(serid), actual_changes) if actual_changes else dict(before)
        except Exception as exc:
            self.audit.record('DEVICE_UPDATE', identity, 'station', target, before=before, after=changes, success=False, reason=str(exc), source=source_id)
            raise
        self.audit.record('DEVICE_UPDATE', identity, 'station', target, before=before, after=after, source=source_id)
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
            self.security.remap_central_serid(int(old_serid), int(new_serid))
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

    def _init_base(self, security: SecurityStore, repository: Any, audit: AuditTrail) -> None:
        self.security = security
        self.repository = repository
        self.audit = audit

    def _update_station_base(self, identity: UserIdentity, pin: str, serid: int, changes: dict[str, Any]) -> dict[str, Any]:
        self.security.require_sensitive(identity, 'edit_station', pin)
        before = self.repository.get_device(int(serid))
        if not before:
            raise ValueError('station tidak ditemukan')
        merged = dict(before)
        merged.update(changes)
        self._validate(merged)
        target = f'station:{serid}'
        try:
            after = self.repository.update_device(int(serid), changes)
        except Exception as exc:
            self.audit.record('DEVICE_UPDATE', identity, 'station', target, before=before, after=changes, success=False, reason=str(exc))
            raise
        self.audit.record('DEVICE_UPDATE', identity, 'station', target, before=before, after=after)
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
SELECT serid, name, location, description, warnlevel, alarmlevel, maxidlemin, unit,
       audiopath, hwaddress, hwtype
FROM device WHERE serid = ?
""",
                    (int(serid),),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            keys = (
                "serid", "name", "location", "description", "warnlevel", "alarmlevel",
                "maxidlemin", "unit", "audiopath", "hwaddress", "hwtype",
            )
            return dict(row) if isinstance(row, dict) else dict(zip(keys, row))
        finally:
            connection.close()

    def create_device(self, serid: int, values: dict[str, Any]) -> dict[str, Any]:
        fields = dict(values)
        unknown = set(fields) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError("field station tidak diizinkan: " + ", ".join(sorted(unknown)))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM device WHERE serid = ?", (int(serid),))
                if cursor.fetchone() is not None:
                    raise ValueError("Tag/SERID sudah digunakan")
                cursor.execute(
                    """
INSERT INTO device
  (serid, name, location, description, warnlevel, alarmlevel, maxidlemin, unit,
   audiopath, hwaddress, hwtype)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        int(serid),
                        fields.get("name") or f"Station {int(serid)}",
                        fields.get("location") or "",
                        fields.get("description") or "",
                        float(fields.get("warnlevel") or 0),
                        float(fields.get("alarmlevel") or 0),
                        int(fields.get("maxidlemin") or 30),
                        fields.get("unit") or "µSv/h",
                        fields.get("audiopath") or "",
                        fields.get("hwaddress") or "",
                        fields.get("hwtype") or "detector",
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        current = self.get_device(serid)
        if current is None:
            raise RuntimeError("station tidak ditemukan setelah create")
        return current

    def update_device(self, serid: int, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes:
            current = self.get_device(serid)
            if current is None:
                raise ValueError("station tidak ditemukan")
            return current
        fields = list(changes)
        unknown = set(fields) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError("field station tidak diizinkan: " + ", ".join(sorted(unknown)))
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
                for table in ("measurement", "recent", "alarm", "rawdata"):
                    cursor.execute(
                        f"UPDATE {table} SET serid = ? WHERE serid = ?",
                        (int(new_serid), int(old_serid)),
                    )
                cursor.execute(
                    "UPDATE device SET serid = ? WHERE serid = ?",
                    (int(new_serid), int(old_serid)),
                )
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
