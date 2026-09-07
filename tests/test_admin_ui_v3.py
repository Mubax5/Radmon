from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_shell_uses_silk_icons_for_tabs_and_toolbar():
    source = read("radmon/admin/main_window.py")
    for tab in ("clock", "table", "chart_line", "report", "lock", "page_white_text"):
        assert f'silk_icon("{tab}")' in source
    assert "QToolBar" in source
    assert "menuBar()" in source
    assert "File" in source and "View" in source and "Tools" in source and "Help" in source
    assert 'silk_icon("feed")' in source
    assert 'silk_icon("monitor")' in source
    assert 'silk_icon("arrow_refresh")' in source
    assert 'silk_icon("printer")' in source


def test_icon_loader_has_attribution_and_no_emoji_icon_literals():
    loader = read("radmon/admin/icons.py")
    assert "QIcon" in loader and "silk_path" in loader
    license_text = read("radmon/admin/icons/silk/LICENSE.txt")
    assert "Mark James" in license_text
    assert "Creative Commons Attribution 2.5" in license_text
    source = read("radmon/admin/main_window.py")
    for token in ("📊", "🖨", "🔒", "📋", "⏱", "⚠️"):
        assert token not in source


def test_vendored_tab_and_toolbar_icons_are_native_sixteen_pixel_pngs():
    import struct

    for name in (
        "clock", "table", "chart_line", "report", "lock", "page_white_text",
        "feed", "monitor", "arrow_refresh", "printer", "door_out", "help",
    ):
        payload = (ROOT / f"radmon/admin/icons/silk/{name}.png").read_bytes()
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", payload[16:24])
        assert (width, height) == (16, 16)


def test_file_and_help_actions_use_real_icons_too():
    source = read("radmon/admin/main_window.py")
    assert 'silk_icon("door_out")' in source
    assert 'silk_icon("help")' in source
