from pathlib import Path

from radmon.grafana_tv import build_dashboard_payloads

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_windows_production_launch_is_exe_package_only():
    assert not list(ROOT.glob("*.bat"))
    assert not (ROOT / "main.py").exists()
    assert not (ROOT / "central_server.py").exists()
    package_main = read("radmon/__main__.py")
    assert "production_app" in package_main


def test_production_supervisor_is_single_process_owner():
    source = read("radmon/production_app.py")
    assert "SingleInstanceLock" in source
    assert "CentralService" in source
    assert "run_admin_ui" in source
    assert "central.start()" in source
    assert "central.stop()" in source


def test_runtime_collision_is_prevented_by_single_instance_lock():
    source = read("radmon/production_app.py")
    assert "SingleInstanceLock" in source
    assert "sudah berjalan" in source


def test_refresh_interval_is_two_seconds_everywhere_live():
    assert "RADMON_REFRESH_INTERVAL=2" in read(".env.example")
    assert "self.refresh_timer.start(2000)" in read("radmon/admin/main_window.py")
    for dashboard in build_dashboard_payloads():
        assert dashboard["refresh"] == "2s"
        assert "2s" in dashboard["timepicker"]["refresh_intervals"]
