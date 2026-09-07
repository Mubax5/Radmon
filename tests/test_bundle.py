from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_windows_launchers_cover_all_entry_points():
    for name in ("collector","dummy","admin","public","sync","central"):
        path=ROOT/f"scripts/run_{name}.bat"
        assert path.is_file(), path
        assert "python" in path.read_text(encoding="utf-8").lower()


def test_requirements_cover_python_ui_backend_database_and_reporting():
    text=(ROOT/"requirements.txt").read_text(encoding="utf-8").lower()
    for package in ("pyserial","mariadb","pyside6","fastapi","uvicorn","jinja2","httpx","reportlab","python-dotenv"):
        assert package in text


def test_readme_documents_the_requested_demo_workflow():
    text=(ROOT/"README.md").read_text(encoding="utf-8")
    for phrase in ("5202","IS-1 Koridor","Gd.52","COM15","2400","dummy_measurement.py --mode normal --interval 2","Recent / Tabular / Chart / Reports / Alarm / Logs","public_app.py","sync_agent.py","central_server.py","database/schema_extension.sql","register_demo_station.py","Export PDF","server pusat"):
        assert phrase in text, phrase


def test_original_user_collector_is_preserved_as_reference():
    source=(ROOT/"reference/original_user_main.py").read_text(encoding="utf-8")
    assert 'port="COM15"' in source
    assert 'serid = 5201' in source
    assert 'INSERT INTO measurement' in source


def test_project_has_expected_python_entry_points():
    for name in ("main.py","dummy_measurement.py","admin_app.py","public_app.py","sync_agent.py","central_server.py"):
        assert (ROOT/name).is_file()


def test_repository_does_not_track_python_bytecode_artifacts():
    tracked = subprocess.check_output(['git','ls-files','*.pyc'], cwd=ROOT, text=True).strip().splitlines()
    assert tracked == []
