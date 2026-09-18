from __future__ import annotations

import math
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



class DeviceAdminService:
    def __init__(
        self,
        security,
        repository,
        audit,
        *,
        station_source=None,
    ) -> None:
        self._init_base(security, repository, audit)
        self.station_source = station_source

    @staticmethod
    def _validate(changes: dict[str, Any]) -> None:
        if not changes:
            raise ValueError("tidak ada perubahan station")
        unknown = set(changes) - _ALLOWED_FIELDS - {"serid"}
        if unknown:
            raise ValueError("field station tidak diizinkan: " + ", ".join(sorted(unknown)))
        for field, limit in (("name", 128), ("location", 256), ("description", 2000), ("unit", 32), ("audiopath", 512), ("hwaddress", 256), ("hwtype", 64)):
            if field not in changes:
                continue
            value = changes[field]
            if not isinstance(value, str) or len(value.strip()) > limit:
                raise ValueError(f"{field} tidak valid")
            if field in {"name", "location", "unit", "hwtype"} and not value.strip():
                raise ValueError(f"{field} tidak boleh kosong")
        try:
            if any(isinstance(changes.get(field), bool) for field in ("warnlevel", "alarmlevel", "maxidlemin") if field in changes):
                raise ValueError
            warn = float(changes.get("warnlevel") or 0)
            alarm = float(changes.get("alarmlevel") or 0)
            max_idle = float(changes.get("maxidlemin") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("threshold atau max idle tidak valid") from exc
        if not all(math.isfinite(value) for value in (warn, alarm, max_idle)):
            raise ValueError("threshold atau max idle tidak valid")
        if warn < 0 or alarm < 0 or (alarm > 0 and warn > alarm):
            raise ValueError("threshold tidak valid: Alert harus <= Alarm")
        if max_idle < 1 or not max_idle.is_integer():
            raise ValueError("max idle minimal 1 menit")

    def _source_mapping(self, serid: int) -> tuple[str, int] | None:
        if self.station_source is None:
            return None
        return self.station_source(int(serid))

    def _require_centrally_managed(self, serid: int) -> None:
        if self._source_mapping(serid) is not None:
            raise ValueError("stasiun milik sumber LAN tidak dapat dikelola sebagai stasiun pusat")

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
        self._require_centrally_managed(int(serid))
        candidate = {
            "name": values.get("name"),
            "location": values.get("location"),
            "description": "",
            "warnlevel": 0,
            "alarmlevel": 0,
            "maxidlemin": 30,
            "unit": "µSv/h",
            "hwtype": "detector",
            **values,
        }
        self._validate(candidate)
        target = f"station:{int(serid)}"
        try:
            after = self.repository.create_device(int(serid), candidate)
        except Exception as exc:
            self.audit.record(
                "DEVICE_CREATE", identity, "station", target,
                after=values, success=False, reason=str(exc)
            )
            raise
        self.audit.record("DEVICE_CREATE", identity, "station", target, after=after)
        return after

    def delete_station(self, identity: UserIdentity, pin: str, serid: int) -> None:
        self.security.require_sensitive(identity, "edit_station", pin)
        self._require_centrally_managed(int(serid))
        before = self.repository.get_device(int(serid))
        if not before:
            raise ValueError("station tidak ditemukan")
        try:
            self.repository.delete_device(int(serid))
        except Exception as exc:
            self.audit.record("DEVICE_DELETE", identity, "station", f"station:{int(serid)}", before=before, success=False, reason=str(exc))
            raise
        self.audit.record("DEVICE_DELETE", identity, "station", f"station:{int(serid)}", before=before)

    def update_station(self, identity, pin: str, serid: int, changes: dict[str, Any]):
        self.security.require_sensitive(identity, 'edit_station', pin)
        # LAN sources remain authoritative. Central station edits must never
        # write through to, or locally override, a source-owned device record.
        self._require_centrally_managed(int(serid))
        return self._update_station_base(identity, pin, serid, changes, authorized=True)

    def migrate_serid(
        self,
        identity: UserIdentity,
        pin: str,
        old_serid: int,
        new_serid: int,
    ) -> dict[str, Any]:
        self.security.require_sensitive(identity, "edit_station", pin)
        self._require_centrally_managed(int(old_serid))
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

    def _update_station_base(self, identity: UserIdentity, pin: str, serid: int, changes: dict[str, Any], *, authorized: bool = False) -> dict[str, Any]:
        if not authorized:
            self.security.require_sensitive(identity, 'edit_station', pin)
        if not changes:
            raise ValueError('tidak ada perubahan station')
        unknown = set(changes) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError('field station tidak diizinkan: ' + ', '.join(sorted(unknown)))
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

    def delete_device(self, serid: int) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                for table in ("measurement", "recent", "alarm", "rawdata"):
                    cursor.execute(f"SELECT 1 FROM {table} WHERE serid = ? LIMIT 1", (int(serid),))
                    if cursor.fetchone() is not None:
                        raise ValueError("stasiun yang memiliki measurement atau riwayat tidak dapat dihapus")
                cursor.execute("DELETE FROM device WHERE serid = ?", (int(serid),))
                if int(getattr(cursor, "rowcount", 0)) != 1:
                    raise ValueError("station tidak ditemukan")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
