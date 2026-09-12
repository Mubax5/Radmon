from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_managed_central_service_owns_archive_catalog_lifecycle_and_api_wiring():
    source = (ROOT / "radmon" / "central_service.py").read_text(encoding="utf-8")
    assert "ArchiveCatalog" in source
    assert "QuarterArchiveService" in source
    assert "CentralArchiveStore" in source
    assert ".reconcile()" in source
    assert "archive_catalog=archive_catalog" in source
    assert "archive_service=archive_service" in source
    assert "archive_service=archive_service" in source.split("LanRuntime", 2)[-1]


def test_legacy_central_server_launcher_is_removed_and_supervisor_uses_managed_service():
    assert not (ROOT / "central_server.py").exists()
    source = (ROOT / "radmon" / "production_app.py").read_text(encoding="utf-8")
    assert "from .central_service import CentralService" in source
    assert "central_factory" in source
    assert "central.start()" in source
    assert "central.stop()" in source
