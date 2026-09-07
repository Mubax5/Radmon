from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_two_launchers_bootstrap_pyqtgraph_and_start_grafana_headlessly():
    for name, source_mode in (("RADMON.bat", "detector"), ("RUN_DUMMY.bat", "dummy")):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "pyqtgraph" in text
        assert "docker compose" in text
        assert "up -d" in text
        assert f"--source {source_mode}" in text
        assert "pythonw.exe" in text
        assert "cmd /k" not in text
