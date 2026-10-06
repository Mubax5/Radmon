from datetime import datetime, timedelta
from pathlib import Path
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.config import Settings
from radmon.models import StationConfig
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore
from radmon.web_reports import WebReportJobs


class ReportRepository:
    def station_config(self, serid):
        if serid != 5201:
            raise KeyError(serid)
        return StationConfig(5201, "52", "IS-1", "Gd.52", 8, 10, 30, "uSv/h")

    def measurement_history(self, start, end, *, serid, limit=5000):
        return [{"serid": serid, "dtom": start, "doserate": 0.1, "dose": 0, "previnterval": 2, "stat": 0}]

    def alarm_history(self, start, end, *, serid, limit=500):
        return []


def test_report_job_lifecycle_persists_only_safe_artifact_metadata(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    identity = security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "2468")
    jobs = WebReportJobs(security, AuditTrail(security), ReportRepository(), Settings(report_dir=tmp_path / "reports"))
    start = datetime(2026, 9, 1, 0, 0)
    created = jobs.create(identity, serid=5201, start=start, end=start + timedelta(hours=1))
    assert created["status"] == "queued"
    for _ in range(100):
        current = jobs.get(created["job_id"])
        if current and current["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert current is not None
    assert current["status"] == "completed", current.get("error")
    item, path = jobs.artifact(created["job_id"])
    assert item["artifact_name"] == f"radmon-{created['job_id']}.pdf"
    assert path.parent == (tmp_path / "reports" / "web").resolve()
    assert path.read_bytes().startswith(b"%PDF")
    jobs.shutdown()


def test_report_request_validates_station_and_range_and_audits_only_requests(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    identity = security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "2468")
    audit = AuditTrail(security)
    jobs = WebReportJobs(security, audit, ReportRepository(), Settings(report_dir=tmp_path / "reports"))
    start = datetime(2026, 9, 1, 0, 0)

    with pytest.raises(ValueError, match="station"):
        jobs.create(identity, serid=9999, start=start, end=start + timedelta(hours=1))
    with pytest.raises(ValueError, match="after"):
        jobs.create(identity, serid=5201, start=start, end=start)
    with pytest.raises(ValueError, match="terlalu panjang"):
        jobs.create(identity, serid=5201, start=start, end=start + timedelta(days=367))

    created = jobs.create(identity, serid=5201, start=start, end=start + timedelta(hours=1))
    events = audit.list_events()
    assert events[0]["action"] == "REPORT_REQUEST"
    assert events[0]["target_id"] == created["job_id"]
    jobs.shutdown()


def test_oversized_report_is_rejected_before_job_or_artifact_state_is_created(tmp_path):
    class OversizedRepository(ReportRepository):
        def measurement_count(self, start, end, *, serid=None):
            return 20_001

    security = SecurityStore(tmp_path / "security.db")
    identity = security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "2468")
    jobs = WebReportJobs(security, AuditTrail(security), OversizedRepository(), Settings(report_dir=tmp_path / "reports"))
    start = datetime(2026, 9, 1, 0, 0)

    with pytest.raises(ValueError, match="pengukuran.*rentang waktu lebih sempit"):
        jobs.create(identity, serid=5201, start=start, end=start + timedelta(hours=1))
    with pytest.raises(ValueError, match="pengukuran.*rentang waktu lebih sempit"):
        jobs.preview_pdf(serid=5201, start=start, end=start + timedelta(hours=1))
    assert jobs.list() == []
    assert not (tmp_path / "reports" / "web").exists()
    jobs.shutdown()


def test_report_artifact_cannot_be_redirected_outside_generated_directory(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    jobs = WebReportJobs(security, AuditTrail(security), ReportRepository(), Settings(report_dir=tmp_path / "reports"))
    job_id = "a" * 32
    with security._connection() as connection:
        connection.execute(
            """INSERT INTO web_report_jobs
            (job_id, username, serid, start_at, end_at, status, artifact_name, created_at)
            VALUES (?, 'operator', 5201, '2026-09-01T00:00:00+00:00',
                    '2026-09-01T01:00:00+00:00', 'completed', '../security.db',
                    '2026-09-01T00:00:00+00:00')""",
            (job_id,),
        )

    with pytest.raises(ValueError, match="artifact"):
        jobs.artifact(job_id)
    assert jobs.get("../security.db") is None
    jobs.shutdown()


class AlarmControl:
    def ack(self, *args, **kwargs):
        return {}


class DeviceAdmin:
    def update_station(self, identity, pin, serid, changes):
        return {"serid": serid, **changes}

    def create_station(self, identity, pin, serid, values):
        return {"serid": serid, **values}

    def delete_station(self, identity, pin, serid):
        return None


class ApiReportJobs:
    owner_job_id = "b" * 32

    def __init__(self, path: Path):
        self.path = path
        self.path.write_bytes(b"%PDF-test")
        self.artifact_calls = 0
        self.created = False
        self.item = {
            "job_id": self.owner_job_id,
            "username": "operator",
            "serid": 5201,
            "start_at": "2026-09-01T00:00:00+00:00",
            "end_at": "2026-09-01T01:00:00+00:00",
            "status": "completed",
            "artifact_name": "radmon-safe.pdf",
            "error": None,
            "created_at": "2026-09-01T00:00:00+00:00",
            "completed_at": "2026-09-01T01:01:00+00:00",
        }

    def list(self, *, username=None):
        return [self.item] if username in (None, "operator") else []

    def create(self, identity, *, serid, start, end):
        self.created = True
        return {**self.item, "username": identity.username, "serid": serid, "start_at": start.isoformat(), "end_at": end.isoformat(), "status": "queued", "artifact_name": None, "completed_at": None}

    def get(self, job_id):
        return self.item if job_id == self.owner_job_id else None

    def artifact(self, job_id):
        self.artifact_calls += 1
        if job_id != self.owner_job_id:
            raise KeyError(job_id)
        return self.item, self.path


def test_report_control_api_validates_rbac_status_download_and_audit(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    for username, role in (("admin", Role.ADMINISTRATOR), ("operator", Role.OPERATOR), ("other", Role.OPERATOR), ("viewer", Role.VIEWER)):
        security.create_user(username, username.title(), role, "Password123!", "2468")
    audit = AuditTrail(security)
    jobs = ApiReportJobs(tmp_path / "safe.pdf")
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=audit,
        alarm_mirror=RemoteAlarmMirror(security),
        alarm_control=AlarmControl(),
        device_admin=DeviceAdmin(),
        report_jobs=jobs,
    )
    web = TestClient(app)
    payload = {"serid": 5201, "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-01T01:00:00Z"}

    assert web.post("/api/v1/control/reports", json=payload).status_code == 401
    assert web.post("/auth/login", json={"username": "viewer", "password": "Password123!"}).status_code == 200
    assert web.post("/api/v1/control/reports", json=payload).status_code == 403
    web.post("/auth/logout")
    assert web.post("/auth/login", json={"username": "operator", "password": "Password123!"}).status_code == 200
    invalid = web.post("/api/v1/control/reports", json={**payload, "end_at": payload["start_at"]})
    assert invalid.status_code == 422
    assert jobs.created is False
    created = web.post("/api/v1/control/reports", json=payload)
    assert created.status_code == 200
    assert "username" not in created.json()
    own_status = web.get(f"/api/v1/control/reports/{jobs.owner_job_id}")
    assert own_status.status_code == 200
    assert own_status.json()["status"] == "completed"
    web.post("/auth/logout")
    assert web.post("/auth/login", json={"username": "other", "password": "Password123!"}).status_code == 200
    assert web.get(f"/api/v1/control/reports/{jobs.owner_job_id}").status_code == 403
    assert web.get(f"/api/v1/control/reports/{jobs.owner_job_id}/download").status_code == 403
    assert web.get(f"/api/v1/control/reports/{jobs.owner_job_id}/preview").status_code == 403
    assert jobs.artifact_calls == 0
    web.post("/auth/logout")
    assert web.post("/auth/login", json={"username": "admin", "password": "Password123!"}).status_code == 200
    download = web.get(f"/api/v1/control/reports/{jobs.owner_job_id}/download")
    preview = web.get(f"/api/v1/control/reports/{jobs.owner_job_id}/preview")
    assert download.status_code == 200
    assert download.content == b"%PDF-test"
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"] == f'inline; filename="radmon-report-{jobs.owner_job_id}.pdf"'
    assert preview.content == download.content == jobs.path.read_bytes()
    assert {event["action"] for event in audit.list_events()} >= {"REPORT_DOWNLOAD", "REPORT_PREVIEW"}


def test_draft_preview_is_authorized_and_matches_generated_job_pdf(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "2468")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    audit = AuditTrail(security)
    jobs = WebReportJobs(security, audit, ReportRepository(), Settings(report_dir=tmp_path / "reports"))
    app = FastAPI()
    attach_secure_routes(app, security=security, audit=audit, alarm_mirror=RemoteAlarmMirror(security), alarm_control=AlarmControl(), device_admin=DeviceAdmin(), report_jobs=jobs)
    web = TestClient(app)
    query = "serid=5201&start_at=2026-09-01T00%3A00%3A00Z&end_at=2026-09-01T01%3A00%3A00Z"

    assert web.get(f"/api/v1/control/reports/draft-preview?{query}").status_code == 401
    web.post("/auth/login", json={"username": "viewer", "password": "Password123!"})
    assert web.get(f"/api/v1/control/reports/draft-preview?{query}").status_code == 403
    web.post("/auth/logout")
    web.post("/auth/login", json={"username": "operator", "password": "Password123!"})
    preview = web.get(f"/api/v1/control/reports/draft-preview?{query}")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    assert web.get(f"/api/v1/control/reports/draft-preview?{query.replace('5201', '../security.db')}").status_code == 422
    created = web.post("/api/v1/control/reports", json={"serid": 5201, "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-01T01:00:00Z"}).json()
    for _ in range(100):
        item = jobs.get(created["job_id"])
        if item and item["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert item["status"] == "completed", item.get("error")
    assert preview.content == jobs.artifact(created["job_id"])[1].read_bytes()
    assert any(event["action"] == "REPORT_PREVIEW" for event in audit.list_events())
    jobs.shutdown()


def test_reports_frontend_contract_uses_native_controls_and_safe_download_url():
    root = Path(__file__).resolve().parents[1]
    page = (root / "web/src/pages/ReportsPage.tsx").read_text(encoding="utf-8")
    api = (root / "web/src/api.ts").read_text(encoding="utf-8")
    navigation = (root / "web/src/navigation.ts").read_text(encoding="utf-8")
    navigation_icon = (root / "web/src/layout/NavigationIcon.tsx").read_text(encoding="utf-8")
    styles = (root / "web/src/ui-polish.css").read_text(encoding="utf-8")

    assert 'id="report-station"' in page
    assert 'type="datetime-local"' in page
    assert "reportDownloadUrl(job.job_id)" in page
    assert "reportPreviewUrl(previewJobId)" in page
    assert 'job.status === "completed"' in page
    assert "<iframe" in page and "previewLoading" in page and "previewError" in page
    assert 'FilePdf' in navigation_icon and 'case "reports"' in navigation_icon
    assert "window.location" not in page
    assert "<Dialog" not in page
    assert "draft-preview?${query}" in page
    assert "disabled={creating || !serid || !draftUrl}" in page
    assert 'grid-template-columns: minmax(260px, 1fr) minmax(0, 2fr)' in styles
    assert "@media (max-width: 767px)" in styles and ".report-workspace { grid-template-columns: minmax(0, 1fr); }" in styles
    assert "listReportJobs" in api and "requestReport" in api and "reportDownloadUrl" in api and "reportPreviewUrl" in api
    assert '{ id: "reports", label: "Laporan", minimum: "Operator" }' in navigation
