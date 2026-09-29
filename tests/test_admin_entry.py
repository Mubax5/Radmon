from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]


def test_admin_entry_attaches_without_owning_server_workers_or_grafana():
    source = (ROOT / "radmon/admin_entry.py").read_text(encoding="utf-8")
    assert "build_secure_services(settings)" in source
    assert "run_admin_ui(" in source
    assert "manage_grafana=False" in source
    assert "CentralService" not in source
    assert "SingleInstanceLock" not in source
    assert "LanRuntime" not in source
    assert "ApplicationRuntime" not in source
    assert "Collector" not in source


def test_admin_central_recovery_uses_server_launcher_contract():
    source = (ROOT / "radmon/admin_entry.py").read_text(encoding="utf-8")
    assert 'paths.app_dir / "RadMon.exe"' in source
    assert '[str(server_exe), "--start"]' in source
    assert "central_is_available()" in source


def test_admin_window_can_disable_grafana_bootstrap_for_attached_client():
    source = (ROOT / "radmon/admin/main_window.py").read_text(encoding="utf-8")
    assert "manage_grafana: bool = True" in source
    assert "if not self._manage_grafana:" in source


def test_admin_health_probe_rejects_non_radmon_http_listener():
    from radmon.admin_entry import central_is_available

    class OtherServiceHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), OtherServiceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert not central_is_available(port=server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_admin_recovery_invokes_server_start_at_most_once(tmp_path, monkeypatch):
    from radmon.admin_entry import _ensure_central
    from radmon.paths import ApplicationPaths

    paths = ApplicationPaths.discover(executable=tmp_path / "app" / "RadMon Admin.exe", frozen=True)
    paths.app_dir.mkdir(parents=True)
    (paths.app_dir / "RadMon.exe").touch()
    calls = []
    monkeypatch.setattr("radmon.admin_entry.central_is_available", lambda: bool(calls))
    monkeypatch.setattr("radmon.admin_entry.subprocess.Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("radmon.admin_entry.time.sleep", lambda _seconds: None)

    assert _ensure_central(paths, timeout=1)
    assert len(calls) == 1
    assert calls[0][0][0] == [str(paths.app_dir / "RadMon.exe"), "--start"]
    assert calls[0][1]["cwd"] == str(paths.app_dir)


def test_admin_smoke_test_checks_existing_central_without_starting_ui(monkeypatch):
    from radmon import admin_entry

    monkeypatch.setattr(admin_entry.sys, "argv", ["RadMon Admin.exe", "--smoke-test"])
    monkeypatch.setattr(admin_entry, "central_is_available", lambda: True)
    monkeypatch.setattr(admin_entry, "run_admin_client", lambda: (_ for _ in ()).throw(AssertionError("UI started")))

    assert admin_entry.main() == 0
