from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_launchers_bootstrap_iana_timezone_data():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "tzdata" in requirements

    for runner in ("RADMON.bat", "RUN_DUMMY.bat", "RUN_LAN.bat"):
        source = (ROOT / runner).read_text(encoding="utf-8").lower()
        assert "tzdata" in source, f"{runner} must force-install tzdata into existing venvs"
