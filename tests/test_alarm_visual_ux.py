from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_current_alarm_requires_fresh_alarm_and_active_policy_event():
    component = source("web/src/components/AlarmStatus.tsx")
    current_alarm_guard = (
        'station.status === "alarm" && station.policy_state === "ALARM" &&'
        'station.underlying_dose_status === "ALARM" && station.active_event_id &&'
        'station.active_event_lifecycle === "ACTIVE"'
    )
    assert current_alarm_guard in component.replace("\n    ", "")
    assert 'station.status === "warning" || (' in component
    assert 'station.policy_state === "SUPPRESSED" || station.policy_state === "RETRIGGER_LOCKED"' in component
    assert 'station.status === "offline" && (station.active_event_id || station.last_event_id)' in component
    assert "tidak sedang berbunyi" in component


def test_alarm_notification_is_accessible_and_deduplicated_by_event_id():
    component = source("web/src/components/AlarmStatus.tsx")
    assert 'role="alert" aria-live="assertive" aria-atomic="true"' in component
    assert "const notifiedAlarmEvents = new Set<string>()" in component
    assert "notifiedAlarmEvents.has(eventId)" in component
    assert "notifiedAlarmEvents.add(eventId)" in component


def test_action_navigation_is_operator_gated_and_deep_links_to_response_modal():
    for path in (
        "web/src/pages/OverviewPage.tsx",
        "web/src/pages/StationsPage.tsx",
        "web/src/pages/StationDetailPage.tsx",
        "web/src/pages/HistoryPage.tsx",
    ):
        text = source(path)
        assert 'user.role !== "Viewer"' in text
        assert 'navigate("alarms", { serid: station.serid, event: station.active_event_id' in text or (
            'navigate("alarms", { serid: item.serid, event: item.active_event_id' in text
        )
    assert "initialEventId={requestedEventId}" in source("web/src/pages/AlarmsPage.tsx")
    assert "setRespondOpen(true)" in source("web/src/Actions.tsx")


def test_alarm_motion_has_a_reduced_motion_fallback():
    css = source("web/src/radmon.css")
    assert ".alarm-status-dot.is-blinking" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "animation-duration: .01ms !important" in css
