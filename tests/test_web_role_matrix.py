from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from radmon.secure_api import SESSION_COOKIE
from radmon.security import Role, SecurityStore, UserIdentity
from radmon.web_api import require_role


def _client(tmp_path, role: Role | None) -> TestClient:
    security = SecurityStore(tmp_path / f"roles-{role.value if role else 'anonymous'}.db")
    app = FastAPI()

    @app.get("/viewer")
    def viewer(_identity: UserIdentity = Depends(require_role(security, Role.VIEWER))):
        return {"ok": True}

    @app.get("/operator")
    def operator(_identity: UserIdentity = Depends(require_role(security, Role.OPERATOR))):
        return {"ok": True}

    @app.get("/admin")
    def admin(_identity: UserIdentity = Depends(require_role(security, Role.ADMINISTRATOR))):
        return {"ok": True}

    client = TestClient(app)
    if role is not None:
        username = role.value.lower()
        security.create_user(username, role.value, role, "Password123!", "2468")
        client.cookies.set(SESSION_COOKIE, security.create_session(username, 3600))
    return client


def test_anonymous_has_no_application_role(tmp_path):
    client = _client(tmp_path, None)
    assert client.get("/viewer").status_code == 401
    assert client.get("/operator").status_code == 401
    assert client.get("/admin").status_code == 401


def test_viewer_is_authenticated_but_read_only(tmp_path):
    client = _client(tmp_path, Role.VIEWER)
    assert client.get("/viewer").status_code == 200
    assert client.get("/operator").status_code == 403
    assert client.get("/admin").status_code == 403


def test_operator_inherits_viewer_but_not_admin(tmp_path):
    client = _client(tmp_path, Role.OPERATOR)
    assert client.get("/viewer").status_code == 200
    assert client.get("/operator").status_code == 200
    assert client.get("/admin").status_code == 403


def test_administrator_has_all_web_roles(tmp_path):
    client = _client(tmp_path, Role.ADMINISTRATOR)
    assert client.get("/viewer").status_code == 200
    assert client.get("/operator").status_code == 200
    assert client.get("/admin").status_code == 200
