from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_package_includes_iana_timezone_runtime_dependency():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "tzdata" in requirements
    assert not list(ROOT.glob("*.bat"))
    production = (ROOT / "radmon/production_app.py").read_text(encoding="utf-8")
    assert "Settings.from_env" in production
