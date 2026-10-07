from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def active_alarms(mirror: Any, policy: Any) -> list[dict[str, Any]]:
    """Current actionable rows; history pagination and resolved policy never hide sources."""
    bound = 10000
    sources = mirror.list_alarms(active_only=True, limit=bound + 1) if mirror else []
    policies = policy.list_events(active_only=True, limit=bound + 1) if policy else []
    if len(sources) > bound or len(policies) > bound:
        raise RuntimeError('active alarm capacity exceeded; complete list unavailable')
    policies = {row['event_id']: dict(row, event_type='policy_lifecycle')
                for row in policies if row.get('kind') == 'ALARM' and row.get('status') == 'ACTIVE'}

    def time_text(value):
        return value.isoformat() if isinstance(value, datetime) else str(value or '')

    def same_occurrence(left, right):
        """Compare persisted source/policy times without trusting formatting."""
        if left is None or right is None:
            return False
        left_dt = left if isinstance(left, datetime) else None
        right_dt = right if isinstance(right, datetime) else None
        if left_dt is None and isinstance(left, str):
            try:
                left_dt = datetime.fromisoformat(left)
            except ValueError:
                pass
        if right_dt is None and isinstance(right, str):
            try:
                right_dt = datetime.fromisoformat(right)
            except ValueError:
                pass
        if left_dt is not None and right_dt is not None:
            # Source MariaDB timestamps may be naive while central policy rows
            # may be UTC-aware. Their persisted wall-clock occurrence is the
            # correlation contract, as in policy reconciliation.
            return abs(left_dt.replace(tzinfo=None) - right_dt.replace(tzinfo=None)) <= timedelta(seconds=5)
        return time_text(left) == time_text(right)

    rows = []
    used = set()
    for raw in sources:
        fields = ('source_id', 'serid', 'remote_serid', 'event_time', 'level', 'measured_value',
                  'threshold', 'hit_count', 'is_active', 'source_i_flag', 'source_observed_at')
        source = {key: raw[key] for key in fields if key in raw}
        # Prefer the persisted correlation. Exact identity fallback supports older mirrors;
        # never collapse separate sources or occurrences using SERID alone.
        linked = policies.get(raw.get('policy_event_id'))
        if linked is None:
            candidates = [row for row in policies.values()
                          if row.get('source_id') == source.get('source_id')
                           and row.get('serid') == source.get('serid')
                           and row.get('remote_serid') == source.get('remote_serid')
                           and same_occurrence(row.get('remote_event_time'), source.get('event_time'))]
            linked = candidates[0] if len(candidates) == 1 else None
        if linked is not None:
            if raw.get('policy_event_id') == linked['event_id'] and linked['event_id'] not in used:
                rows.append(dict(linked, source_alarm=source))
                used.add(linked['event_id'])
                continue
            if raw.get('policy_event_id') == linked['event_id']:
                continue
            # An exact match without a persisted link cannot use policy response:
            # that route dispatches only linked rows. Keep the source ack action.
            used.add(linked['event_id'])
        rows.append(dict(source, event_id=f"source:{source['source_id']}:{source['serid']}:{time_text(source['event_time'])}",
                         event_type='source_alarm', kind='SOURCE_ALARM', status='ACTIVE',
                         surfaced_at=source['event_time'], reason='HIGH_THRESHOLD' if source.get('level') == 'ALARM' else 'LOW_THRESHOLD'))
    rows.extend(row for key, row in policies.items() if key not in used)
    return sorted(rows, key=lambda row: time_text(row.get('surfaced_at')), reverse=True)
