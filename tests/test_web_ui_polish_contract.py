from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_sidebar_brand_is_brin_logo_only_without_radmon_wordmark():
    desktop = read("layout/DesktopShell.tsx")
    assert '<strong>RadMon</strong>' not in desktop
    assert 'className="sidebar-logo"' in desktop


def test_mobile_more_uses_navigation_rows_and_bottom_sheet_geometry():
    more = read("layout/MobileMoreSheet.tsx")
    css = read("radmon.css") + "\n" + read("radmon-overlays.css") + "\n" + read("ui-polish.css")
    assert "mobile-sheet-panel" in more
    assert "mobile-more-route" in more
    assert "NavigationIcon" in more
    assert "bottom: calc(8px + env(safe-area-inset-bottom))" in css
    assert "border-radius: 20px" in css


def test_live_history_refresh_keeps_existing_content_mounted():
    history = read("pages/HistoryPage.tsx")
    assert "loadHistory(true)" in history
    assert "loadHistory(false)" in history
    assert "loading && rows.length === 0" in history
    assert "setRefreshing" in history


def test_other_live_pages_refresh_in_place_without_initial_loading_reset():
    for path in (
        "pages/OverviewPage.tsx",
        "pages/StationsPage.tsx",
        "pages/AlarmsPage.tsx",
        "pages/SystemPage.tsx",
        "pages/ArchivesPage.tsx",
    ):
        source = read(path)
        assert "useWebRefresh" in source
        assert "setLoading(true)" not in source, f"{path} tidak boleh mereset seluruh halaman saat live refresh"


def test_trend_chart_has_pointer_tooltip_crosshair_and_readable_axes():
    chart = read("components/TrendChart.tsx")
    css = read("radmon.css") + "\n" + read("ui-polish.css")
    assert "onPointerMove" in chart
    assert "onPointerLeave" in chart
    assert "trend-chart-tooltip" in chart
    assert "trend-chart-crosshair" in chart
    assert "trend-chart-y-label" in chart
    assert "pointer-events" in css


def test_mobile_dialogs_are_marked_for_sheet_treatment():
    actions = read("Actions.tsx")
    users = read("pages/UsersPage.tsx")
    assert actions.count('className="radmon-dialog mobile-sheet-dialog"') >= 2
    assert 'className="radmon-dialog mobile-sheet-dialog"' in users


def test_select_portals_have_a_layer_contract_above_dialog_and_navigation():
    css = read("radmon.css") + "\n" + read("radmon-overlays.css")
    assert "--radmon-layer-select: 100" in css
    assert "--radmon-layer-toast: 110" in css
    assert "[data-kumo-select-positioner]" in css
    assert "z-index: var(--radmon-layer-select) !important" in css
    assert ".mobile-sheet-dialog" not in css or "overflow: visible" not in css
    for path in ("pages/StationsPage.tsx", "pages/HistoryPage.tsx", "pages/ArchivesPage.tsx", "Actions.tsx"):
        assert "<Select" in read(path)


def test_alarm_operations_offer_preset_duration_and_active_cancellation_ui():
    actions = read("Actions.tsx")
    assert 'label="Durasi suppression"' in actions
    assert "15 menit" in actions and "1 jam" in actions
    assert "/api/v1/control/suppressions/" in actions
    assert "/cancel" in actions
    assert "Suppression aktif" in actions
    assert "/api/v1/control/suppressions?active_only=true" in read("pages/AlarmsPage.tsx")
    assert "source_silence_state" in actions


def test_alarm_events_remain_available_when_suppression_fetch_fails():
    alarms = read("pages/AlarmsPage.tsx")
    assert "Promise.allSettled" in alarms
    assert "suppressionError" in alarms
    assert "Muat ulang suppression" in alarms
