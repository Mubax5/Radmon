from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operator_surface_is_exe_oriented_and_legacy_launchers_are_removed():
    assert (ROOT / "radmon/__main__.py").is_file()
    assert (ROOT / "radmon/production_app.py").is_file()
    assert (ROOT / "radmon/dev_app.py").is_file()
    assert not list(ROOT.glob("*.bat"))
    for removed in (
        "main.py",
        "central_server.py",
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


def test_readme_documents_monitoring_schema_and_operator_outputs():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "5202", "IS-1 Koridor", "2 detik", "measurement", "alarm", "Grafana", "Playlist", "10 detik", "Preview", "Print", "Export PDF", "server pusat",
    ):
        assert phrase.lower() in text.lower(), phrase
    assert "schema_extension.sql" not in text


def test_repository_does_not_track_python_bytecode_artifacts():
    import subprocess
    tracked = subprocess.check_output(["git", "ls-files", "*.pyc"], cwd=ROOT, text=True).strip().splitlines()
    assert tracked == []
