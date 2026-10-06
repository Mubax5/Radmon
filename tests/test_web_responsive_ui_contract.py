from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_adaptive_shell_files_exist_and_mobile_navigation_is_role_aware():
    assert (WEB / "layout/DesktopShell.tsx").exists()
    assert (WEB / "layout/MobileShell.tsx").exists()
    assert (WEB / "layout/MobileMoreSheet.tsx").exists()
    nav = read("navigation.ts")
    more_sheet = read("layout/MobileMoreSheet.tsx")
    assert "Viewer" in nav and "Operator" in nav and "Administrator" in nav
    for label in ("Ringkasan", "Stasiun", "Riwayat", "Arsip", "Alarm", "Pengguna", "Sistem"):
        assert label in nav
    assert '"more"' in nav
    assert "Lainnya" in more_sheet


def test_mobile_first_css_has_exact_breakpoints_safe_areas_and_no_unsafe_page_width():
    css = read("radmon.css")
    assert "100dvh" in css
    assert "env(safe-area-inset-bottom" in css
    assert "@media (min-width: 768px)" in css
    assert "@media (min-width: 1024px)" in css
    assert "@media (max-width: 767px)" not in css
    assert "100vw" not in css
    assert "prefers-reduced-motion" in css


def test_mobile_and_desktop_data_presentations_are_explicit():
    source = read("components/ResponsiveDataView.tsx")
    assert "desktop" in source
    assert "mobile" in source
    station = read("components/StationViews.tsx")
    assert "StationTable" in station
    assert "StationCards" in station


def test_history_has_dependency_free_svg_trend_chart():
    chart = read("components/TrendChart.tsx")
    package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    assert "<svg" in chart
    assert "polyline" in chart or "path" in chart
    assert "recharts" not in package.lower()
    assert "chart.js" not in package.lower()


def test_control_plane_uses_consistent_phosphor_navigation_icons_without_letter_r_badges():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in WEB.rglob("*.tsx"))
    assert re.search(r">\s*R\s*<", combined) is None
    layout_dir = WEB / "layout"
    layout_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in layout_dir.glob("*.tsx")
    ) if layout_dir.exists() else ""
    assert "@phosphor-icons/react" in layout_sources
    assert "nav-icon" in layout_sources


def test_mobile_topbar_is_brand_only_and_bottom_nav_uses_icon_over_small_label():
    mobile_shell = read("layout/MobileShell.tsx")
    css = read("radmon.css")
    assert "<strong>{routeLabel(route)}</strong>" not in mobile_shell
    assert "mobile-nav-icon" in mobile_shell
    assert "mobile-nav-label" in mobile_shell
    assert ".mobile-nav-button" in css
    assert "flex-direction: column" in css
    assert ".mobile-content .page-heading h1 { display: none; }" not in css


def test_primary_page_copy_defaults_to_indonesian():
    expectations = {
        "pages/OverviewPage.tsx": ("Monitoring radiasi", "Perhatian", "Kesehatan stasiun"),
        "pages/StationsPage.tsx": ("Stasiun", "Cari", "Detail stasiun"),
        "pages/HistoryPage.tsx": ("Riwayat", "measurement", "Rekaman"),
        "pages/ArchivesPage.tsx": ("Arsip", "Detail arsip"),
        "pages/AlarmsPage.tsx": ("Tindakan operator", "Respons alarm", "Riwayat event"),
        "pages/UsersPage.tsx": ("Pengguna", "Buat pengguna"),
        "pages/SystemPage.tsx": ("Sistem", "Kesehatan source", "Administrasi Grafana"),
    }
    for path, phrases in expectations.items():
        source = read(path)
        for phrase in phrases:
            assert phrase in source, f"{phrase!r} belum ada di {path}"


def test_pages_have_relevant_compact_sections():
    assert "attention" in read("pages/OverviewPage.tsx").lower()
    assert "station-search" in read("pages/StationsPage.tsx")
    assert "history-summary" in read("pages/HistoryPage.tsx")
    assert "archive-summary" in read("pages/ArchivesPage.tsx")
    assert "active-alarm" in read("pages/AlarmsPage.tsx")
    assert "user-summary" in read("pages/UsersPage.tsx")
    assert "source-health" in read("pages/SystemPage.tsx")


def test_history_keeps_station_toolbar_before_summary_and_chart_with_compact_rules():
    history = read("pages/HistoryPage.tsx")
    css = read("ui-polish.css")
    assert 'className="page-stack history-page"' in history
    assert history.index('className="filter-card history-filter"') < history.index('className="metric-grid history-summary"')
    assert history.index('className="metric-grid history-summary"') < history.index('className="action-card trend-chart-card"')
    carousel = history[history.index('className="history-carousel"'):history.index('className="history-toolbar-meta"')]
    for control in ('data-testid="history-prev"', 'data-testid="history-station-combobox"', 'data-testid="history-next"'):
        assert control in carousel
    assert 'data-testid="history-search"' not in history
    assert 'data-testid="history-station-select"' not in history
    assert 'data-testid="history-range-select"' not in history
    assert 'Offline — last-known' in history
    assert '.history-carousel {' in css and 'grid-template-columns: 40px minmax(0, 1fr) 40px' in css
    assert 'grid-template-columns: minmax(0, 1fr);' in css
    assert 'column-gap: 12px' in css and 'row-gap: 8px' in css
    assert 'justify-content: flex-end' in css and 'overflow-wrap: anywhere' in css
    assert 'min-height: 68px' in css and 'padding: 12px 14px' in css
    assert '@media (max-width: 767px)' in css and 'grid-template-columns: minmax(0, 1fr);' in css
    assert '.history-page .trend-chart svg {' in css and 'min-height: 0' in css


def test_history_uses_one_accessible_local_searchable_station_combobox_and_centered_arrows():
    history = read("pages/HistoryPage.tsx")
    css = read("ui-polish.css")
    assert history.count('data-testid="history-station-combobox"') == 1
    assert '<input' in history and 'type="text"' in history
    assert 'role="combobox"' in history
    assert 'aria-autocomplete="list"' in history
    assert 'aria-haspopup="listbox"' in history
    assert 'aria-activedescendant=' in history
    assert 'role="listbox"' in history and 'role="option"' in history
    assert '`${station.name} ${station.serid}`' in history
    assert 'onKeyDown={handleStationKeyDown}' in history
    assert 'event.key === "ArrowDown"' in history
    assert 'event.key === "ArrowUp"' in history
    assert 'event.key === "Enter"' in history
    assert 'event.key === "Escape"' in history
    assert 'history-station-listbox' in history
    assert 'stationLabel(selectedStation)' in history
    assert 'onClick={() => selectStation(station)}' in history
    assert 'createPortal(' in history and 'document.body' in history
    assert 'position: "fixed"' in history
    assert 'import { CaretLeft, CaretRight } from "@phosphor-icons/react"' in history
    assert '<CaretLeft aria-hidden="true"' in history
    assert '<CaretRight aria-hidden="true"' in history
    assert '‹' not in history and '›' not in history
    assert '.history-station-listbox {' in css
    assert 'position: fixed' in css[css.index('.history-station-listbox {'):css.index('.history-station-listbox [role="option"] {')]
    assert 'z-index: 2147483647' in css[css.index('.history-station-listbox {'):css.index('.history-station-listbox [role="option"] {')]
    assert 'width: 40px' in css[css.index('.history-carousel > button {'):css.index('.history-station-selector {')]
    assert 'height: 40px' in css[css.index('.history-carousel > button {'):css.index('.history-station-selector {')]
    assert 'display: grid' in css[css.index('.history-carousel > button {'):css.index('.history-station-selector {')]
    assert 'place-items: center' in css[css.index('.history-carousel > button {'):css.index('.history-station-selector {')]
    mobile = css[css.index('@media (max-width: 767px)'):css.index('@media (min-width: 768px)', css.index('@media (max-width: 767px)'))]
    assert 'grid-template-columns: 40px minmax(0, 1fr) 40px' in mobile
    assert 'height: 40px' in mobile


def test_history_controls_share_one_row_and_chart_uses_remaining_page_height():
    history = read("pages/HistoryPage.tsx")
    css = read("ui-polish.css")
    toolbar_start = history.index('<div className="history-toolbar">')
    toolbar_end = history.index("</div>", history.index('className="history-toolbar-meta"'))
    toolbar = history[toolbar_start:toolbar_end]
    assert toolbar.index('data-testid="history-prev"') < toolbar.index('data-testid="history-station-combobox"')
    assert toolbar.index('data-testid="history-station-combobox"') < toolbar.index('data-testid="history-next"')
    assert toolbar.index('data-testid="history-next"') < toolbar.index('className="history-toolbar-meta"')
    assert 'data-testid="history-range-select"' not in toolbar
    assert "grid-template-rows: auto auto auto minmax(300px, 1fr) auto" in css
    assert "min-height: calc(100dvh - 88px)" in css
    assert ".history-page .trend-chart-plot" in css
    assert "height: 100%" in css and "overflow: auto" not in css[css.index(".history-page > .page-section:has(.trend-chart-card)"):css.index(".mobile-sheet-handle")]


def test_dialogs_and_mobile_navigation_reserve_viewport_space():
    css = read("radmon.css") + "\n" + read("ui-polish.css")
    assert "calc(84px + env(safe-area-inset-bottom))" in css
    assert "max-height: calc(100dvh" in css or "height: min(" in css


def test_mutating_forms_have_pending_guards():
    actions = read("Actions.tsx")
    assert "pending" in actions
    assert "disabled={" in actions


def test_session_expiry_returns_to_radmon_login():
    api = read("api.ts")
    auth = read("auth.tsx")
    assert "radmon:session-expired" in api
    assert "radmon:session-expired" in auth
    assert '"/app/login"' in auth


def test_history_route_accepts_station_query_context():
    history = read("pages/HistoryPage.tsx")
    assert 'get("station")' in history
    assert "replaceState" in history


def test_login_branding_remains_centered_and_uses_only_brin_logo():
    auth = read("auth.tsx")
    css = read("radmon.css")
    assert "brin-logo.png" in auth
    assert "login-brand" in auth
    assert "justify-content: center" in css
    assert re.search(r">\s*R\s*<", auth) is None
