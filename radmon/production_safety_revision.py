"""Final production safety guards for LAN source writes and alarm state.

These patches are intentionally applied after the main production integration
revision. They ensure Station Properties can write to a source only when LAN
mode is explicitly enabled, revoke desktop PIN elevation on logout/context
clear, and reconcile externally silenced source alarms even when the original
alarm is old.
"""
from __future__ import annotations

from datetime import datetime
import os
from typing import Iterable


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def apply() -> None:
    _guard_station_write_through()
    _clear_desktop_sensitive_lease()
    _add_alarm_active_set_reconciliation()


def _guard_station_write_through() -> None:
    from . import secure_services as module

    previous_build = module.build_secure_services

    def build_secure_services(*args, **kwargs):
        services = previous_build(*args, **kwargs)
        if not _enabled("RADMON_LAN_ENABLED", False):
            # Merely listing LAN endpoints in .env must never authorize source
            # writes. Explicit LAN runtime enablement is the safety boundary.
            services.device_admin.write_through = False
            services.device_admin.station_source = None
            services.device_admin.remote_factory = None
        return services

    module.build_secure_services = build_secure_services


def _clear_desktop_sensitive_lease() -> None:
    from . import secure_context as module

    previous_set_context = module.set_context

    def set_context(value) -> None:
        current = module.get_context()
        if current is not None and (
            value is None
            or getattr(value, "identity", None) != getattr(current, "identity", None)
        ):
            try:
                current.security.clear_sensitive_lease(current.identity.username)
            except Exception:
                pass
        previous_set_context(value)

    module.set_context = set_context


def _add_alarm_active_set_reconciliation() -> None:
    from . import lan as lan_module
    from . import remote_alarm as alarm_module

    def active_alarm_keys(self) -> list[tuple[int, datetime]]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                # Only two compact fields are needed on every 2-second cycle.
                # This includes old alarms that are still active without
                # repeatedly transferring all historical alarm payloads.
                cursor.execute(
                    """
SELECT serid, dtoa
FROM alarm
WHERE i_flag = 0
ORDER BY dtoa ASC, serid ASC
"""
                )
                rows = cursor.fetchall()
            result: list[tuple[int, datetime]] = []
            for row in rows:
                if isinstance(row, dict):
                    serid = row.get("serid")
                    dtoa = row.get("dtoa")
                else:
                    serid, dtoa = row[0], row[1]
                if serid is not None and isinstance(dtoa, datetime):
                    result.append((int(serid), dtoa))
            return result
        finally:
            connection.close()

    def reconcile_source_active_keys(
        self,
        source_id: str,
        active_keys: set[tuple[int, datetime]],
    ) -> list[tuple[int, datetime]]:
        self._ensure_active_schema()
        normalized = {
            (int(serid), when.isoformat())
            for serid, when in active_keys
            if isinstance(when, datetime)
        }
        handled: list[tuple[int, datetime]] = []
        with self.store._connection() as connection:
            rows = connection.execute(
                """
SELECT serid, event_time
FROM remote_alarm_state
WHERE source_id = ? AND is_active = 1
""",
                (str(source_id),),
            ).fetchall()
            for serid, event_text in rows:
                key = (int(serid), str(event_text))
                if key in normalized:
                    continue
                cursor = connection.execute(
                    """
UPDATE remote_alarm_state
SET is_active = 0
WHERE source_id = ? AND serid = ? AND event_time = ? AND is_active = 1
""",
                    (str(source_id), int(serid), str(event_text)),
                )
                if cursor.rowcount == 1:
                    handled.append((int(serid), datetime.fromisoformat(str(event_text))))
        return handled

    def mark_alarm_handled(self, keys: Iterable[tuple[int, datetime]]) -> int:
        values = list(keys)
        if not values:
            return 0
        connection = self._connection()
        changed = 0
        try:
            with connection.cursor() as cursor:
                for serid, event_time in values:
                    cursor.execute(
                        """
UPDATE alarm
SET i_flag = 1
WHERE serid = ? AND dtoa = ? AND i_flag = 0
""",
                        (int(serid), event_time),
                    )
                    changed += max(0, int(getattr(cursor, "rowcount", 0)))
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    previous_run_live = lan_module.LanAggregator.run_live_once

    def run_live_once(self, source):
        result = previous_run_live(self, source)
        if result.error or self.alarm_mirror is None:
            return result
        try:
            remote = self.remote_factory(source)
            key_reader = getattr(remote, "active_alarm_keys", None)
            if not callable(key_reader):
                return result
            active_keys: set[tuple[int, datetime]] = set()
            for remote_serid, event_time in key_reader():
                central_serid = self.checkpoints.store.resolve_station(
                    source.source_id, int(remote_serid)
                )
                active_keys.add((int(central_serid), event_time))
            handled = self.alarm_mirror.reconcile_source_active_keys(
                source.source_id, active_keys
            )
            if handled and hasattr(self.central, "mark_alarm_handled"):
                self.central.mark_alarm_handled(handled)
        except Exception as exc:
            result.error = str(exc)
        return result

    lan_module.RemoteMariaDBSource.active_alarm_keys = active_alarm_keys
    alarm_module.RemoteAlarmMirror.reconcile_source_active_keys = reconcile_source_active_keys
    lan_module.MariaCentralStore.mark_alarm_handled = mark_alarm_handled
    lan_module.LanAggregator.run_live_once = run_live_once
