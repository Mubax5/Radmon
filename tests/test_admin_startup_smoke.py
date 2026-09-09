from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from radmon.admin.main_window import MainWindow
from radmon.config import Settings
from radmon.models import LatestReading, StationConfig
from radmon.reports import ReportService
from radmon.secure_context import set_context


class FakeRepo:
    def __init__(self) -> None:
        self.station = StationConfig(
            5202,
            "52",
            "IS-1 Koridor",
            "Gd.52",
            8.0,
            10.0,
            30,
            "µSv/h",
        )

    def station_configs(self):
        return [self.station]

    def station_config(self, serid=None):
        return self.station

    def latest_reading(self, serid=None):
        return LatestReading(station=self.station, measured_at=None, dose_rate=None)

    def measurement_history(self, start, end, *, serid=None, limit=5000):
        return []

    def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
        return []


def app():
    return QApplication.instance() or QApplication([])


def test_main_window_can_construct_after_login_without_monitoring_timer_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    app()
    set_context(None)
    settings = Settings().for_dummy()
    repository = FakeRepo()
    report_service = ReportService(repository, settings)
    monkeypatch.setattr(MainWindow, "_start_grafana_bootstrap", lambda self: None)

    try:
        window = MainWindow(
            repository,
            report_service,
            object(),
            settings,
            tmp_path / "radmon.log",
            source="dummy",
        )
    finally:
        set_context(None)

    assert hasattr(window, "_monitoring_poll_timer")
    window.close()
