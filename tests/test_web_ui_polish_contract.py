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
    css = read("radmon.css") + "\n" + read("radmon-overlays.css")
    assert "mobile-sheet-panel" in more
    assert "mobile-more-route" in more
    assert "NavigationIcon" in more
    assert "bottom: 0" in css
    assert "border-radius" in css


def test_live_history_refresh_keeps_existing_content_mounted():
    history = read("pages/HistoryPage.tsx")
    assert "loadHistory(true)" in history
    assert "loadHistory(false)" in history
    assert "loading && rows.length === 0" in history
    assert "setRefreshing" in history


def test_live_pages_do_not_replace_loaded_content_with_initial_loading_state():
    expectations = {
        "pages/OverviewPage.tsx": "data",
        "pages/StationsPage.tsx": "stations",
        "pages/AlarmsPage.tsx": "items",
        "pages/SystemPage.tsx": "data",
    }
    for path, state_name in expectations.items():
        source = read(path)
        assert "useWebRefresh" in source
        assert "setRefreshing" in source, f"{path} belum punya background refresh state"
        assert "initial" in source.lower() or state_name in source


def test_trend_chart_has_pointer_tooltip_crosshair_and_readable_axes():
    chart = read("components/TrendChart.tsx")
    css = read("radmon.css")
    assert "onPointerMove" in chart
    assert "onPointerLeave" in chart
    assert "trend-chart-tooltip" in chart
    assert "trend-chart-crosshair" in chart
    assert "trend-chart-y-label" in chart
    assert "pointer-events" in css


def test_mobile_dialogs_are_marked_for_sheet_treatment():
    actions = read("Actions.tsx")
    assert actions.count('className="radmon-dialog mobile-sheet-dialog"') >= 2
