from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_api import SESSION_COOKIE, attach_secure_routes
from radmon.security import AuthenticationRateLimited, Role, SecurityStore
from radmon.web_host import attach_web_routes
from radmon.config import Settings, ensure_grafana_password
from radmon.lan import LanSource
from radmon.source_health import SourceHealthService


class _AlarmControl:
    def ack(self, *args, **kwargs):
        return {}


class _DeviceAdmin:
    def update_station(self, *args, **kwargs):
        return {}

    def create_station(self, *args, **kwargs):
        return {}

    def delete_station(self, *args, **kwargs):
        return None


def _secure_client(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    mirror = RemoteAlarmMirror(security)
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=AuditTrail(security),
        alarm_mirror=mirror,
        alarm_control=_AlarmControl(),
        device_admin=_DeviceAdmin(),
    )
    return TestClient(app), security, mirror


def test_login_throttle_is_atomic_per_ip_and_does_not_lock_account_globally(tmp_path):
    now = [datetime(2026, 10, 8, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db", now=lambda: now[0])
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")

    for _ in range(4):
        assert security.authenticate("viewer", "wrong", client_ip="192.0.2.10") is None
    with pytest.raises(AuthenticationRateLimited):
        security.authenticate("viewer", "wrong", client_ip="192.0.2.10")
    # The account is not globally locked: a different client can still log in.
    assert security.authenticate("viewer", "Password123!", client_ip="192.0.2.11") is not None
    now[0] += timedelta(seconds=46)
    assert security.authenticate("viewer", "Password123!", client_ip="192.0.2.10") is not None


def test_malformed_hash_cannot_trigger_unbounded_password_work(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    with security._connection() as connection:
        connection.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            ("pbkdf2_sha256$999999999$0011223344556677$" + "0" * 64, "viewer"),
        )
    assert security.authenticate("viewer", "Password123!") is None


def test_first_install_grafana_secret_is_unique_atomic_and_legacy_value_is_preserved(tmp_path):
    env_file = tmp_path / "config" / ".env"
    env_file.parent.mkdir()
    env_file.write_text(
        "RADMON_GRAFANA_PASSWORD=GENERATE_ON_FIRST_START\n",
        encoding="utf-8",
    )
    assert ensure_grafana_password(env_file) is True
    generated = env_file.read_text(encoding="utf-8").split("=", 1)[1].strip()
    assert generated != "GENERATE_ON_FIRST_START"
    assert len(generated) >= 20
    assert ensure_grafana_password(env_file) is False
    assert env_file.read_text(encoding="utf-8").split("=", 1)[1].strip() == generated

    legacy = tmp_path / "legacy.env"
    legacy.write_text("RADMON_GRAFANA_PASSWORD=admin\n", encoding="utf-8")
    assert ensure_grafana_password(legacy) is False
    assert legacy.read_text(encoding="utf-8") == "RADMON_GRAFANA_PASSWORD=admin\n"


def test_production_remote_login_requires_tls_but_loopback_http_remains_recoverable(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=AuditTrail(security),
        alarm_mirror=RemoteAlarmMirror(security),
        alarm_control=_AlarmControl(),
        device_admin=_DeviceAdmin(),
        cookie_secure=True,
        reject_insecure_remote=True,
    )
    remote = TestClient(app, client=("10.50.60.70", 50000))
    assert remote.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
    ).status_code == 426

    local = TestClient(app, client=("127.0.0.1", 50000))
    response = local.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
    )
    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]


def test_forwarded_https_is_accepted_only_from_configured_proxy_network(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=AuditTrail(security),
        alarm_mirror=RemoteAlarmMirror(security),
        alarm_control=_AlarmControl(),
        device_admin=_DeviceAdmin(),
        cookie_secure=True,
        reject_insecure_remote=True,
        trusted_proxy_nets=("10.50.0.0/16",),
        allowed_origins=("https://monitoring.example",),
    )

    trusted = TestClient(app, client=("10.50.60.70", 50000))
    response = trusted.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
        headers={
            "Origin": "https://monitoring.example",
            "X-Forwarded-For": "192.0.2.10",
            "X-Forwarded-Proto": "https",
        },
    )
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]

    untrusted = TestClient(app, client=("192.0.2.20", 50000))
    assert untrusted.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
        headers={"X-Forwarded-Proto": "https"},
    ).status_code == 426


def test_policy_failure_does_not_mark_a_healthy_remote_source_offline(tmp_path):
    service = SourceHealthService(SecurityStore(tmp_path / "security.db"), offline_after_failures=2)
    source = LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    state = service.record_success(
        source, live=True, alarm=True, history=False, policy_error="policy cache unavailable"
    )
    assert state["state"] == "CONNECTED"
    assert state["policy_state"] == "DEGRADED"
    assert state["last_policy_error"] == "policy cache unavailable"
    recovered = service.record_success(source, live=True, alarm=True, history=False)
    assert recovered["state"] == "CONNECTED"
    assert recovered["policy_state"] == "OK"


def test_cookie_mutations_require_same_origin_and_security_headers(tmp_path):
    client, _security, _mirror = _secure_client(tmp_path)
    denied = client.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
        headers={"Origin": "https://evil.example"},
    )
    assert denied.status_code == 403
    allowed = client.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
        headers={"Origin": "http://testserver"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'self'" in allowed.headers["content-security-policy"]


def test_same_origin_referer_is_accepted_but_grafana_gateway_requires_radmon_session(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    app = FastAPI()
    attach_web_routes(
        app,
        settings=Settings(grafana_fallback_port=3300),
        security=security,
        web_dist=tmp_path / "missing",
        grafana_transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok")),
    )
    client = TestClient(app, client=("10.50.60.70", 50000))
    assert client.get("/api/ds/query").status_code == 401
    token = security.create_session("viewer")
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/ds/query").status_code == 200

    secure_client, _security, _mirror = _secure_client(tmp_path / "referer")
    assert secure_client.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
        headers={"Referer": "http://testserver/app/login?next=/"},
    ).status_code == 200


def test_authenticated_alarm_read_model_does_not_expose_operator_metadata(tmp_path):
    client, _security, mirror = _secure_client(tmp_path)
    mirror.mirror(
        "gd52",
        [{
            "serid": 5201,
            "dtoa": datetime(2026, 10, 8, 1, 0),
            "lvl": 2,
            "mvalue": 26.0,
            "thvalue": 25.0,
            "i_flag": 1,
            "pic": "private-pic",
            "note": "private-note",
        }],
    )
    client.post(
        "/auth/login",
        json={"username": "viewer", "password": "Password123!"},
    )
    response = client.get("/api/v1/control/alarms")
    assert response.status_code == 200
    assert not {"pic", "note", "action", "acknowledged_at"} & response.json()[0].keys()
