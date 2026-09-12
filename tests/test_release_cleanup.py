from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ACTIVE_DOCS = (
    "README.md",
    "docs/INSTALLATION.md",
    "docs/manual/installation.html",
    "docs/USER-MANUAL.md",
    "docs/manual/user-manual.html",
)

OBSOLETE_PLAN_DOCS = (
    "docs/2026-09-08-quarterly-archive-design.md",
    "docs/2026-09-08-quarterly-archive-implementation-plan.md",
    "docs/2026-09-09-legacy-desktop-ui-parity-design.md",
    "docs/2026-09-09-legacy-desktop-ui-parity-implementation-plan.md",
    "docs/2026-09-09-web-admin-grafana-manual-hosting-design.md",
    "docs/2026-09-10-production-integration-fix-design.md",
    "docs/2026-09-10-production-integration-fix-implementation-plan.md",
)


def test_active_docs_describe_exe_only_production_startup():
    for relative in ACTIVE_DOCS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for obsolete in ("RADMON.bat", "RUN_DUMMY.bat", "RUN_LAN.bat"):
            assert obsolete not in text, f"{relative} masih menyebut {obsolete}"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/INSTALLATION.md").read_text(encoding="utf-8")
    installation_html = (ROOT / "docs/manual/installation.html").read_text(encoding="utf-8")
    for text in (readme, installation, installation_html):
        assert "RadMon.exe" in text
        assert "config\\.env" in text or "config/.env" in text


def test_active_docs_do_not_tell_operator_to_run_legacy_central_launcher():
    for relative in ACTIVE_DOCS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "python central_server.py" not in text
        assert "central_server.py sebagai" not in text
        assert "central_server.py sebagai proses" not in text


def test_obsolete_internal_planning_docs_and_smoke_demo_are_removed():
    for relative in OBSOLETE_PLAN_DOCS:
        assert not (ROOT / relative).exists(), relative
    assert not (ROOT / "scripts/smoke_demo.py").exists()


def test_silk_compatibility_layer_and_assets_are_removed():
    icons_source = (ROOT / "radmon/admin/icons.py").read_text(encoding="utf-8")
    station_source = (ROOT / "radmon/admin/station_admin_dialog.py").read_text(encoding="utf-8")

    assert "_SILK_ROOT" not in icons_source
    assert "def silk_path" not in icons_source
    assert "def silk_icon" not in icons_source
    assert "silk_icon" not in station_source
    assert not (ROOT / "radmon/admin/icons/silk").exists()
