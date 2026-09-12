from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_lan_forces_central_lan_collection_for_this_launcher():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    assert "set RADMON_LAN_ENABLED=1" in text
    assert text.index("set RADMON_LAN_ENABLED=1") < text.index("central_server.py")


def test_run_lan_reuses_only_verified_radmon_lan_central():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    central = text.split(":central", 1)[1]
    assert ":central_ready" in text
    assert "http://127.0.0.1:8090/health" in text
    assert "radmon-central" in text
    assert "lan_enabled" in text
    assert "call :central_ready" in central
    assert "call :port_open" in central
    assert "Port 8090" in central


def test_run_lan_waits_for_verified_central_before_admin_launch():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    admin_launch = 'start "" /wait "%~dp0.venv\\Scripts\\pythonw.exe" "%~dp0main.py" --source lan'
    assert text.index("call :central || exit /b 1") < text.index(admin_launch)
    wait_section = text.split("for /L %%I in (1,1,30) do (", 1)[1]
    assert "call :central_ready" in wait_section


def test_run_lan_waits_for_admin_exit_then_stops_central():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    admin_launch = 'start "" /wait "%~dp0.venv\\Scripts\\pythonw.exe" "%~dp0main.py" --source lan'
    assert admin_launch in text
    admin = text.index('main.py" --source lan')
    tail = text[admin:]
    assert "call :stop_central" in tail
    assert "\n:stop_central\n" in text
    assert "Stop-Process" in text


def test_verified_existing_central_is_adopted_for_shutdown():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    start = text.index("\n:central\n")
    end = text.index("\n:capture_central_pid\n")
    central = text[start:end]
    assert "call :central_ready" in central
    assert "call :capture_central_pid" in central
    assert "Get-NetTCPConnection" in text


def test_unhealthy_port_recovers_only_stale_radmon_central():
    text = (ROOT / "RUN_LAN.bat").read_text(encoding="utf-8")
    assert "call :recover_stale_central" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "central_server\\.py" in text
