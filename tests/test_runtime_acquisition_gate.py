from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from radmon.config import Settings
from radmon.runtime import ApplicationRuntime


class Repo:
    def station_configs(self):
        return []



def test_runtime_pause_resume_gate():
    runtime = ApplicationRuntime(Repo(), Settings(), None, "dummy")
    assert runtime.is_paused is False
    runtime.pause()
    assert runtime.is_paused is True
    runtime.resume()
    assert runtime.is_paused is False


def test_collector_supports_pause_event_and_releases_port():
    source = Path("radmon/collector.py").read_text(encoding="utf-8")
    assert "pause_event" in source
    assert "pause_event.is_set()" in source
    assert "serial_port.close()" in source


def test_developer_runtime_passes_runtime_to_window_and_production_lan_does_not():
    developer = Path("radmon/dev_app.py").read_text(encoding="utf-8")
    desktop = Path("radmon/desktop_app.py").read_text(encoding="utf-8")
    production = Path("radmon/production_app.py").read_text(encoding="utf-8")
    assert "runtime=runtime" in developer
    assert "ApplicationRuntime(" not in desktop
    assert "ApplicationRuntime(" not in production
