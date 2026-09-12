"""Production integration fixes for PC3 LAN deployment.

This module is applied after the existing compatibility revisions. It keeps the
legacy-compatible modules small while making source writes, alarm handling,
PIN elevation, live chart samples, and desktop integration consistent with the
production ``ipradmon`` contract.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import threading
import time
from typing import Any


def apply() -> None:
    _patch_admin_ui()
    _patch_grafana()


def _patch_security() -> None:
    from . import security as module

    original_init = module.SecurityStore.__init__
    original_set_user_enabled = module.SecurityStore.set_user_enabled
    original_reset_pin = module.SecurityStore.reset_pin
    original_revoke_session = module.SecurityStore.revoke_session

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._sensitive_leases: dict[str, datetime] = {}
        self._sensitive_lease_lock = threading.Lock()

    def sensitive_lease_active(self, identity) -> bool:
        if identity is None:
            return False
        username = str(identity.username).strip().lower()
        with self._sensitive_lease_lock:
            expires = self._sensitive_leases.get(username)
            if expires is None:
                return False
            if expires <= self._now():
                self._sensitive_leases.pop(username, None)
                return False
            return True

    def clear_sensitive_lease(self, username: str | None = None) -> None:
        with self._sensitive_lease_lock:
            if username is None:
                self._sensitive_leases.clear()
            else:
                self._sensitive_leases.pop(str(username).strip().lower(), None)

    def require_sensitive(self, identity, permission: str, pin: str) -> None:
        if identity is None or not self.role_allows(identity.role, permission):
            raise module.SecurityError("aksi tidak diizinkan")
        if sensitive_lease_active(self, identity):
            return
        supplied = str(pin or "")
        if not supplied or not self.verify_pin(identity.username, supplied):
            raise module.SecurityError("PIN tidak valid")
        with self._sensitive_lease_lock:
            self._sensitive_leases[str(identity.username).strip().lower()] = (
                self._now() + timedelta(seconds=600)
            )

    def set_user_enabled(self, username: str, enabled: bool) -> None:
        original_set_user_enabled(self, username, enabled)
        if not enabled:
            clear_sensitive_lease(self, username)

    def reset_pin(self, username: str, pin: str) -> None:
        original_reset_pin(self, username, pin)
        clear_sensitive_lease(self, username)

    def revoke_session(self, token: str | None) -> None:
        identity = self.session_user(token) if token else None
        original_revoke_session(self, token)
        if identity is not None:
            clear_sensitive_lease(self, identity.username)

    def station_source(self, central_serid: int) -> tuple[str, int] | None:
        with self._connection() as connection:
            rows = connection.execute(
                """
SELECT source_id, remote_serid
FROM source_station_map
WHERE central_serid = ?
ORDER BY source_id, remote_serid
""",
                (int(central_serid),),
            ).fetchall()
        if not rows:
            return None
        unique = {(str(row[0]), int(row[1])) for row in rows}
        if len(unique) != 1:
            raise RuntimeError(
                f"ambiguous source mapping for central SERID {int(central_serid)}"
            )
        return next(iter(unique))

    def station_source_map(self) -> dict[int, str]:
        with self._connection() as connection:
            rows = connection.execute(
                """
SELECT source_id, remote_serid, central_serid
FROM source_station_map
ORDER BY source_id, remote_serid
"""
            ).fetchall()
        candidates: dict[int, set[str]] = {}
        for source_id, _remote_serid, central_serid in rows:
            candidates.setdefault(int(central_serid), set()).add(str(source_id))
        return {
            serid: next(iter(source_ids))
            for serid, source_ids in candidates.items()
            if len(source_ids) == 1
        }

    module.SecurityStore.__init__ = init
    module.SecurityStore.sensitive_lease_active = sensitive_lease_active
    module.SecurityStore.clear_sensitive_lease = clear_sensitive_lease
    module.SecurityStore.require_sensitive = require_sensitive
    module.SecurityStore.set_user_enabled = set_user_enabled
    module.SecurityStore.reset_pin = reset_pin
    module.SecurityStore.revoke_session = revoke_session
    module.SecurityStore.station_source = station_source
    module.SecurityStore.station_source_map = station_source_map


def _patch_remote_source() -> None:
    from . import lan as module

    editable = {
        "name", "location", "description", "warnlevel", "alarmlevel",
        "maxidlemin", "unit", "audiopath",
    }

    def get_device(self, serid: int) -> dict[str, Any] | None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, name, location, description, warnlevel, alarmlevel,
       maxidlemin, unit, audiopath, hwaddress, hwtype
FROM device WHERE serid = ?
""",
                    (int(serid),),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            keys = (
                "serid", "name", "location", "description", "warnlevel",
                "alarmlevel", "maxidlemin", "unit", "audiopath",
                "hwaddress", "hwtype",
            )
            return dict(row) if isinstance(row, dict) else dict(zip(keys, row))
        finally:
            connection.close()

    def update_device(self, serid: int, changes: dict[str, Any]) -> dict[str, Any]:
        fields = list(changes)
        unknown = set(fields) - editable
        if unknown:
            raise ValueError(
                "field station LAN tidak diizinkan: " + ", ".join(sorted(unknown))
            )
        if not fields:
            current = get_device(self, serid)
            if current is None:
                raise ValueError("station source tidak ditemukan")
            return current
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                sql = "UPDATE device SET " + ", ".join(
                    f"{field} = ?" for field in fields
                ) + " WHERE serid = ?"
                cursor.execute(
                    sql,
                    tuple(changes[field] for field in fields) + (int(serid),),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        current = get_device(self, serid)
        if current is None:
            raise RuntimeError("station source hilang setelah update")
        return current

    def respond_alarm(
        self,
        serid: int,
        dtoa: datetime,
        *,
        action: str,
        pic: str,
        note: str,
        at: datetime,
    ) -> bool:
        source_note = f"[{action.strip()}] {note.strip()}".strip()[:255]
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
UPDATE alarm
SET i_op = ?, pic = ?, note = ?, i_flag = 1
WHERE serid = ? AND dtoa = ? AND i_flag = 0
""",
                    (at, pic.strip(), source_note, int(serid), dtoa),
                )
                changed = int(getattr(cursor, "rowcount", 0))
            connection.commit()
            return changed == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def alarm_states(self, limit: int = 2000) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT serid, dtoa, lvl, mvalue, thvalue, nhit, ack, i_flag, i_op, pic, note
FROM alarm
WHERE i_flag = 0 OR dtoa >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY dtoa DESC, serid DESC
LIMIT ?
""",
                    (max(1, int(limit)),),
                )
                rows = cursor.fetchall()
            keys = (
                "serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit",
                "ack", "i_flag", "i_op", "pic", "note",
            )
            return self._dict_rows(rows, keys)
        finally:
            connection.close()

    module.RemoteMariaDBSource.get_device = get_device
    module.RemoteMariaDBSource.update_device = update_device
    module.RemoteMariaDBSource.respond_alarm = respond_alarm
    module.RemoteMariaDBSource.alarm_states = alarm_states


def _patch_device_admin() -> None:
    from . import device_admin as module

    original_init = module.DeviceAdminService.__init__
    original_update = module.DeviceAdminService.update_station
    lan_fields = {
        "name", "location", "description", "warnlevel", "alarmlevel",
        "maxidlemin", "unit", "audiopath",
    }

    def init(
        self,
        security,
        repository,
        audit,
        *,
        station_source=None,
        remote_factory=None,
        write_through: bool = False,
    ) -> None:
        original_init(self, security, repository, audit)
        self.station_source = station_source
        self.remote_factory = remote_factory
        self.write_through = bool(write_through)
        self.source_definitions: dict[str, Any] = {}

    def update_station(self, identity, pin: str, serid: int, changes: dict[str, Any]):
        if not self.write_through:
            return original_update(self, identity, pin, serid, changes)

        self.security.require_sensitive(identity, "edit_station", pin)
        forbidden = set(changes) - lan_fields
        if forbidden:
            raise ValueError(
                "field identity/hardware LAN tidak dapat diedit: "
                + ", ".join(sorted(forbidden))
            )
        before = self.repository.get_device(int(serid))
        if not before:
            raise ValueError("station tidak ditemukan")
        merged = dict(before)
        merged.update(changes)
        self._validate(merged)
        if self.station_source is None or self.remote_factory is None:
            raise RuntimeError("source station LAN belum dikonfigurasi")
        mapping = self.station_source(int(serid))
        if mapping is None:
            raise RuntimeError(f"source station untuk SERID {int(serid)} tidak ditemukan")
        source_id, remote_serid = mapping
        target = f"station:{int(serid)}"
        try:
            remote = self.remote_factory(source_id)
            confirmed = remote.update_device(int(remote_serid), dict(changes))
            central_changes = {
                key: confirmed.get(key, changes.get(key))
                for key in lan_fields
                if key in changes
            }
            actual_changes = {
                key: value
                for key, value in central_changes.items()
                if before.get(key) != value
            }
            after = (
                self.repository.update_device(int(serid), actual_changes)
                if actual_changes else dict(before)
            )
        except Exception as exc:
            self.audit.record(
                "DEVICE_UPDATE", identity, "station", target,
                before=before, after=changes, success=False,
                reason=str(exc), source=source_id,
            )
            raise
        self.audit.record(
            "DEVICE_UPDATE", identity, "station", target,
            before=before, after=after, source=source_id,
        )
        return after

    module.DeviceAdminService.__init__ = init
    module.DeviceAdminService.update_station = update_station


def _patch_secure_services() -> None:
    from . import secure_services as module
    from .lan import RemoteMariaDBSource

    original_build = module.build_secure_services

    def build_secure_services(*args, **kwargs):
        services = original_build(*args, **kwargs)
        device_admin = services.device_admin
        device_admin.source_definitions = dict(services.sources)
        if services.sources:
            device_admin.write_through = True
            device_admin.station_source = services.security.station_source

            def remote_factory(source_id: str):
                source = services.sources.get(str(source_id))
                if source is None:
                    raise KeyError(f"LAN source tidak ditemukan: {source_id}")
                return RemoteMariaDBSource(source)

            device_admin.remote_factory = remote_factory
        return services

    module.build_secure_services = build_secure_services


def _patch_alarm_mirror_and_control() -> None:
    from . import remote_alarm as module

    schema_lock = threading.Lock()

    def ensure_active_schema(self) -> None:
        if getattr(self, "_active_schema_ready", False):
            return
        with schema_lock:
            if getattr(self, "_active_schema_ready", False):
                return
            with self.store._connection() as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(remote_alarm_state)"
                    ).fetchall()
                }
                if "is_active" not in columns:
                    connection.execute(
                        "ALTER TABLE remote_alarm_state "
                        "ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                    )
                connection.execute(
                    "UPDATE remote_alarm_state SET is_active = 0 "
                    "WHERE acknowledged_at IS NOT NULL"
                )
            self._active_schema_ready = True

    def mirror(self, source_id: str, rows: list[dict[str, Any]]) -> int:
        ensure_active_schema(self)
        changed = 0
        with self.store._connection() as connection:
            for row in rows:
                event_time = self._event_time(row)
                event_iso = event_time.isoformat()
                serid = int(row["serid"])
                remote_serid = int(row.get("_remote_serid", serid))
                acknowledged_at = row.get("i_op")
                ack_iso = (
                    acknowledged_at.isoformat()
                    if isinstance(acknowledged_at, datetime) else None
                )
                if "i_flag" in row:
                    is_active = 0 if int(row.get("i_flag") or 0) else 1
                else:
                    is_active = 0 if ack_iso or bool(row.get("ack")) else 1
                historical = bool(row.get("_historical_seed"))
                already_notified = (
                    historical
                    or not bool(is_active)
                    or bool(row.get("ack"))
                    or ack_iso is not None
                )
                notification_sent_at = ack_iso or (
                    event_iso if already_notified else None
                )
                before_changes = connection.total_changes
                connection.execute(
                    """
INSERT INTO remote_alarm_state
  (source_id, serid, remote_serid, event_time, level, measured_value,
   threshold, hit_count, acknowledged_at, pic, action, note,
   notification_sent_at, is_active)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(source_id, serid, event_time) DO UPDATE SET
  remote_serid = excluded.remote_serid,
  level = excluded.level,
  measured_value = COALESCE(excluded.measured_value, measured_value),
  threshold = COALESCE(excluded.threshold, threshold),
  hit_count = COALESCE(excluded.hit_count, hit_count),
  is_active = excluded.is_active,
  acknowledged_at = CASE
    WHEN excluded.is_active = 1 THEN NULL
    ELSE COALESCE(excluded.acknowledged_at, acknowledged_at)
  END,
  pic = COALESCE(excluded.pic, pic),
  note = COALESCE(excluded.note, note),
  notification_sent_at = COALESCE(notification_sent_at, excluded.notification_sent_at)
""",
                    (
                        source_id, serid, remote_serid, event_iso,
                        self._level(row), row.get("mvalue"), row.get("thvalue"),
                        row.get("nhit"), ack_iso, row.get("pic"), None,
                        row.get("note"), notification_sent_at, is_active,
                    ),
                )
                if connection.total_changes > before_changes:
                    changed += 1
        return changed

    @staticmethod
    def row_to_dict(row):
        keys = (
            "source_id", "serid", "remote_serid", "event_time", "level",
            "measured_value", "threshold", "hit_count", "acknowledged_at",
            "pic", "action", "note", "notification_sent_at", "is_active",
        )
        item = dict(zip(keys, row))
        for key in ("event_time", "acknowledged_at", "notification_sent_at"):
            if item[key]:
                item[key] = datetime.fromisoformat(str(item[key]))
        item["is_active"] = bool(item.get("is_active"))
        return item

    def list_alarms(self, *, active_only: bool = False, limit: int = 500):
        ensure_active_schema(self)
        clause = "WHERE is_active = 1" if active_only else ""
        with self.store._connection() as connection:
            rows = connection.execute(
                f"""
SELECT source_id, serid, remote_serid, event_time, level, measured_value,
       threshold, hit_count, acknowledged_at, pic, action, note,
       notification_sent_at, is_active
FROM remote_alarm_state {clause}
ORDER BY event_time DESC LIMIT ?
""",
                (max(1, int(limit)),),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get(self, source_id: str, serid: int, event_time: datetime):
        ensure_active_schema(self)
        with self.store._connection() as connection:
            row = connection.execute(
                """
SELECT source_id, serid, remote_serid, event_time, level, measured_value,
       threshold, hit_count, acknowledged_at, pic, action, note,
       notification_sent_at, is_active
FROM remote_alarm_state
WHERE source_id = ? AND serid = ? AND event_time = ?
""",
                (source_id, int(serid), event_time.isoformat()),
            ).fetchone()
        return row_to_dict(row) if row else None

    def mark_acknowledged(
        self,
        source_id: str,
        serid: int,
        event_time: datetime,
        *,
        acknowledged_at: datetime,
        pic: str,
        action: str,
        note: str,
    ):
        ensure_active_schema(self)
        with self.store._connection() as connection:
            cursor = connection.execute(
                """
UPDATE remote_alarm_state
SET acknowledged_at = ?, pic = ?, action = ?, note = ?, is_active = 0
WHERE source_id = ? AND serid = ? AND event_time = ? AND is_active = 1
""",
                (
                    acknowledged_at.isoformat(), pic, action, note,
                    source_id, int(serid), event_time.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("alarm sudah ditangani atau tidak ditemukan")
        item = get(self, source_id, serid, event_time)
        if item is None:
            raise RuntimeError("alarm tidak ditemukan setelah response")
        return item

    def ack(
        self,
        identity,
        pin: str,
        source_id: str,
        serid: int,
        event_time: datetime,
        *,
        action: str,
        pic: str,
        note: str,
    ):
        self.security.require_sensitive(identity, "ack_alarm", pin)
        if not action.strip() or not pic.strip():
            raise ValueError("Action dan PIC wajib diisi")
        before = self.mirror.get(source_id, serid, event_time)
        if before is None:
            raise RuntimeError("alarm tidak ditemukan")
        if before.get("is_active") is False:
            raise RuntimeError("alarm sudah ditangani")
        remote_serid = int(before.get("remote_serid") or serid)
        at = self.now()
        target_id = f"{source_id}:{serid}:{event_time.isoformat()}"
        try:
            remote = self.remote_factory(source_id)
            ok = bool(
                remote.respond_alarm(
                    remote_serid,
                    event_time,
                    action=action.strip(),
                    pic=pic.strip(),
                    note=note.strip(),
                    at=at,
                )
            )
            if not ok:
                raise RuntimeError("source menolak response; alarm mungkin sudah ditangani")
            after = self.mirror.mark_acknowledged(
                source_id,
                serid,
                event_time,
                acknowledged_at=at,
                pic=pic.strip(),
                action=action.strip(),
                note=note.strip(),
            )
        except Exception as exc:
            self.audit.record(
                "ALARM_ACK", identity, "alarm", target_id,
                before=before, success=False, reason=str(exc), source=source_id,
            )
            raise
        self.audit.record(
            "ALARM_ACK", identity, "alarm", target_id,
            before=before, after=after, source=source_id,
        )
        return after

    module.RemoteAlarmMirror._ensure_active_schema = ensure_active_schema
    module.RemoteAlarmMirror.mirror = mirror
    module.RemoteAlarmMirror._row = row_to_dict
    module.RemoteAlarmMirror.list_alarms = list_alarms
    module.RemoteAlarmMirror.get = get
    module.RemoteAlarmMirror.mark_acknowledged = mark_acknowledged
    module.AlarmControlService.ack = ack


def _patch_live_collector() -> None:
    from . import lan as module

    original_upsert_live = module.MariaCentralStore.upsert_live_rows
    original_run_live = module.LanAggregator.run_live_once

    def upsert_live_rows(self, source_id: str, rows) -> int:
        values = list(rows)
        changed = original_upsert_live(self, source_id, values)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                for row in values:
                    measured_at = row.get("dtom")
                    rate = row.get("doserate")
                    if not isinstance(measured_at, datetime) or rate is None:
                        continue
                    try:
                        interval = int(row.get("lastmeasec") or 2)
                    except (TypeError, ValueError):
                        interval = 2
                    if interval < 1 or interval > 3600:
                        interval = 2
                    cursor.execute(
                        """
INSERT IGNORE INTO measurement
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, 0)
""",
                        (
                            int(row["serid"]), measured_at, float(rate),
                            float(row.get("dose") or 0.0), interval,
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return changed

    def run_live_once(self, source):
        historical_seed = self.checkpoints.load_alarm(source.source_id) is None
        result = original_run_live(self, source)
        if result.error:
            return result
        try:
            remote = self.remote_factory(source)
            state_rows = remote.alarm_states(2000)
            mapped: list[dict[str, Any]] = []
            for row in state_rows:
                item = dict(row)
                remote_serid = int(item["serid"])
                item["_remote_serid"] = remote_serid
                item["serid"] = self.checkpoints.store.resolve_station(
                    source.source_id, remote_serid
                )
                if historical_seed:
                    item["_historical_seed"] = True
                mapped.append(item)
            if mapped and self.alarm_mirror is not None:
                self.alarm_mirror.mirror(source.source_id, mapped)
            if mapped and hasattr(self.central, "mirror_alarm_events"):
                self.central.mirror_alarm_events(source.source_id, mapped)
        except Exception as exc:
            result.error = str(exc)
        return result

    module.MariaCentralStore.upsert_live_rows = upsert_live_rows
    module.LanAggregator.run_live_once = run_live_once


def _patch_admin_ui() -> None:
    try:
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtWidgets import QApplication, QMessageBox, QTreeWidgetItem
        from .admin import auth_dialogs, main_window, station_admin_dialog
        from .admin import alarm_page, alarm_response_dialog
        from .secure_context import get_context
    except Exception:
        return

    original_pin = auth_dialogs.PinDialog.get_pin

    @staticmethod
    def get_pin(parent, *, title: str = "PIN", message: str = "Masukkan PIN untuk melanjutkan"):
        context = get_context()
        security = getattr(getattr(context, "device_admin", None), "security", None)
        identity = getattr(context, "identity", None)
        if security is not None and identity is not None:
            try:
                if security.sensitive_lease_active(identity):
                    return "", True
            except Exception:
                pass
        return original_pin(parent, title=title, message=message)

    auth_dialogs.PinDialog.get_pin = get_pin


    def group_stations_by_source(stations, station_source_by_serid, sources, health_by_source):
        groups = []
        for source_id, source in sources.items():
            members = [
                station for station in stations
                if station_source_by_serid.get(int(station.serid)) == source_id
            ]
            groups.append(
                {
                    "source_id": source_id,
                    "host": str(getattr(source, "host", "")),
                    "state": str(health_by_source.get(source_id, "UNKNOWN")),
                    "stations": members,
                }
            )
        return groups

    main_window.group_stations_by_source = group_stations_by_source
    main_window.INSTALLATION_MANUAL_PATH = "docs/manual/installation.html"
    main_window.USER_MANUAL_PATH = "docs/manual/user-manual.html"

    original_reload = main_window.MainWindow.reload_station_sidebar
    original_select_recent = main_window.MainWindow._select_station_from_recent
    original_build_actions = main_window.MainWindow._build_actions
    original_refresh_current = main_window.MainWindow.refresh_current_page

    def source_label(source_id: str) -> str:
        text = str(source_id)
        lower = text.lower()
        if lower.startswith("gd") and lower[2:].isdigit():
            return f"Gd.{lower[2:]}"
        return text

    def health_map():
        context = get_context()
        if context is None:
            return {}
        try:
            return {
                str(row["source_id"]): str(row.get("state") or "UNKNOWN")
                for row in context.source_health.list_states()
            }
        except Exception:
            return {}

    def reload_station_sidebar(self, *, select_serid: int | None = None) -> None:
        context = get_context()
        source_definitions = dict(
            getattr(getattr(context, "device_admin", None), "source_definitions", {})
            if context is not None else {}
        )
        if self.source != "lan" or not source_definitions:
            return original_reload(self, select_serid=select_serid)

        expanded: dict[str, bool] = {}
        old_root = self.station_tree.topLevelItem(0)
        if old_root is not None:
            for index in range(old_root.childCount()):
                item = old_root.child(index)
                sid = item.data(0, Qt.UserRole + 1)
                if sid:
                    expanded[str(sid)] = item.isExpanded()

        self.station_tree.blockSignals(True)
        self.station_tree.clear()
        root = QTreeWidgetItem(self.station_tree, ["Station"])
        root.setIcon(0, main_window.silk_icon("feed"))
        root.setExpanded(True)
        selected_item = None
        try:
            stations = list(self.repository.station_configs())
            mapping = context.device_admin.security.station_source_map()
            states = health_map()
            groups = group_stations_by_source(
                stations, mapping, source_definitions, states
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Station list error: {exc}")
            groups = []

        for group in groups:
            sid = str(group["source_id"])
            state = str(group["state"])
            host = str(group["host"])
            parent = QTreeWidgetItem(
                root,
                [f"Server {source_label(sid)} · {host} [{state}]"],
            )
            parent.setIcon(0, main_window.silk_icon("monitor"))
            parent.setData(0, Qt.UserRole + 1, sid)
            parent.setToolTip(0, f"source={sid} · host={host} · state={state}")
            parent.setExpanded(expanded.get(sid, True))
            for station in group["stations"]:
                child = QTreeWidgetItem(parent, [f"[{station.serid}] {station.room}"])
                child.setIcon(0, main_window.silk_icon("feed"))
                child.setData(0, Qt.UserRole, station.serid)
                child.setToolTip(
                    0,
                    f"[{station.serid}] {station.room} ({station.location}) · "
                    f"Alert {station.warnlevel:g} {station.unit}, "
                    f"Alarm {station.alarmlevel:g} {station.unit}",
                )
                if select_serid is not None and int(station.serid) == int(select_serid):
                    selected_item = child

        if selected_item is None:
            for index in range(root.childCount()):
                parent = root.child(index)
                if parent.childCount():
                    selected_item = parent.child(0)
                    break
        self.station_tree.blockSignals(False)
        if selected_item is not None:
            self.station_tree.setCurrentItem(selected_item)
            self._station_changed(selected_item)

    def select_station_from_recent(self, serid: int) -> None:
        if self.source != "lan":
            return original_select_recent(self, serid)
        root = self.station_tree.topLevelItem(0)
        if root is None:
            return
        for group_index in range(root.childCount()):
            parent = root.child(group_index)
            for index in range(parent.childCount()):
                item = parent.child(index)
                if int(item.data(0, Qt.UserRole) or 0) == int(serid):
                    parent.setExpanded(True)
                    self.station_tree.setCurrentItem(item)
                    return

    def refresh_parent_states(self) -> None:
        if self.source != "lan":
            return
        states = health_map()
        context = get_context()
        sources = dict(
            getattr(getattr(context, "device_admin", None), "source_definitions", {})
            if context is not None else {}
        )
        root = self.station_tree.topLevelItem(0)
        if root is None:
            return
        for index in range(root.childCount()):
            parent = root.child(index)
            sid = parent.data(0, Qt.UserRole + 1)
            if not sid:
                continue
            source = sources.get(str(sid))
            host = str(getattr(source, "host", ""))
            state = states.get(str(sid), "UNKNOWN")
            parent.setText(0, f"Server {source_label(str(sid))} · {host} [{state}]")

    def refresh_all(self) -> None:
        current_serid = getattr(self.settings, "serid", None)
        reload_station_sidebar(self, select_serid=current_serid)
        refresh_parent_states(self)
        original_refresh_current(self)
        context = get_context()
        if context is not None and hasattr(self.recent_page, "set_message_rows"):
            try:
                messages = []
                for item in context.source_health.list_states():
                    state = str(item.get("state") or "UNKNOWN")
                    message = f"[SERVER {state}] {item.get('source_id')} / {item.get('host')}"
                    if item.get("last_error") and state in {"DEGRADED", "OFFLINE"}:
                        message += f" - {item.get('last_error')}"
                    messages.append((item.get("updated_at") or "", message))
                self.recent_page.set_message_rows(messages)
            except Exception:
                pass

    def build_actions(self) -> None:
        original_build_actions(self)
        try:
            self.refresh_action.triggered.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.refresh_action.triggered.connect(self.refresh_all)
        try:
            self.install_manual_action.triggered.disconnect()
            self.user_manual_action.triggered.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.install_manual_action.triggered.connect(
            lambda: self._open_manual(main_window.INSTALLATION_MANUAL_PATH)
        )
        self.user_manual_action.triggered.connect(
            lambda: self._open_manual(main_window.USER_MANUAL_PATH)
        )

    def open_manual(self, relative_path: str) -> None:
        path = main_window.Path(relative_path).resolve()
        if not path.is_file():
            QMessageBox.information(self, "Manual", f"Manual belum tersedia: {relative_path}")
            return
        url = QUrl.fromLocalFile(str(path)).toString()
        if not main_window.open_external_url(url):
            QMessageBox.warning(self, "Manual", f"Gagal membuka manual di browser: {path}")

    def refresh_current_page(self) -> None:
        original_refresh_current(self)
        refresh_parent_states(self)
        context = get_context()
        if context is None:
            return
        try:
            active = context.alarm_mirror.list_alarms(active_only=True, limit=1)
        except Exception:
            active = []
        if active:
            now = time.monotonic()
            last = float(getattr(self, "_last_alarm_beep", 0.0))
            if now - last >= 1.5:
                QApplication.beep()
                self._last_alarm_beep = now

    main_window.MainWindow.reload_station_sidebar = reload_station_sidebar
    main_window.MainWindow._select_station_from_recent = select_station_from_recent
    main_window.MainWindow._refresh_source_parent_states = refresh_parent_states
    main_window.MainWindow.refresh_all = refresh_all
    main_window.MainWindow._build_actions = build_actions
    main_window.MainWindow._open_manual = open_manual
    main_window.MainWindow.refresh_current_page = refresh_current_page

    original_alarm_init = alarm_page.AlarmPage.__init__

    def alarm_init(self, *args, **kwargs):
        original_alarm_init(self, *args, **kwargs)
        self.ack_button.setText("Response / Silence")
        self.ack_button.setToolTip(
            "Isi Action/PIC/Note lalu submit untuk set i_flag=1 pada source."
        )

    alarm_page.AlarmPage.__init__ = alarm_init

    original_response_init = alarm_response_dialog.AlarmResponseDialog.__init__

    def response_init(self, *args, **kwargs):
        original_response_init(self, *args, **kwargs)
        self.setWindowTitle("Alarm Response / Silence")
        self.pic.returnPressed.connect(self.accept)
        for box in self.findChildren(alarm_response_dialog.QDialogButtonBox):
            button = box.button(alarm_response_dialog.QDialogButtonBox.Ok)
            if button is not None:
                button.setText("Submit / Silence")
                button.setDefault(True)

    alarm_response_dialog.AlarmResponseDialog.__init__ = response_init


def _patch_grafana() -> None:
    from . import grafana_tv as tv

    def dose_stat(panel_id, station, x, y, w, h=2):
        panel = tv._panel(
            panel_id,
            "stat",
            f"[{station.serid}] {station.room} ({station.location})",
            x, y, w, h,
        )
        panel["targets"] = [tv._target(f"""
SELECT doserate AS value
FROM vrecent
WHERE serid = {station.serid}
LIMIT 1
""")]
        # Alarm/alert classification is intentionally database-driven in the
        # Operations queries. Avoid freezing editable thresholds into JSON.
        panel["fieldConfig"] = {
            "defaults": {
                "unit": "suffix: µSv/h",
                "decimals": 2,
                "color": {"mode": "fixed", "fixedColor": "green"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [{"color": "green", "value": None}],
                },
            },
            "overrides": [],
        }
        panel["options"] = {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "text": {"valueSize": 28},
            "textMode": "value",
            "wideLayout": True,
        }
        return panel

    tv._dose_stat = dose_stat
