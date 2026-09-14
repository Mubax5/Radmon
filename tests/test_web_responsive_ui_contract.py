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
    mobile_shell = read("layout/MobileShell.tsx")
    assert "Viewer" in nav and "Operator" in nav and "Administrator" in nav
    assert "Overview" in nav and "Stations" in nav and "History" in nav and "Alarms" in nav
    assert '"more"' in nav
    assert "More" in mobile_shell


def test_mobile_first_css_has_exact_breakpoints_safe_areas_and_no_unsafe_page_width():
    css = read("radmon.css")
    assert "100dvh" in css
    assert "env(safe-area-inset-bottom" in css
    assert "@media (min-width: 640px)" in css
    assert "@media (min-width: 1024px)" in css
    assert "@media (max-width: 640px)" not in css
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


def test_control_plane_never_reintroduces_letter_r_brand_badges_or_phosphor_nav_icons():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in WEB.rglob("*.tsx"))
    assert re.search(r">\s*R\s*<", combined) is None
    layout_dir = WEB / "layout"
    layout_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in layout_dir.glob("*.tsx")
    ) if layout_dir.exists() else ""
    assert "@phosphor-icons/react" not in layout_sources


def test_pages_have_relevant_compact_sections():
    assert "attention" in read("pages/OverviewPage.tsx").lower()
    assert "station-search" in read("pages/StationsPage.tsx")
    assert "history-summary" in read("pages/HistoryPage.tsx")
    assert "archive-summary" in read("pages/ArchivesPage.tsx")
    assert "active-alarm" in read("pages/AlarmsPage.tsx")
    assert "user-summary" in read("pages/UsersPage.tsx")
    assert "source-health" in read("pages/SystemPage.tsx")


def test_dialogs_and_mobile_navigation_reserve_viewport_space():
    css = read("radmon.css")
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
