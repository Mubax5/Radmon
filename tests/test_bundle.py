from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operator_surface_is_small_and_has_single_python_entrypoint():
    assert (ROOT / "RADMON.bat").is_file()
    assert (ROOT / "RUN_DUMMY.bat").is_file()
    assert (ROOT / "main.py").is_file()
    for removed in (
        "admin_app.py",
        "public_app.py",
        "sync_agent.py",
        "dummy_measurement.py",
        "START_COMMON.bat",
        "STOP_ALL.bat",
        "SETUP_WINDOWS.bat",
    ):
        assert not (ROOT / removed).exists(), removed


def test_requirements_cover_admin_chart_backend_database_and_reporting():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for package in (
        "pyserial", "mariadb", "pyside6", "pyqtgraph", "fastapi", "uvicorn", "httpx", "reportlab", "python-dotenv",
    ):
        assert package in text
    assert "jinja2" not in text


def test_grafana_assets_are_part_of_the_bundle():
    for path in (
        "grafana/docker-compose.yml",
        "grafana/provisioning/datasources/ipradmon.yaml",
        "radmon/grafana_tv.py",
    ):
        assert (ROOT / path).is_file(), path
    assert not (ROOT / "grafana/dashboards/radiation-monitoring.json").exists()
    assert not (ROOT / "grafana/provisioning/dashboards/radmon.yaml").exists()


def test_readme_documents_two_click_workflows_user_schema_grafana_playlist_and_preview():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "RADMON.bat", "RUN_DUMMY.bat", "5202", "IS-1 Koridor", "2 detik", "measurement", "alarm", "Grafana", "Playlist", "10 detik", "Preview", "Print", "Export PDF", "server pusat",
    ):
        assert phrase.lower() in text.lower(), phrase
    assert "schema_extension.sql" not in text


def test_repository_does_not_track_python_bytecode_artifacts():
    import subprocess
    tracked = subprocess.check_output(["git", "ls-files", "*.pyc"], cwd=ROOT, text=True).strip().splitlines()
    assert tracked == []
