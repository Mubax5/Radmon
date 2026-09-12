from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_build_contract_exists():
    spec = (ROOT / "RadMon.spec").read_text(encoding="utf-8")
    entry = (ROOT / "packaging/radmon_entry.py").read_text(encoding="utf-8")
    build_requirements = (ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()

    assert "radmon_entry.py" in spec
    assert "name='RadMon'" in spec or 'name="RadMon"' in spec
    assert "console=False" in spec
    assert "radmon/admin/icons" in spec.replace("\\", "/")
    assert "from radmon.production_app import main" in entry
    assert "pyinstaller" in build_requirements


def test_windows_workflow_builds_smokes_and_uploads_portable_exe():
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    normalized = workflow.replace("/", "\\").lower()

    assert "windows-latest" in workflow
    assert "requirements-build.txt" in workflow
    assert "RadMon.spec" in workflow
    assert "RadMon\\app\\RadMon.exe".lower() in normalized
    assert "--smoke-test" in workflow
    assert "RadMon-Windows" in workflow
    assert "actions/upload-artifact" in workflow


def test_portable_layout_keeps_configuration_external_and_assets_beside_exe():
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    normalized = workflow.replace("/", "\\")

    assert "RadMon\\config\\.env.example" in normalized
    assert "RadMon\\app\\docs\\manual" in normalized
    assert "RadMon\\app\\grafana" in normalized
    assert "Copy-Item .env " not in workflow
