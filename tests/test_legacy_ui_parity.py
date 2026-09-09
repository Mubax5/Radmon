from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_period_presets_calendar_boundaries():
    from radmon.admin.period_dialog import period_preset

    now = datetime(2026, 9, 9, 14, 30, 15)
    assert period_preset("Today", now) == (
        datetime(2026, 9, 9, 0, 0, 0),
        datetime(2026, 9, 9, 14, 30, 15),
    )
    assert period_preset("Yesterday", now) == (
        datetime(2026, 9, 8, 0, 0, 0),
        datetime(2026, 9, 9, 0, 0, 0),
    )
    assert period_preset("Last 7 days", now) == (
        datetime(2026, 9, 3, 0, 0, 0),
        datetime(2026, 9, 9, 14, 30, 15),
    )
    assert period_preset("This month", now) == (
        datetime(2026, 9, 1, 0, 0, 0),
        datetime(2026, 9, 9, 14, 30, 15),
    )
    assert period_preset("Last month", now) == (
        datetime(2026, 8, 1, 0, 0, 0),
        datetime(2026, 9, 1, 0, 0, 0),
    )
    assert period_preset("This year", now) == (
        datetime(2026, 1, 1, 0, 0, 0),
        datetime(2026, 9, 9, 14, 30, 15),
    )
    assert period_preset("Last year", now) == (
        datetime(2025, 1, 1, 0, 0, 0),
        datetime(2026, 1, 1, 0, 0, 0),
    )
    with pytest.raises(ValueError):
        period_preset("not-a-period", now)


def test_preferences_module_has_no_secret_fields():
    source = read("radmon/admin/ui_preferences.py").lower()
    for forbidden in ("db_password", "central_token", "pin_hash", "password_hash"):
        assert forbidden not in source
    assert "qsettings" in source
    for field in (
        "refresh_interval", "date_format", "datetime_format", "dose_rate_format",
        "dose_format", "threshold_format", "warning_color", "alarm_color",
        "csv_delimiter", "report_dir", "institution", "institution_address",
        "server_uri", "api_path", "api_version", "uri_datetime_format",
    ):
        assert field in source


def test_message_panel_belongs_to_recent_only():
    recent = read("radmon/admin/recent_page.py")
    assert 'setObjectName("recentMessageTable")' in recent
    assert '"Date/Time", "Message"' in recent
    for path in (
        "radmon/admin/tabular_page.py",
        "radmon/admin/chart_page.py",
        "radmon/admin/reports_page.py",
        "radmon/admin/alarm_page.py",
        "radmon/admin/logs_page.py",
    ):
        assert "recentMessageTable" not in read(path)
    security = read("radmon/secure_context.py")
    assert "QDockWidget" not in security
    assert "set_message_rows" in security


def test_recent_page_has_legacy_overview_columns():
    source = read("radmon/admin/recent_page.py")
    for label in (
        "Station",
        "Measurement Time",
        "Dose Rate [µSv/h]",
        "Avg. Dose Rate [µSv/h]",
        "Approx. Dose [µSv]",
        "Low Threshold",
        "High Threshold",
        "Alarm",
    ):
        assert label in source


def test_about_credits_creator_and_links():
    source = read("radmon/admin/about_dialog.py")
    assert "Hilmi Mubarok" in source
    assert "https://github.com/Mubax5" in source
    assert "https://mubacs.site" in source
    assert "QDesktopServices" in source


def test_station_properties_and_alarm_legacy_fields_present():
    station = read("radmon/admin/station_admin_dialog.py")
    for label in ("Attributes", "Alarm", "Hardware", "Audio path", "Type", "Address"):
        assert label in station
    alarm = read("radmon/admin/alarm_page.py")
    for label in (
        "Tag", "Event time", "Threshold", "Dose rate", "Hit count",
        "Action Time", "PIC", "Action", "Note",
    ):
        assert label in alarm


def test_legacy_menu_actions_present():
    source = read("radmon/admin/main_window.py")
    for label in (
        "Save As...", "Save As CSV...", "Printer Setup...", "Print Preview...", "Print...",
        "Recent Values", "Tabular View", "Chart Display", "Reports", "Alarm", "Log", "Refresh",
        "Options...", "Test Server...", "Test Hardware...", "Acquisition Control...",
        "Installation Manual...", "User Manual...", "About...",
    ):
        assert label in source
    for attr in ("recent_page", "tabular_page", "chart_page", "reports_page", "alarm_page", "logs_page"):
        assert f"self.{attr}" in source


def test_server_probe_is_read_only_health_get():
    source = read("radmon/admin/diagnostics_dialogs.py").lower()
    assert "server_health_lines" in source
    assert "urlopen" in source
    assert ".write(" not in source
    assert "health" in source


def test_hardware_probe_never_writes_serial():
    from radmon.admin.diagnostics_dialogs import hardware_test_lines

    calls: list[str] = []

    class FakeSerial:
        def __init__(self, **kwargs):
            calls.append(f"open:{kwargs.get('port')}")
            self.port = kwargs.get("port")

        def readline(self):
            calls.append(f"read:{self.port}")
            return b""

        def write(self, *_args, **_kwargs):
            raise AssertionError("hardware test must never write")

        def close(self):
            calls.append(f"close:{self.port}")

    lines = hardware_test_lines(
        [(5201, "COM3")],
        2400,
        0.01,
        serial_factory=FakeSerial,
    )
    assert any("COM3" in line for line in lines)
    assert calls == ["open:COM3", "read:COM3", "close:COM3"]


def test_lan_acquisition_dialog_never_owns_collector():
    source = read("radmon/admin/acquisition_dialog.py")
    assert "central_server.py" in source
    assert "LAN" in source
    assert "LanRuntime(" not in source


def test_period_hooks_exist_on_tabular_and_reports():
    assert "select_period" in read("radmon/admin/tabular_page.py")
    assert "select_period" in read("radmon/admin/reports_page.py")
