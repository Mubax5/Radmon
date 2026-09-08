from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_lan_mode_does_not_construct_a_lan_collector():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from radmon.lan_runtime import LanRuntime" not in source
    assert "LanRuntime(settings, secure" not in source


def test_static_station_catalog_is_not_seeded_in_lan_central_mode():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'if args.source != "lan":' in source
    guarded = source.split('if args.source != "lan":', 1)[1].split("station =", 1)[0]
    assert "ensure_station_catalog()" in guarded


def test_run_lan_starts_central_server_and_then_admin_view():
    source = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    assert "central_server.py" in source
    assert "main.py\" --source lan" in source
    server_position = source.index("central_server.py")
    admin_position = source.index("main.py")
    assert server_position < admin_position
