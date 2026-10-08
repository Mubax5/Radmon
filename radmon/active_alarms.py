from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


_SOURCE_FIELDS = (
    'source_id', 'serid', 'remote_serid', 'event_time', 'level',
    'measured_value', 'threshold', 'hit_count', 'is_active', 'source_i_flag',
    'source_observed_at', 'source_observation_version',
)
_POLICY_FIELDS = (
    'event_id', 'source_id', 'serid', 'remote_serid', 'remote_event_time',
    'surfaced_at', 'origin', 'kind', 'trigger_index', 'measured_value',
    'threshold', 'status', 'suppression_id', 'responded_at',
    'notification_sent_at', 'resolved_at', 'resolution_code',
)


def _time_text(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or '')


def _source_is_actionable(row: dict[str, Any]) -> bool:
    """Return true only for a mirrored source row whose i_flag is still zero."""
    try:
        return bool(row.get('is_active')) and int(row.get('source_i_flag')) == 0
    except (TypeError, ValueError):
        # An absent/invalid source latch is not evidence that an alarm is
        # sounding. The source action must fail closed until a valid poll.
        return False


def _source_action_row(raw: dict[str, Any]) -> dict[str, Any]:
    source = {key: raw[key] for key in _SOURCE_FIELDS if key in raw}
    event_time = source.get('event_time')
    source_actionable = _source_is_actionable(source)
    return dict(
        source,
        event_id=f"source:{source.get('source_id')}:{source.get('serid')}:{_time_text(event_time)}",
        event_type='source_alarm',
        kind='SOURCE_ALARM',
        status='ACTIVE' if source_actionable else 'ACKNOWLEDGED',
        surfaced_at=event_time,
        reason='HIGH_THRESHOLD' if source.get('level') == 'ALARM' else 'LOW_THRESHOLD',
        # This is deliberately derived from the source mirror, not policy
        # status, dose rate, threshold, notification, or browser settings.
        source_actionable=source_actionable,
    )


def _policy_view_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the read-only policy projection used by viewer-facing routes."""
    return {key: raw[key] for key in _POLICY_FIELDS if key in raw}


def active_alarm_snapshot(mirror: Any, policy: Any) -> dict[str, Any]:
    """Read one consistent active snapshot and split source actions from policy rows.

    ``items`` remains the merged informational view for compatibility. The
    ``source_items`` projection is the only list permitted to drive a source
    response in the web UI. It is built from the same active mirror read, so a
    policy-only ACTIVE event cannot manufacture a source action.
    """
    bound = 10000
    sources = mirror.list_alarms(active_only=True, limit=bound + 1) if mirror else []
    policies = policy.list_events(active_only=True, limit=bound + 1) if policy else []
    if len(sources) > bound or len(policies) > bound:
        raise RuntimeError('active alarm capacity exceeded; complete list unavailable')
    # ``active_only`` is a local projection; the source latch remains the
    # authoritative gate in case an inconsistent/stale mirror row has
    # is_active=1 while i_flag is already 1.
    sources = [raw for raw in sources if _source_is_actionable(dict(raw))]
    policies = {row['event_id']: dict(_policy_view_row(row), event_type='policy_lifecycle')
                for row in policies if row.get('kind') == 'ALARM' and row.get('status') == 'ACTIVE'}

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
        return _time_text(left) == _time_text(right)

    source_items = [_source_action_row(dict(raw)) for raw in sources]
    rows = []
    used = set()
    for raw in sources:
        source = {key: raw[key] for key in _SOURCE_FIELDS if key in raw}
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
                rows.append(dict(linked, source_alarm=source, source_actionable=False))
                used.add(linked['event_id'])
                continue
            if raw.get('policy_event_id') == linked['event_id']:
                continue
            # An exact match without a persisted link cannot use policy response:
            # that route dispatches only linked rows. Keep the source ack action.
            used.add(linked['event_id'])
        rows.append(_source_action_row(source))
    rows.extend(row for key, row in policies.items() if key not in used)
    return {
        'items': sorted(rows, key=lambda row: _time_text(row.get('surfaced_at')), reverse=True),
        'source_items': sorted(source_items, key=lambda row: _time_text(row.get('surfaced_at')), reverse=True),
        'source_active_count': len(source_items),
    }


def active_alarms(mirror: Any, policy: Any) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that need the merged informational view."""
    return active_alarm_snapshot(mirror, policy)['items']
