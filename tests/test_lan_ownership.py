from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_lan_mode_does_not_construct_a_lan_collector():
    source = (ROOT / "radmon" / "desktop_app.py").read_text(encoding="utf-8")
    assert "LanRuntime(" not in source
    assert "ApplicationRuntime(" not in source


def test_static_station_catalog_is_not_seeded_in_lan_desktop_mode():
    desktop = (ROOT / "radmon" / "desktop_app.py").read_text(encoding="utf-8")
    production = (ROOT / "radmon" / "production_app.py").read_text(encoding="utf-8")
    developer = (ROOT / "radmon" / "dev_app.py").read_text(encoding="utf-8")
    assert "ensure_station_catalog()" not in desktop
    assert "ensure_station_catalog()" not in production
    assert "repository.ensure_station_catalog()" in developer


def test_production_supervisor_starts_central_before_admin_view():
    source = (ROOT / "radmon" / "production_app.py").read_text(encoding="utf-8")
    assert "CentralService(" in source
    assert "central.start()" in source
    assert "run_admin_ui(" in source
    assert source.index("central.start()") < source.index("run_admin_ui(")


def test_production_supervisor_stops_central_after_admin_view_exits():
    source = (ROOT / "radmon" / "production_app.py").read_text(encoding="utf-8")
    finally_block = source.split("finally:", 1)[1]
    assert "central.stop()" in finally_block
