from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_lan_forces_central_lan_collection_for_this_launcher():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    assert "set RADMON_LAN_ENABLED=1" in text
    assert text.index("set RADMON_LAN_ENABLED=1") < text.index("central_server.py")
