from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_shell_uses_distinct_semantic_icons_for_tabs_toolbar_and_tools():
    source = read("radmon/admin/main_window.py")
    for slot in (
        "monitoring", "station_group", "detector", "recent", "tabular", "chart",
        "reports", "alarm", "logs", "refresh", "server_test", "hardware_test",
        "acquisition", "installation_manual", "user_manual", "exit", "save_as",
        "save_csv", "printer_setup", "print_preview", "print", "select_period",
        "new_station", "application_options", "about",
    ):
        assert f'app_icon("{slot}")' in source
    assert "silk_icon(" not in source
    assert "QToolBar" in source
    assert "menuBar()" in source
    assert "File" in source and "View" in source and "Tools" in source and "Help" in source


def test_security_context_uses_specific_semantic_icons():
    source = read("radmon/secure_context.py")
    assert 'app_icon("station_properties")' in source
    assert 'app_icon("users")' in source
    assert 'app_icon("exit")' in source
    assert "silk_icon(" not in source


def test_tabler_loader_has_attribution_and_no_emoji_icon_literals():
    loader = read("radmon/admin/icons.py")
    assert "QIcon" in loader and "app_icon" in loader and "ICON_SLOTS" in loader
    license_text = read("radmon/admin/icons/tabler/LICENSE.txt")
    assert "MIT License" in license_text
    assert "Paweł Kuna" in license_text
    sources = "\n".join(
        read(path)
        for path in (
            "radmon/admin/main_window.py",
            "radmon/secure_context.py",
            "radmon/admin/alarm_page.py",
        )
    )
    for token in ("📊", "🖨", "🔒", "📋", "⏱", "⚠️"):
        assert token not in sources


def test_visible_admin_dialogs_do_not_use_silk_icons():
    for path in (
        "radmon/admin/auth_dialogs.py",
        "radmon/admin/alarm_response_dialog.py",
        "radmon/admin/alarm_page.py",
        "radmon/admin/station_admin_dialog.py",
        "radmon/admin/user_admin_dialog.py",
    ):
        assert "silk_icon(" not in read(path), path


def test_semantic_icon_behavior_is_owned_by_canonical_modules():
    init_source = read("radmon/__init__.py")
    main_source = read("radmon/admin/main_window.py")
    context_source = read("radmon/secure_context.py")
    assert "icon_system_revision" not in init_source
    assert not (ROOT / "radmon/icon_system_revision.py").exists()
    assert 'app_icon("station_group")' in main_source
    assert 'app_icon("detector")' in main_source
    assert 'app_icon("station_properties")' in context_source
