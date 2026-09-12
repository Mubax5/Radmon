from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source() -> str:
    return (ROOT / "radmon/production_app.py").read_text(encoding="utf-8")


def test_production_supervisor_owns_central_service_and_admin_view():
    text = source()
    assert "central_factory: Callable[..., Any] = CentralService" in text
    assert "central = central_factory(" in text
    assert "run_admin_ui" in text
    assert text.index("central.start()") < text.index("desktop_runner(")


def test_production_supervisor_enables_lan_collection():
    text = source()
    assert "lan_enabled=True" in text
    assert "central_factory(settings" in text


def test_production_supervisor_recovers_only_verified_legacy_central():
    text = source()
    assert "is_legacy_radmon_central" in text
    assert "stop_legacy_radmon_central" in text
    ownership = (ROOT / "radmon/process_ownership.py").read_text(encoding="utf-8")
    assert "central_server\\.py" in ownership


def test_admin_exit_stops_central_and_releases_single_instance_lock():
    text = source()
    finally_block = text.split("finally:", 1)[1]
    assert "central.stop()" in finally_block
    assert "lock.release()" in finally_block


def test_unrelated_port_owner_is_never_force_killed():
    text = source()
    assert "find_listener_owner" in text
    assert "Port 8090 dipakai proses lain" in text
    ownership = (ROOT / "radmon/process_ownership.py").read_text(encoding="utf-8")
    assert "bukan legacy RadMon" in ownership
