from datetime import datetime, timedelta
import pytest
from radmon.detector import parse_detector_line
from radmon.status import MonitorStatus, classify_status
from radmon.config import Settings


def test_detector_parser_matches_existing_first_seven_character_protocol():
    assert parse_detector_line("0.12345 extra") == pytest.approx(0.12345)
    assert parse_detector_line("10.5000 alarm") == pytest.approx(10.5)


@pytest.mark.parametrize("raw", ["", "abc", "-0.1234", "nan", "inf", "-inf"])
def test_detector_parser_rejects_invalid_values(raw: str):
    with pytest.raises(ValueError): parse_detector_line(raw)


def test_status_alarm_alert_normal_offline():
    now = datetime(2026, 9, 7, 10, 0, 0)
    assert classify_status(10.5, now, now, 8, 10, 5) is MonitorStatus.ALARM
    assert classify_status(8.5, now, now, 8, 10, 5) is MonitorStatus.ALERT
    assert classify_status(0.2, now, now, 8, 10, 5) is MonitorStatus.NORMAL
    assert classify_status(0.2, now - timedelta(minutes=6), now, 8, 10, 5) is MonitorStatus.OFFLINE
    assert classify_status(None, None, now, 8, 10, 5) is MonitorStatus.OFFLINE


def test_settings_defaults_match_demo(monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith('RADMON_'): monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.serial_port == "COM15" and settings.baudrate == 2400 and settings.serid == 5202
    assert settings.building == "52" and settings.room == "IS-1 Koridor" and settings.sample_interval == 2.0
    assert settings.warnlevel == 8.0 and settings.alarmlevel == 10.0
