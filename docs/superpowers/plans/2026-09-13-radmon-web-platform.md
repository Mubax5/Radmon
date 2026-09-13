# RadMon Web Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a lightweight Windows-hosted BRIN web platform where `/` is a clean anonymous Grafana kiosk, `/app` requires RadMon login for Viewer/Operator/Administrator, saved Grafana edits survive every restart/update, and the existing Dell i5-4460/6 GB host runs unattended without Docker or an always-on Node process.

**Architecture:** Keep Python/FastAPI/LAN/alarm logic authoritative. Serve a static React + TypeScript + Kumo control plane from FastAPI, keep native Grafana as the anonymous monitoring engine, and supervise `RadMon.exe --server` plus native Grafana as automatic Windows services. SQLite remains the lightweight central state store; source MariaDB schemas remain untouched.

**Tech Stack:** Python 3, FastAPI, Uvicorn, SQLite, MariaDB client, React 19, TypeScript, Vite, `@cloudflare/kumo` 2.13.2, Phosphor Icons, native Grafana, SSE, PyInstaller, Inno Setup, WinSW v2.12.0 `WinSW.NET461.exe`, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md`

## Global Constraints

- Server stays on the current Dell Inspiron 3847, Intel i5-4460, 6 GB RAM, existing storage, and current Windows 10 Enterprise build.
- No hardware or OS upgrade.
- No Docker requirement, Kubernetes, Redis, local PostgreSQL, SSR Node service, or heavyweight observability stack.
- Node/Vite are build-time only.
- Existing `.50/.52/.38` source MariaDB schemas must not receive migrations.
- Existing Alarm Policy, ACK, suppression, archive, reports, audit, and LAN behavior must remain regression-green.
- `/` is anonymous read-only Grafana monitoring only, with no RadMon sign-in UI.
- `/app` and application APIs require RadMon login, including Viewer.
- Viewer/Operator/Administrator permissions are enforced server-side.
- Kumo is the primary UI system; custom CSS is layout glue only.
- Existing saved Grafana dashboards are authoritative. Normal startup/update must not overwrite them.
- Production Grafana stays on configured port 3300 and must not silently move to another port.
- Production must start at Windows boot without an interactive login or open PySide window.
- Only `main` and `feature` remain as persistent repository branches.
- This plan and the companion spec are temporary and are deleted after all verification gates pass.

---

### Task 1: Lock the Frontend Build and CI Baseline

**Files:**
- Create: `web/package-lock.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_web_platform_contract.py`

**Interfaces:**
- Produces: deterministic `npm ci`, `npm run check`, and `npm run build` gates.

- [ ] **Step 1: Write the failing build contract**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_build_is_locked_and_node_is_build_time_only():
    assert (ROOT / "web/package-lock.json").is_file()
    package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    assert '"build": "tsc -b && vite build"' in package
    assert '"start"' not in package
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_web_platform_contract.py`

Expected: fail because the npm lockfile is absent.

- [ ] **Step 3: Generate the lockfile and verify the current Kumo app**

```bash
cd web
npm install --package-lock-only
npm ci
npm run check
npm run build
```

Do not change the approved dependency families: React 19, Kumo 2.13.2, Phosphor Icons, TypeScript, Vite.

- [ ] **Step 4: Add frontend gates to CI**

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: '22'
    cache: npm
    cache-dependency-path: web/package-lock.json
- run: npm ci
  working-directory: web
- run: npm run check
  working-directory: web
- run: npm run build
  working-directory: web
```

- [ ] **Step 5: Verify baseline**

```bash
pytest -q
python -m compileall -q radmon packaging
cd web && npm ci && npm run check && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add web/package-lock.json .github/workflows/ci.yml tests/test_web_platform_contract.py
git commit -m "test: lock web platform build"
```

---

### Task 2: Make Grafana Seed-Once, Editable, Persistent, and Kiosk-First

**Files:**
- Modify: `radmon/grafana_persistent.py`
- Modify: `radmon/grafana_tv.py`
- Modify: `radmon/web_host.py`
- Modify: `tests/test_grafana_persistence.py`
- Create: `tests/test_grafana_landing.py`

**Interfaces:**
- Consumes: `PersistentGrafanaBootstrap.ensure()`, `playlist_url(base_url)`.
- Produces: stable anonymous monitoring URL and seed-once dashboard provisioning.

- [ ] **Step 1: Add final kiosk URL test**

```python
from radmon.config import Settings
from radmon.web_host import monitoring_url


def test_monitoring_url_is_grafana_kiosk_only():
    url = monitoring_url(Settings(central_host="192.168.1.2", grafana_fallback_port=3300))
    assert url.startswith("http://192.168.1.2:3300/")
    assert "kiosk" in url
    assert "autofitpanels" in url
    assert "/app" not in url
    assert "login" not in url.lower()
```

- [ ] **Step 2: Strengthen no-rollback tests**

In `tests/test_grafana_persistence.py`, keep the existing assertion that an editable saved dashboard with arbitrary panels causes zero writes. Add a second restart-style call to `_provision_via_api()` and assert it still produces zero dashboard writes.

- [ ] **Step 3: Keep first seed editable and non-overwriting**

For a missing dashboard, POST:

```python
{
    "dashboard": {**factory_dashboard, "editable": True},
    "folderId": 0,
    "overwrite": False,
    "message": "RadMon initial monitoring seed",
}
```

- [ ] **Step 4: Preserve old saved layouts during one-time unlock**

If an existing dashboard has `editable=False`, send back the saved dashboard body unchanged except `editable=True`. This is the only normal migration path allowed to use `overwrite=True`.

- [ ] **Step 5: Keep native Grafana stable and anonymous-viewer capable**

`_native_environment()` must include:

```python
env["GF_SERVER_HTTP_ADDR"] = "0.0.0.0"
env["GF_AUTH_ANONYMOUS_ENABLED"] = "true"
env["GF_AUTH_ANONYMOUS_ORG_ROLE"] = "Viewer"
env["GF_AUTH_DISABLE_LOGIN_FORM"] = "false"
```

`_find_free_port(3300)` must raise if 3300 is occupied rather than selecting 3301/3302.

- [ ] **Step 6: Verify**

```bash
pytest -q tests/test_grafana_persistence.py tests/test_grafana_landing.py tests/test_grafana_tv.py tests/test_grafana_monitoring.py
```

- [ ] **Step 7: Commit**

```bash
git add radmon/grafana_persistent.py radmon/grafana_tv.py radmon/web_host.py tests/test_grafana_persistence.py tests/test_grafana_landing.py
git commit -m "feat: persist editable Grafana monitoring"
```

---

### Task 3: Enforce Authenticated Viewer/Operator/Admin Boundaries Server-Side

**Files:**
- Modify: `radmon/web_api.py`
- Modify: `radmon/secure_api.py`
- Modify: `tests/test_web_api.py`
- Create: `tests/test_web_role_matrix.py`

**Interfaces:**
- Consumes: `SESSION_COOKIE`, `SecurityStore.session_user()`, `Role`.
- Produces: `require_role(security, minimum)` FastAPI dependency.

- [ ] **Step 1: Add the permission matrix**

```python
@pytest.mark.parametrize(
    "role,path,expected",
    [
        (None, "/api/v1/web/overview", 401),
        ("Viewer", "/api/v1/web/overview", 200),
        ("Viewer", "/api/v1/control/alarm-events", 403),
        ("Operator", "/api/v1/control/alarm-events", 200),
        ("Viewer", "/api/v1/web/system", 403),
        ("Administrator", "/api/v1/web/system", 200),
    ],
)
def test_role_matrix(role, path, expected, web_client_for_role):
    assert web_client_for_role(role).get(path).status_code == expected
```

- [ ] **Step 2: Verify RED where current routes are too permissive**

Run: `pytest -q tests/test_web_api.py tests/test_web_role_matrix.py`

- [ ] **Step 3: Add reusable backend role dependency**

```python
ROLE_RANK = {Role.VIEWER: 1, Role.OPERATOR: 2, Role.ADMINISTRATOR: 3}


def require_role(security: SecurityStore, minimum: Role):
    def dependency(request: Request) -> UserIdentity:
        identity = security.session_user(request.cookies.get(SESSION_COOKIE))
        if identity is None:
            raise HTTPException(status_code=401, detail="authentication required")
        if ROLE_RANK[identity.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail=f"{minimum.value} required")
        return identity
    return dependency
```

- [ ] **Step 4: Require Viewer on every `/api/v1/web/*` read route**

Do not trust a browser-supplied role. Operator/Admin control endpoints keep their existing backend security/PIN rules.

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_security.py tests/test_secure_api.py tests/test_web_api.py tests/test_web_role_matrix.py
```

- [ ] **Step 6: Commit**

```bash
git add radmon/web_api.py radmon/secure_api.py tests/test_web_api.py tests/test_web_role_matrix.py
git commit -m "feat: enforce web role boundaries"
```

---

### Task 4: Refactor the React/Kumo Control Plane into Focused Pages

**Files:**
- Create: `web/src/auth.tsx`
- Create: `web/src/layout.tsx`
- Create: `web/src/pages/OverviewPage.tsx`
- Create: `web/src/pages/StationsPage.tsx`
- Create: `web/src/pages/HistoryPage.tsx`
- Create: `web/src/pages/ArchivesPage.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/radmon.css`
- Modify: `tests/test_web_platform_contract.py`

**Interfaces:**
- Consumes: existing `api`, `login`, `logout`, `currentUser` helpers.
- Produces: `AuthProvider`, `useSession`, `AppLayout`, role-filtered navigation, Viewer pages.

- [ ] **Step 1: Add Kumo-only contract**

```python
def test_web_uses_kumo_as_primary_component_system():
    combined = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "web/src").rglob("*.tsx")
    )
    assert "@cloudflare/kumo" in combined
    for forbidden in ("material-ui", "@mui/", "antd", "bootstrap"):
        assert forbidden not in combined.lower()
```

- [ ] **Step 2: Establish build parity before refactor**

```bash
cd web
npm ci
npm run check
npm run build
```

- [ ] **Step 3: Extract session ownership**

`auth.tsx` exposes:

```tsx
export type SessionContextValue = {
  user: SessionUser | null;
  loading: boolean;
  signIn(username: string, password: string): Promise<void>;
  signOut(): Promise<void>;
};
```

No credentials or PINs are stored in localStorage/sessionStorage.

- [ ] **Step 4: Extract Kumo layout**

Role-filtered nav must remain:

```tsx
const NAV = [
  ["overview", "Overview", "Viewer"],
  ["stations", "Stations", "Viewer"],
  ["history", "History", "Viewer"],
  ["archives", "Archives", "Viewer"],
  ["alarms", "Alarms", "Operator"],
  ["users", "Users", "Administrator"],
  ["system", "System", "Administrator"],
] as const;
```

- [ ] **Step 5: Move Viewer pages out of `App.tsx`**

Each page owns its data query and Kumo presentation only. Alarm thresholds remain server-calculated.

- [ ] **Step 6: Keep custom CSS to layout glue**

Do not recreate Kumo buttons, inputs, tables, badges, dialogs, or sidebar styling in CSS.

- [ ] **Step 7: Verify**

```bash
pytest -q tests/test_web_platform_contract.py
cd web && npm run check && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add web/src tests/test_web_platform_contract.py
git commit -m "refactor: split Kumo web control plane"
```

---

### Task 5: Complete Authenticated Viewer Parity and Lightweight SSE

**Files:**
- Create: `radmon/web_events.py`
- Modify: `radmon/central_service.py`
- Modify: `radmon/web_api.py`
- Modify: `web/src/api.ts`
- Modify: Viewer page files from Task 4
- Create: `tests/test_web_events.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `WebEventBroker.publish(event)`, `subscribe()`, authenticated `GET /api/v1/web/events` SSE.

- [ ] **Step 1: Add bounded broker test**

```python
def test_broker_is_bounded():
    broker = WebEventBroker(max_queue=8)
    q = broker.subscribe()
    for i in range(20):
        broker.publish({"type": "tick", "index": i})
    assert q.qsize() <= 8
```

Also assert anonymous SSE returns 401.

- [ ] **Step 2: Implement bounded broker**

```python
class WebEventBroker:
    def __init__(self, max_queue: int = 32):
        self.max_queue = max_queue
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            targets = tuple(self._subscribers)
        for target in targets:
            if target.full():
                try:
                    target.get_nowait()
                except queue.Empty:
                    pass
            target.put_nowait(event)
```

- [ ] **Step 3: Serve SSE with heartbeat/cleanup**

Use FastAPI `StreamingResponse(media_type="text/event-stream")`. SSE only signals state changes; authoritative data still comes from REST.

- [ ] **Step 4: Connect React using `EventSource`**

On update, refetch overview/current station state. Do not stream bulk history.

- [ ] **Step 5: Verify Viewer pages**

```bash
pytest -q tests/test_web_events.py tests/test_web_api.py tests/test_web_role_matrix.py
cd web && npm run check && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add radmon/web_events.py radmon/central_service.py radmon/web_api.py web/src tests/test_web_events.py tests/test_web_api.py
git commit -m "feat: add live Viewer web updates"
```

---

### Task 6: Complete Operator and Administrator Web Parity

**Files:**
- Create: `web/src/pages/AlarmsPage.tsx`
- Create: `web/src/pages/UsersPage.tsx`
- Create: `web/src/pages/SystemPage.tsx`
- Refactor: `web/src/Actions.tsx`
- Modify: `web/src/App.tsx`
- Modify: `radmon/web_api.py`
- Modify: `tests/test_web_role_matrix.py`
- Modify: `tests/test_alarm_policy_api.py`
- Modify: `tests/test_alarm_suppression.py`
- Modify: `tests/test_secure_api.py`

**Interfaces:**
- Operator consumes existing alarm event/ACK/suppression APIs and PIN policy.
- Administrator consumes existing user/device/system services and diagnostics.

- [ ] **Step 1: Add mutation role tests**

For every ACK/suppression/admin mutation assert: anonymous=401, Viewer=403, Operator allowed only where policy permits, Administrator allowed where policy permits.

- [ ] **Step 2: Run backend tests before UI changes**

```bash
pytest -q tests/test_web_role_matrix.py tests/test_alarm_policy_api.py tests/test_alarm_suppression.py tests/test_secure_api.py
```

- [ ] **Step 3: Implement Kumo alarm dialogs**

Submit the same required fields as desktop: event/detector identity, PIC, action/reason, duration/auto-resume where applicable, PIN. Clear PIN immediately after submit/cancel.

- [ ] **Step 4: Implement Administrator pages**

`UsersPage` never returns/displays password hashes. `SystemPage` shows source health/runtime diagnostics and `grafana_admin_url="http://localhost:3300"` only for Administrator.

- [ ] **Step 5: Preserve backend authorization as final authority**

React role filtering is presentation only; crafted requests must still be rejected by FastAPI.

- [ ] **Step 6: Verify**

```bash
pytest -q tests/test_web_role_matrix.py tests/test_alarm_policy_api.py tests/test_alarm_suppression.py tests/test_secure_api.py tests/test_security.py
cd web && npm run check && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add web/src radmon/web_api.py tests/test_web_role_matrix.py tests/test_alarm_policy_api.py tests/test_alarm_suppression.py tests/test_secure_api.py
git commit -m "feat: complete Operator and Administrator web parity"
```

---

### Task 7: Bundle Only Compiled Web Assets into `RadMon.exe`

**Files:**
- Modify: `RadMon.spec`
- Modify: `.github/workflows/windows-build.yml`
- Modify: `tests/test_bundle.py`
- Modify: `tests/test_windows_packaging.py`

**Interfaces:**
- Consumes: `web/dist`.
- Produces: packaged `RadMon.exe` with static web assets, no Node runtime.

- [ ] **Step 1: Add packaging contract**

```python
def test_pyinstaller_bundles_compiled_web_only():
    spec = (ROOT / "RadMon.spec").read_text(encoding="utf-8")
    assert "web/dist" in spec.replace("\\", "/")
    assert "node_modules" not in spec
```

- [ ] **Step 2: Build web before PyInstaller in Windows CI**

Use Node 22 + `npm ci`, `npm run check`, `npm run build`.

- [ ] **Step 3: Add `web/dist` to PyInstaller data**

Bundle to runtime `web/`. Do not bundle `web/src`, TypeScript configs, npm cache, or `node_modules`.

- [ ] **Step 4: Extend smoke test**

Installed `RadMon.exe --smoke-test` must verify packaged imports and bundled `web/index.html` availability.

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_bundle.py tests/test_windows_packaging.py
```

Require Windows Actions PyInstaller smoke test to pass.

- [ ] **Step 6: Commit**

```bash
git add RadMon.spec .github/workflows/windows-build.yml tests/test_bundle.py tests/test_windows_packaging.py
git commit -m "build: bundle Kumo web app"
```

---

### Task 8: Install RadMon and Grafana as Automatic Windows Services

**Files:**
- Create: `packaging/RadMon.Service.xml`
- Create: `packaging/Grafana.Service.xml`
- Modify: `packaging/install_server.ps1`
- Modify: `packaging/RadMon.iss`
- Modify: `.github/workflows/windows-build.yml`
- Create: `tests/test_windows_service_packaging.py`
- Modify: `tests/test_server_mode.py`

**Interfaces:**
- Produces: `RadMonServer` service running `RadMon.exe --server`, optional `RadMonGrafana` service when native Grafana is found.

- [ ] **Step 1: Add service contract tests**

```python
def test_radmon_service_runs_server_mode():
    xml = (ROOT / "packaging/RadMon.Service.xml").read_text(encoding="utf-8")
    assert "<id>RadMonServer</id>" in xml
    assert "%BASE%\\app\\RadMon.exe" in xml
    assert "--server" in xml
    assert "<startmode>Automatic</startmode>" in xml
    assert '<onfailure action="restart"' in xml
```

Also assert `install_server.ps1` no longer calls `Register-ScheduledTask`.

- [ ] **Step 2: Pin the service wrapper exactly**

Windows CI downloads:

```text
https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe
```

Copy it into installer staging as both `RadMon.Service.exe` and `Grafana.Service.exe`. No production startup download is allowed.

- [ ] **Step 3: Define RadMon service XML**

```xml
<service>
  <id>RadMonServer</id>
  <name>RadMon Server</name>
  <description>RadMon central collector and authenticated web platform</description>
  <executable>%BASE%\app\RadMon.exe</executable>
  <arguments>--server</arguments>
  <startmode>Automatic</startmode>
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="30 sec" />
  <resetfailure>1 hour</resetfailure>
  <log mode="roll-by-size-time">
    <sizeThreshold>10485760</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
</service>
```

The wrapper is installed at `{app}\RadMon.Service.exe`, so `%BASE%\app\RadMon.exe` resolves to the existing Inno layout `{app}\app\RadMon.exe`.

- [ ] **Step 4: Define Grafana service template**

`Grafana.Service.xml` contains token `__GRAFANA_BIN__`. `install_server.ps1` detects, in order: `RADMON_GRAFANA_BIN`, `%ProgramFiles%\GrafanaLabs\grafana\bin\grafana-server.exe`, then `%ProgramFiles%\GrafanaLabs\grafana\grafana-server.exe`. It replaces the token with the XML-escaped absolute executable path before calling `Grafana.Service.exe install`.

- [ ] **Step 5: Replace Scheduled Task ownership**

`install_server.ps1` performs idempotently:

```powershell
& "$InstallRoot\RadMon.Service.exe" stop 2>$null
& "$InstallRoot\RadMon.Service.exe" uninstall 2>$null
& "$InstallRoot\RadMon.Service.exe" install
& "$InstallRoot\RadMon.Service.exe" start
```

Do the same for `RadMonGrafana` only when a native Grafana executable is detected. Keep firewall rules 8090 and 3300 limited to `LocalSubnet`.

- [ ] **Step 6: Update Inno uninstall**

Replace legacy `schtasks.exe` uninstall entries with wrapper `stop` + `uninstall`. Persistent data remains untouched.

- [ ] **Step 7: Verify**

```bash
pytest -q tests/test_server_mode.py tests/test_windows_service_packaging.py tests/test_windows_packaging.py
```

Windows Actions must compile the installer and verify the service XML/wrapper files are present after silent install.

- [ ] **Step 8: Commit**

```bash
git add packaging/RadMon.Service.xml packaging/Grafana.Service.xml packaging/install_server.ps1 packaging/RadMon.iss .github/workflows/windows-build.yml tests/test_windows_service_packaging.py tests/test_server_mode.py
git commit -m "feat: install RadMon as Windows services"
```

---

### Task 9: Preserve All Production State Across Installer Updates

**Files:**
- Modify: `packaging/RadMon.iss`
- Modify: `radmon/paths.py`
- Modify: `radmon/grafana_persistent.py`
- Modify: `tests/test_windows_packaging.py`
- Modify: `tests/test_grafana_persistence.py`

**Interfaces:**
- Produces: upgrade-safe persistence for config, SQLite/runtime, Grafana data, archives, reports.

- [ ] **Step 1: Add persistence assertions**

The installer must never delete normal-upgrade contents of:

```text
config/
runtime/
runtime/grafana/data/
archives/
reports/
```

and must create `.env` only when it does not exist.

- [ ] **Step 2: Keep only `{app}\app` replaceable**

Retain `[InstallDelete] Type: filesandordirs; Name: "{app}\app"`; do not add deletion directives for persistent directories.

- [ ] **Step 3: Keep `GF_PATHS_DATA` external**

`PersistentGrafanaBootstrap._native_environment()` must resolve Grafana data under external runtime, never inside replaceable application binaries.

- [ ] **Step 4: Verify**

```bash
pytest -q tests/test_windows_packaging.py tests/test_grafana_persistence.py tests/test_paths.py
```

- [ ] **Step 5: Commit**

```bash
git add packaging/RadMon.iss radmon/paths.py radmon/grafana_persistent.py tests/test_windows_packaging.py tests/test_grafana_persistence.py
git commit -m "fix: preserve RadMon and Grafana state on upgrade"
```

---

### Task 10: Bound Resource Use for the 6 GB Windows Host

**Files:**
- Modify: `radmon/production_app.py`
- Modify: `radmon/logging_setup.py`
- Modify: `.env.example`
- Modify: `tests/test_server_mode.py`
- Create: `tests/test_logging.py`

**Interfaces:**
- Produces: headless server mode, bounded logs, no Docker fallback, no accidental browser/UI launch.

- [ ] **Step 1: Add headless resource contracts**

Tests must prove `run_server()` does not call `run_admin_ui` or `webbrowser.open`, and Docker fallback stays disabled by default.

- [ ] **Step 2: Add logging test**

```python
def test_production_logging_is_bounded(tmp_path):
    log_path = configure_logging(tmp_path)
    handlers = logging.getLogger().handlers
    rotating = [h for h in handlers if isinstance(h, RotatingFileHandler)]
    assert rotating
    assert rotating[0].maxBytes == 10 * 1024 * 1024
    assert rotating[0].backupCount == 5
    assert log_path.parent == tmp_path
```

- [ ] **Step 3: Use rotating logging**

Configure 10 MB × 5 files for the primary production log.

- [ ] **Step 4: Make low-resource production defaults explicit**

```env
RADMON_GRAFANA_DOCKER_FALLBACK=0
RADMON_WEB_COOKIE_SECURE=0
RADMON_GRAFANA_FALLBACK_PORT=3300
RADMON_LAN_POLL_INTERVAL=2
RADMON_WHATSAPP_ENABLED=0
```

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_server_mode.py tests/test_logging.py
```

- [ ] **Step 6: Commit**

```bash
git add radmon/production_app.py radmon/logging_setup.py .env.example tests/test_server_mode.py tests/test_logging.py
git commit -m "perf: bound server resources for 6GB host"
```

---

### Task 11: Update Operator and Deployment Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/INSTALLATION.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/manual/installation.html`
- Modify: `docs/manual/user-manual.html`
- Modify: `grafana/README.md`
- Modify: `tests/test_bundle.py`
- Modify: `tests/test_release_cleanup.py`

**Interfaces:**
- Produces: exact SOP for routes, auth, Grafana editing/persistence, services, and updates.

- [ ] **Step 1: Document routes exactly**

```text
http://<server>:8090/      -> full Grafana kiosk monitoring
http://<server>:8090/app   -> RadMon login and role-based control plane
http://localhost:3300      -> Grafana login/editor on the server
```

Viewer requires RadMon login. Anonymous access is monitoring only.

- [ ] **Step 2: Document no-rollback behavior**

State that a dashboard saved in Grafana is authoritative, normal RadMon startup does not overwrite it, and factory reset is never automatic.

- [ ] **Step 3: Document actual service names**

```powershell
Get-Service RadMonServer
Restart-Service RadMonServer
Get-Service RadMonGrafana
Restart-Service RadMonGrafana
```

Only `RadMonGrafana` exists when native Grafana was detected during install.

- [ ] **Step 4: Document the fixed old-Windows hardware constraint honestly**

State that the deployment is optimized for the existing Dell i5-4460/6 GB host and that BRIN network/firewall restriction is mandatory because the OS remains the existing installation.

- [ ] **Step 5: Update existing doc contracts, not a duplicate test file**

Add route/service/persistence assertions to `tests/test_bundle.py` and `tests/test_release_cleanup.py`.

Run:

```bash
pytest -q tests/test_bundle.py tests/test_release_cleanup.py
```

- [ ] **Step 6: Commit**

```bash
git add README.md docs grafana/README.md tests/test_bundle.py tests/test_release_cleanup.py
git commit -m "docs: document RadMon web platform operations"
```

---

### Task 12: Full Regression, Windows Artifact Verification, and Planning-Doc Cleanup

**Files:**
- Delete after green gates: `docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md`
- Delete after green gates: `docs/superpowers/plans/2026-09-13-radmon-web-platform.md`

**Interfaces:**
- Produces: merge-ready `feature` branch and verified installer.

- [ ] **Step 1: Run complete Python regression**

```bash
python -m pytest -q
python -m compileall -q radmon packaging
```

Expected: zero failures.

- [ ] **Step 2: Run clean frontend build**

```bash
cd web
npm ci
npm run check
npm run build
```

Expected: zero TypeScript errors and fresh `web/dist`.

- [ ] **Step 3: Run Grafana persistence regression**

```bash
pytest -q tests/test_grafana_persistence.py tests/test_grafana_landing.py tests/test_grafana_tv.py tests/test_grafana_monitoring.py
```

Expected: saved dashboards are not overwritten; missing resources seed once.

- [ ] **Step 4: Require final Windows GitHub Actions evidence**

`windows-build.yml` must prove:

```text
frontend npm ci/check/build success
PyInstaller RadMon.exe success
Inno Setup RadMon-Setup.exe success
silent install success
RadMon.exe --smoke-test success
RadMon.Service.exe/xml installed
Grafana service template/wrapper installed
no .bat or node_modules in release payload
```

- [ ] **Step 5: Remove temporary planning docs only after the gates above are green**

```bash
git rm docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md
git rm docs/superpowers/plans/2026-09-13-radmon-web-platform.md
git commit -m "chore: remove temporary web platform planning docs"
```

- [ ] **Step 6: Verify branch policy**

GitHub must list only:

```text
main
feature
```

- [ ] **Step 7: Physical Dell commissioning checklist**

Do not claim field commissioning complete until evidence is collected for every item:

```text
[ ] RadMonServer starts automatically after Windows boot
[ ] native Grafana starts automatically on port 3300
[ ] / from an allowed BRIN-LAN client shows only Grafana kiosk monitoring
[ ] /app requires login even for Viewer
[ ] Viewer crafted requests cannot call Operator/Admin mutations
[ ] Operator ACK and suppression work against production policy
[ ] Administrator user/system operations work
[ ] Grafana edit at localhost:3300 immediately changes monitoring
[ ] saved Grafana edit survives RadMonServer restart
[ ] saved Grafana edit survives Grafana restart
[ ] saved Grafana edit survives Windows restart
[ ] installer update preserves config, SQLite/runtime, archives, reports, and Grafana data
[ ] source .50/.52/.38 remain compatible with no schema mutation
```
