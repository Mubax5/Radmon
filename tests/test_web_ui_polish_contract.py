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
    assert '<dialog ref={dialog} className="native-user-dialog"' in users


def test_response_and_role_controls_are_native_and_browser_selectable():
    actions = read("Actions.tsx")
    users = read("pages/UsersPage.tsx")
    css = read("ui-polish.css")
    assert 'testId="alarm-event-select"' in actions
    assert 'testId="alarm-action-select"' in actions
    assert 'testId="user-role-select"' in actions
    assert 'name="action"' in actions and 'name="role"' in actions
    assert 'value={selectedEventId}' in actions
    assert 'body: JSON.stringify({' in actions
    assert 'role,' in actions
    assert 'data-testid="user-create-dialog"' in users
    assert ".native-select-field" in css
    assert ".native-select" in css


def test_select_portals_have_a_layer_contract_above_dialog_and_navigation():
    css = read("radmon.css") + "\n" + read("radmon-overlays.css")
    assert "--radmon-layer-select: 100" in css
    assert "--radmon-layer-toast: 110" in css
    assert "[data-kumo-select-positioner]" in css
    assert "z-index: var(--radmon-layer-select) !important" in css
    assert ".mobile-sheet-dialog" not in css or "overflow: visible" not in css
    for path in ("pages/StationsPage.tsx", "pages/HistoryPage.tsx", "pages/ArchivesPage.tsx"):
        assert "<Select" in read(path)
    assert 'testId="suppression-duration-select"' in read("Actions.tsx")


def test_sidebar_icons_have_fixed_geometry_and_consistent_mobile_breakpoint():
    desktop = read("layout/DesktopShell.tsx")
    css = read("radmon.css") + "\n" + read("ui-polish.css")
    responsive = read("responsive.ts")
    assert 'data-testid="sidebar-collapse-trigger"' in desktop
    assert 'mobileBreakpoint={768}' in desktop
    assert "sidebar-icon-wrapper" in desktop
    assert "width: 24px" in css and "height: 24px" in css
    assert "(max-width: 767px)" in responsive
    assert "@media (min-width: 768px)" in css


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


def test_alarms_page_renders_full_content_on_suppression_partial_success():
    alarms = read("pages/AlarmsPage.tsx")
    # Partial-success: event + suppression dimuat lewat allSettled, suppression
    # gagal tidak boleh mengosongkan items atau menyembunyikan operasi.
    assert "Promise.allSettled" in alarms
    assert "/api/v1/control/alarm-events" in alarms
    assert "/api/v1/control/suppressions?active_only=true" in alarms
    assert "<AlarmOperations events={items} suppressions={suppressions}" in alarms
    # Event gagal pada load awal harus tampilkan error + retry eksplisit,
    # bukan skeleton/blank putih selamanya.
    assert "Muat ulang alarm" in alarms
    assert "Memuat alarm" in alarms
    assert "!items ? <LoadingCard" not in alarms
    # Data basi saat live refresh gagal tetap ditampilkan dengan penanda usang.
    assert "mungkin usang" in alarms


def test_alarms_overlay_keeps_background_mounted_and_stacked():
    css = read("radmon.css") + "\n" + read("radmon-overlays.css")
    alarms = read("pages/AlarmsPage.tsx")
    actions = read("Actions.tsx")
    # Kontrak lapisan: backdrop 80 < dialog 90 < select portal 100 < toast 110.
    assert "--radmon-layer-backdrop" in css
    assert "--radmon-layer-dialog: 90" in css
    assert "--radmon-layer-select: 100" in css
    assert "--radmon-layer-toast: 110" in css
    assert '[role="presentation"]' in css or "backdrop" in css.lower()
    assert '[role="dialog"]' in css
    assert "[data-kumo-select-positioner]" in css
    assert "z-index: var(--radmon-layer-select) !important" in css
    # Modal portal tidak boleh meng-unmount/menyembunyikan background halaman.
    assert 'body:has([role="dialog"])' in css
    assert ".page-stack" in css
    assert "visibility: visible" in css
    # State dialog hidup di Actions, bukan di page, sehingga background tetap mounted.
    assert "respondOpen" not in alarms
    assert 'className="radmon-dialog mobile-sheet-dialog"' in actions


def test_alarms_dropdown_filled_from_active_with_empty_state():
    actions = read("Actions.tsx")
    # Dropdown wajib diturunkan dari event ALARM ACTIVE.
    assert "ALARM" in actions and "ACTIVE" in actions
    assert "eventItems" in actions
    assert "Pilih event" in actions
    # Empty-state jelas saat tidak ada alarm aktif, plus hitungan saat ada.
    assert "Tidak ada alarm aktif" in actions
    assert "alarm-empty-hint" in actions
    assert 'role="status"' in actions
    # Pilihan basi dibersihkan saat live refresh menyelesaikan event terpilih.
    assert "active.some" in actions
    assert 'setEventId("")' in actions


def test_alarms_loading_is_skeleton_not_blank():
    alarms = read("pages/AlarmsPage.tsx")
    ui = read("ui.tsx")
    css = read("radmon.css")
    assert "Memuat alarm" in alarms
    assert "LoadingCard" in alarms
    assert 'role="status"' in ui
    assert 'aria-busy="true"' in ui
    assert "skeleton-line" in ui
    assert "loading-skeleton-card" in css
    assert "skeleton-line" in css
    assert "radmon-skeleton-shimmer" in css
