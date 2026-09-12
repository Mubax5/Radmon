from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source() -> str:
    return (ROOT / "radmon/production_app.py").read_text(encoding="utf-8")


def test_production_supervisor_owns_central_service_and_admin_view():
    text = source()
    assert "CentralService(" in text
    assert "run_admin_ui(" in text
    assert text.index("central.start()") < text.index("run_admin_ui(")


def test_production_supervisor_enables_lan_collection():
    text = source()
    assert "lan_enabled=True" in text
    assert "CentralService(settings" in text


def test_production_supervisor_recovers_only_verified_legacy_central():
    text = source()
    assert "recover_stale_radmon_central" in text
    ownership = (ROOT / "radmon/process_ownership.py").read_text(encoding="utf-8")
    assert "is_legacy_radmon_central" in ownership
    assert "central_server\\.py" in ownership


def test_admin_exit_stops_central_and_releases_single_instance_lock():
    text = source()
    finally_block = text.split("finally:", 1)[1]
    assert "central.stop()" in finally_block
    assert "lock.release()" in finally_block


def test_unrelated_port_owner_is_never_force_killed():
    text = source()
    assert "find_listener_owner" in text
    ownership = (ROOT / "radmon/process_ownership.py").read_text(encoding="utf-8")
    assert "bukan legacy RadMon" in ownership
