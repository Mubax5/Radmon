from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from radmon.config import Settings


def test_archive_defaults_match_pc3_calendar_lifecycle():
    settings = Settings()
    assert settings.central_host == "192.168.1.2"
    assert settings.archive_enabled is True
    assert settings.archive_dir == Path("archives")
    assert settings.archive_timezone == "Asia/Jakarta"
    assert settings.archive_min_retention_years == 5
    assert settings.archive_check_interval == 60.0
    ZoneInfo(settings.archive_timezone)


def test_archive_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("RADMON_CENTRAL_HOST", "192.168.1.2")
    monkeypatch.setenv("RADMON_ARCHIVE_ENABLED", "0")
    monkeypatch.setenv("RADMON_ARCHIVE_DIR", "D:/radmon-archive")
    monkeypatch.setenv("RADMON_ARCHIVE_TIMEZONE", "Asia/Jakarta")
    monkeypatch.setenv("RADMON_ARCHIVE_MIN_RETENTION_YEARS", "7")
    monkeypatch.setenv("RADMON_ARCHIVE_CHECK_INTERVAL", "90")
    settings = Settings.from_env(env_file=None)
    assert settings.archive_enabled is False
    assert settings.archive_dir == Path("D:/radmon-archive")
    assert settings.archive_min_retention_years == 7
    assert settings.archive_check_interval == 90.0


def test_archive_retention_cannot_be_configured_below_five_years(monkeypatch):
    monkeypatch.setenv("RADMON_ARCHIVE_MIN_RETENTION_YEARS", "4")
    with pytest.raises(ValueError, match="minimal 5 tahun"):
        Settings.from_env(env_file=None)


def test_archive_timezone_is_validated(monkeypatch):
    monkeypatch.setenv("RADMON_ARCHIVE_TIMEZONE", "Not/AZone")
    with pytest.raises(ValueError, match="timezone archive"):
        Settings.from_env(env_file=None)
