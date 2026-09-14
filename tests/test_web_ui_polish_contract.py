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
