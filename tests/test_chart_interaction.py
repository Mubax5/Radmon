from datetime import datetime, timedelta
from pathlib import Path

from radmon.admin.chart_state import ChartViewport

ROOT = Path(__file__).resolve().parents[1]


def test_manual_viewport_is_preserved_during_refresh():
    start = datetime(2026, 9, 7, 10, 0, 0)
    end = start + timedelta(hours=1)
    viewport = ChartViewport(live=False)
    viewport.capture(start.timestamp(), end.timestamp())
    new_end = end + timedelta(minutes=15)
    assert viewport.range_for_refresh(new_end.timestamp()) == (start.timestamp(), end.timestamp())


def test_live_viewport_follows_latest_with_same_window_width():
    start = datetime(2026, 9, 7, 10, 0, 0)
    end = start + timedelta(hours=1)
    viewport = ChartViewport(live=True)
    viewport.capture(start.timestamp(), end.timestamp())
    latest = (end + timedelta(minutes=10)).timestamp()
    assert viewport.range_for_refresh(latest) == (latest - 3600, latest)


def test_chart_page_uses_pyqtgraph_crosshair_dual_axes_and_threshold_lines():
    source = (ROOT / "radmon/admin/chart_page.py").read_text(encoding="utf-8")
    assert "import pyqtgraph as pg" in source
    assert "sigMouseMoved" in source
    assert "sigRangeChangedManually" in source
    assert "_manual_range_changed" in source
    assert "InfiniteLine" in source
    assert "showAxis(\"right\")" in source
    assert "setXLink" in source
    assert "Alert threshold" in source
    assert "Alarm threshold" in source
    assert "live_window_seconds" in source
    assert "self.start.setDateTime(now.addSecs(-self.live_window_seconds))" in source
    assert "enableAutoRange" not in source.split("def refresh_live", 1)[1]
