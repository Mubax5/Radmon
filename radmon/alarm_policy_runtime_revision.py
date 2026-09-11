"""Restart-safe notification gate for the central alarm policy.

Persisted policy events are restored for visibility, but notification delivery
stays closed until a fresh live policy cycle has completed. Historical seed
rows therefore cannot be re-emitted as new WhatsApp notifications after a
restart.
"""
from __future__ import annotations


def apply() -> None:
    from . import alarm_policy as module

    original_list_events = module.AlarmPolicyService.list_events
    original_process_cycle = module.AlarmPolicyService.process_cycle

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

    module.AlarmPolicyService.list_events = list_events
    module.AlarmPolicyService.process_cycle = process_cycle
