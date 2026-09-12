from pathlib import Path


def test_desktop_module_does_not_own_central_or_single_instance():
    path = Path("radmon/desktop_app.py")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "SingleInstanceLock(" not in text
    assert "LanRuntime(" not in text
    assert "ApplicationRuntime(" not in text
    assert "build_secure_services(" not in text


def test_desktop_module_consumes_existing_secure_services():
    path = Path("radmon/desktop_app.py")
    text = path.read_text(encoding="utf-8")
    assert "def run_admin_ui(" in text
    assert "services" in text
    assert 'source="lan"' in text
