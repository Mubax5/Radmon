from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operator_surface_is_small_and_has_single_python_entrypoint():
    assert (ROOT / "RADMON.bat").is_file()
    assert (ROOT / "RUN_DUMMY.bat").is_file()
    assert (ROOT / "main.py").is_file()
    for removed in ("admin_app.py", "public_app.py", "sync_agent.py", "dummy_measurement.py", "START_COMMON.bat", "STOP_ALL.bat", "SETUP_WINDOWS.bat"):
        assert not (ROOT / removed).exists(), removed


def test_requirements_cover_python_ui_backend_database_and_reporting():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for package in ("pyserial", "mariadb", "pyside6", "fastapi", "uvicorn", "jinja2", "httpx", "reportlab", "python-dotenv"):
        assert package in text


def test_readme_documents_two_click_workflows_and_user_schema_only():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in ("RADMON.bat", "RUN_DUMMY.bat", "5202", "IS-1 Koridor", "2 detik", "measurement", "recent", "alarm", "applog", "rawdata", "Export PDF", "server pusat"):
        assert phrase.lower() in text.lower(), phrase
    assert "schema_extension.sql" not in text


def test_repository_does_not_track_python_bytecode_artifacts():
    import subprocess
    tracked = subprocess.check_output(["git", "ls-files", "*.pyc"], cwd=ROOT, text=True).strip().splitlines()
    assert tracked == []
