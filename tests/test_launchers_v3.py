from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_developer_cli_keeps_detector_and_dummy_out_of_production_entrypoint():
    dev = (ROOT / "radmon/dev_app.py").read_text(encoding="utf-8")
    parser_body = dev.split("def parser", 1)[1].split("def run_developer_mode", 1)[0]
    assert 'choices=("detector", "dummy")' in parser_body
    assert '"lan"' not in parser_body
    assert "SingleInstanceLock" in dev


def test_production_entrypoint_is_not_mode_selectable():
    production = (ROOT / "radmon/production_app.py").read_text(encoding="utf-8")
    package_main = (ROOT / "radmon/__main__.py").read_text(encoding="utf-8")
    assert "--source" not in production
    assert "from .production_app import main" in package_main
    assert not list(ROOT.glob("*.bat"))
