import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_only_two_operator_launchers_exist():
    assert sorted(path.name for path in ROOT.glob("*.bat")) == ["RADMON.bat", "RUN_DUMMY.bat"]
    assert not list((ROOT / "scripts").glob("*.bat"))


def test_launchers_self_bootstrap_without_spawning_service_consoles():
    for name, source_mode in (("RADMON.bat", "detector"), ("RUN_DUMMY.bat", "dummy")):
        text = read(name).lower()
        assert ".venv" in text
        assert "requirements.txt" in text
        assert ".env.example" in text
        assert "pythonw.exe" in text
        assert "main.py" in text
        assert f"--source {source_mode}" in text
        assert "cmd /k" not in text
        assert "taskkill" not in text


def test_runtime_collision_is_prevented_by_single_instance_lock():
    source = read("main.py")
    assert "SingleInstanceLock" in source
    assert "sudah berjalan" in source


def test_refresh_interval_is_two_seconds_everywhere_live():
    assert "RADMON_REFRESH_INTERVAL=2" in read(".env.example")
    assert "self.refresh_timer.start(2000)" in read("radmon/admin/main_window.py")
    dashboard = json.loads(read("grafana/dashboards/radiation-monitoring.json"))
    assert dashboard["refresh"] == "2s"
    assert "2s" in dashboard["timepicker"]["refresh_intervals"]
