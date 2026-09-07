from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(name: str) -> str: return (ROOT / name).read_text(encoding="utf-8")
def executable_lines(text: str) -> str:
    lines=[]
    for raw in text.lower().splitlines():
        line=raw.strip()
        if not line or line.startswith(("echo ","rem ","::")): continue
        lines.append(line)
    return "\n".join(lines)

def test_top_level_windows_launchers_exist_for_setup_common_and_measurement_writers():
    for name in ("SETUP_WINDOWS.bat","START_COMMON.bat","RUN_DETECTOR.bat","RUN_DUMMY.bat","STOP_ALL.bat"): assert (ROOT/name).is_file(),name

def test_common_runner_starts_only_non_writer_services():
    text=read("START_COMMON.bat").lower(); commands=executable_lines(text)
    for service in ("scripts\\run_central.bat","scripts\\run_public.bat","scripts\\run_sync.bat","scripts\\run_admin.bat"): assert service in text,service
    for forbidden in ("main.py","dummy_measurement.py","run_collector.bat","run_dummy.bat","run_detector.bat"): assert forbidden not in commands,forbidden

def test_dummy_and_detector_have_separate_mutually_exclusive_launchers():
    dummy=read("RUN_DUMMY.bat").lower(); detector=read("RUN_DETECTOR.bat").lower(); dummy_commands=executable_lines(dummy); detector_commands=executable_lines(detector)
    assert "dummy_measurement.py" in dummy and "--interval 2" in dummy and "main.py" not in dummy_commands and "run_collector.bat" not in dummy_commands
    assert "main.py" in detector_commands and "dummy_measurement.py" not in detector_commands and "run_dummy.bat" not in detector_commands

def test_windows_setup_creates_venv_installs_requirements_and_preserves_env_file():
    text=read("SETUP_WINDOWS.bat").lower(); assert ".venv" in text and "requirements.txt" in text and ".env.example" in text and ".env" in text and "pip install" in text

def test_stop_runner_targets_only_radmon_windows_started_by_common_runner():
    text=read("STOP_ALL.bat").lower()
    for title in ("radmon central","radmon public","radmon sync","radmon admin","radmon detector","radmon dummy"): assert title in text
    assert "taskkill" in text

def test_windows_runbook_documents_safe_startup_modes_and_writer_collision_rule():
    runbook=(ROOT/"docs/WINDOWS_RUNBOOK.md").read_text(encoding="utf-8")
    for phrase in ("SETUP_WINDOWS.bat","START_COMMON.bat","RUN_DETECTOR.bat","RUN_DUMMY.bat","STOP_ALL.bat","5202","IS-1 Koridor","jangan menjalankan RUN_DETECTOR.bat dan RUN_DUMMY.bat bersamaan","http://127.0.0.1:8080","http://127.0.0.1:8090"): assert phrase.lower() in runbook.lower(),phrase

def test_windows_setup_uses_block_safe_errorlevel_checks():
    text=read("SETUP_WINDOWS.bat").lower(); assert "%errorlevel%" not in text and "if errorlevel 1" in text
