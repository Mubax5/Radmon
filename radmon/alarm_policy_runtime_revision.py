"""Restart/runtime compatibility for the central alarm policy.

Persisted policy events are restored for visibility, notification delivery stays
closed until a fresh live policy cycle completes, and the latest live policy
snapshot is retained so desktop/API consumers can show SUPPRESSED together with
the real underlying dose condition.
"""
from __future__ import annotations


def apply() -> None:
    from . import alarm_policy as module

    original_snapshot = module.AlarmPolicyService._snapshot
    original_get_policy = module.AlarmPolicyService.get_policy
    original_list_events = module.AlarmPolicyService.list_events
    original_process_cycle = module.AlarmPolicyService.process_cycle

    def _snapshot(self, tx, *, underlying, measured_value=None,
                  threshold=None, active_event_id=None):
        snapshot = original_snapshot(
            self,
            tx,
            underlying=underlying,
            measured_value=measured_value,
            threshold=threshold,
            active_event_id=active_event_id,
        )
        cache = getattr(self, "_current_policy_snapshots", None)
        if cache is None:
            cache = {}
            self._current_policy_snapshots = cache
        copy = dict(snapshot)
        copy["updated_at"] = tx.state.updated_at or self.now()
        cache[int(snapshot["serid"])] = copy
        return snapshot

    def get_policy(self, serid):
        persistent = original_get_policy(self, serid)
        cache = getattr(self, "_current_policy_snapshots", {})
        live = dict(cache.get(int(serid), {}))
        result = dict(live)
        result.update(persistent)

        suppression = persistent.get("suppression") or {}
        underlying = live.get("underlying_dose_status")
        if not underlying:
            if persistent.get("active_event_id") or persistent.get("retrigger_locked"):
                underlying = "ALARM"
            else:
                underlying = "UNKNOWN"

        if persistent.get("suppressed"):
            policy_state = "SUPPRESSED"
        elif persistent.get("retrigger_locked") and underlying == "ALARM":
            policy_state = "RETRIGGER_LOCKED"
        elif persistent.get("active_event_id"):
            policy_state = "ALARM"
        elif underlying in {"NORMAL", "ALERT", "ALARM"}:
            policy_state = underlying
        else:
            policy_state = "NORMAL"

        result.update({
            "policy_state": policy_state,
            "underlying_dose_status": underlying,
            "measured_value": live.get("measured_value"),
            "threshold": live.get("threshold"),
            "suppression_id": suppression.get("suppression_id"),
            "suppression_expires_at": suppression.get("expires_at"),
            "suppression_pic": suppression.get("pic"),
            "suppression_reason": suppression.get("reason"),
            "updated_at": live.get("updated_at") or persistent.get("last_trigger_at") or persistent.get("last_normal_at"),
        })
        return result

    def list_events(self, *, serid=None, active_only=False,
                    notify_pending_only=False, limit=500):
        if notify_pending_only and not bool(getattr(self, "notifications_enabled", True)):
            return []
        return original_list_events(
            self,
            serid=serid,
            active_only=active_only,
            notify_pending_only=notify_pending_only,
            limit=limit,
        )

    def process_cycle(self, source_id, live_rows, alarm_rows):
        events = original_process_cycle(self, source_id, live_rows, alarm_rows)
        # Only a completed live evaluation opens the notification gate. A
        # startup restore by itself is intentionally insufficient.
        self.notifications_enabled = True
        return events

    module.AlarmPolicyService._snapshot = _snapshot
    module.AlarmPolicyService.get_policy = get_policy
    module.AlarmPolicyService.list_events = list_events
    module.AlarmPolicyService.process_cycle = process_cycle
