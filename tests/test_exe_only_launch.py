from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_repo_has_no_batch_or_legacy_root_launchers():
    assert list(ROOT.glob("*.bat")) == []
    assert not (ROOT / "main.py").exists()
    assert not (ROOT / "central_server.py").exists()


def test_package_main_is_the_only_production_entrypoint():
    package_main = (ROOT / "radmon/__main__.py").read_text(encoding="utf-8")
    assert "from .production_app import main" in package_main
    assert "raise SystemExit(main())" in package_main


def test_detector_and_dummy_modes_are_developer_only():
    dev_app = (ROOT / "radmon/dev_app.py").read_text(encoding="utf-8")
    assert 'choices=("detector", "dummy")' in dev_app
    assert '"lan"' not in dev_app.split("def parser", 1)[1].split("def ", 1)[0]
    assert "SingleInstanceLock" in dev_app
