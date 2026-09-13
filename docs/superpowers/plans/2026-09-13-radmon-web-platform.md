# RadMon Web Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn RadMon into a lightweight Windows-hosted BRIN web platform where `/` is a clean anonymous Grafana kiosk, `/app` is fully authenticated and role-based, Grafana edits persist without rollback, and the existing Dell i5-4460/6 GB server runs unattended 24/7 without Docker or an always-on Node process.

**Architecture:** Keep the existing Python/FastAPI/LAN/alarm core authoritative. Build the authenticated control plane as a static React + TypeScript + Kumo application served by FastAPI, keep native Grafana as the anonymous visualization engine, and install the RadMon headless runtime plus native Grafana under Windows service supervision. Preserve SQLite and legacy source MariaDB semantics; migrate desktop workflows incrementally and keep the desktop emergency UI until web parity is verified.

**Tech Stack:** Python 3, FastAPI, Uvicorn, SQLite, existing MariaDB source access, React 19, TypeScript, Vite, `@cloudflare/kumo` 2.13.2, Phosphor Icons, native Grafana, PyInstaller, Inno Setup, Windows Service Wrapper (WinSW) bundled at build time, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md`

## Global Constraints

- Final server remains the existing Dell Inspiron 3847 with Intel i5-4460, 6 GB RAM, existing storage, and the current Windows 10 Enterprise installation/build.
- No hardware or OS upgrade is part of this work.
- Production must be lightweight: no Kubernetes, no Redis, no PostgreSQL, no always-on Node server, and no Docker requirement.
- Existing detector/source MariaDB hosts and schemas remain authoritative legacy sources and must not receive schema migrations.
- Existing RadMon alarm policy, ACK, suppression, archive, reports, audit, and LAN collection semantics remain intact.
- `/` is anonymous read-only Grafana monitoring only; it contains no RadMon sign-in UI.
- `/app` and all application APIs require RadMon authentication, including Viewer.
- Viewer, Operator, and Administrator permissions are enforced server-side.
- `@cloudflare/kumo` is the primary UI component system; custom CSS is layout glue only.
- Saved Grafana state is authoritative after first seed. Normal startup and updates must never restore factory dashboards over saved edits.
- Production uses native Grafana. Docker fallback is disabled by default and is not part of the production acceptance path.
- Production does not depend on an interactive Windows login or an open PySide window.
- Only `main` and `feature` remain as persistent branches.
- This plan and its companion spec are temporary engineering artifacts and must be deleted before final merge/release.

---

## File Structure

### Existing files to evolve

- `radmon/grafana_persistent.py` — seed-once Grafana bootstrap, stable port, anonymous Viewer policy, persistent native data paths.
- `radmon/grafana_tv.py` — canonical monitoring dashboard/playlist identifiers and kiosk URL construction.
- `radmon/web_host.py` — anonymous monitoring route and static `/app` host boundary.
- `radmon/web_api.py` — authenticated Viewer read models and Administrator diagnostics.
- `radmon/secure_api.py` — canonical session/login/logout and protected control actions.
- `radmon/central_service.py` — complete backend runtime assembly and web route registration.
- `radmon/production_app.py` — interactive emergency mode and headless `--server` mode.
- `packaging/RadMon.iss` — installer layout, persistent-data exclusions, service installation.
- `packaging/install_server.ps1` — replace Scheduled Task ownership with real service installation and firewall rules.
- `.github/workflows/ci.yml` — Python + frontend contract/build checks.
- `.github/workflows/windows-build.yml` — build frontend, package EXE, bundle service wrapper, compile installer, smoke-test installed server artifacts.
- `README.md`, `docs/INSTALLATION.md`, `docs/USER-MANUAL.md`, HTML manuals — final operator/deployment documentation.

### New focused files

- `radmon/web_events.py` — low-overhead SSE broadcaster and `/api/v1/web/events` endpoint helper.
- `web/src/auth.tsx` — session provider and authenticated-route boundary.
- `web/src/layout.tsx` — Kumo application chrome and role-filtered navigation.
- `web/src/pages/OverviewPage.tsx` — Viewer overview.
- `web/src/pages/StationsPage.tsx` — Viewer station list/details.
- `web/src/pages/HistoryPage.tsx` — Viewer measurement history.
- `web/src/pages/ArchivesPage.tsx` — Viewer archive/report access.
- `web/src/pages/AlarmsPage.tsx` — Operator alarm response and suppression.
- `web/src/pages/UsersPage.tsx` — Administrator user management.
- `web/src/pages/SystemPage.tsx` — Administrator source/system diagnostics and Grafana admin link.
- `packaging/RadMon.Service.xml` — WinSW definition for `RadMon.exe --server`.
- `packaging/Grafana.Service.xml` — WinSW definition for native `grafana-server.exe` when RadMon manages it.
- `tests/test_web_events.py` — SSE behavior and authentication.
- `tests/test_web_role_matrix.py` — backend permission matrix.
- `tests/test_grafana_landing.py` — anonymous kiosk and no-sign-in contract.
- `tests/test_windows_service_packaging.py` — service wrapper/install/update persistence contract.

---

### Task 1: Re-establish a Green Feature Baseline and Frontend Build Contract

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `web/package.json`
- Test: `tests/test_web_platform_contract.py`

**Interfaces:**
- Consumes: existing `web/` React/Kumo scaffold and existing Python test suite.
- Produces: deterministic `npm ci`, `npm run check`, and `npm run build` gates used by all later tasks.

- [ ] **Step 1: Add a failing repository contract for a committed npm lockfile and static output policy**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_build_is_locked_and_node_is_build_time_only():
    assert (ROOT / "web" / "package-lock.json").is_file()
    package = (ROOT / "web" / "package.json").read_text(encoding="utf-8")
    assert '"build": "tsc -b && vite build"' in package
    assert '"start"' not in package
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `pytest -q tests/test_web_platform_contract.py`

Expected: FAIL because `web/package-lock.json` is not yet committed or the workflow does not use the locked install path.

- [ ] **Step 3: Generate and commit the lockfile without changing approved dependency families**

Run in `web/`:

```bash
npm install --package-lock-only
npm ci
npm run check
npm run build
```

The dependency set remains React 19, Kumo 2.13.2, Phosphor Icons, TypeScript, and Vite; Node remains build-time only.

- [ ] **Step 4: Make CI build the frontend before Python packaging validation**

Add these steps to `.github/workflows/ci.yml`:

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

- [ ] **Step 5: Verify the baseline**

Run:

```bash
pytest -q
python -m compileall -q radmon packaging
cd web && npm ci && npm run check && npm run build
```

Expected: all Python tests pass, TypeScript check passes, and `web/dist/index.html` is produced.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml web/package.json web/package-lock.json tests/test_web_platform_contract.py
git commit -m "test: lock web platform build contract"
```

---

### Task 2: Make Saved Grafana State Authoritative and Kiosk Landing Stable

**Files:**
- Modify: `radmon/grafana_persistent.py`
- Modify: `radmon/grafana_tv.py`
- Modify: `radmon/web_host.py`
- Test: `tests/test_grafana_persistence.py`
- Create: `tests/test_grafana_landing.py`

**Interfaces:**
- Consumes: `PersistentGrafanaBootstrap.ensure()`, `playlist_url(base_url: str) -> str`, `Settings.grafana_fallback_port`.
- Produces: `monitoring_url(settings: Settings) -> str` that always points to the saved Grafana playlist in kiosk mode and seed-once provisioning that never overwrites editable saved dashboards.

- [ ] **Step 1: Write failing tests for the final monitoring contract**

```python
from radmon.config import Settings
from radmon.web_host import monitoring_url


def test_monitoring_url_is_clean_grafana_kiosk():
    url = monitoring_url(Settings(central_host="192.168.1.2", grafana_fallback_port=3300))
    assert url.startswith("http://192.168.1.2:3300/")
    assert "kiosk" in url
    assert "autofitpanels" in url
    assert "/app" not in url
    assert "login" not in url.lower()
```

Extend `tests/test_grafana_persistence.py` so an already editable dashboard with arbitrary saved panels causes zero dashboard writes, and a missing dashboard is POSTed with `overwrite=False`.

- [ ] **Step 2: Verify RED only where the current behavior is incomplete**

Run:

```bash
pytest -q tests/test_grafana_persistence.py tests/test_grafana_landing.py
```

- [ ] **Step 3: Normalize factory dashboards as editable seeds before first POST**

In `PersistentGrafanaBootstrap._provision_via_api`, preserve this invariant:

```python
try:
    current = self._request_json(dashboard_endpoint)
except Exception:
    dashboard = dict(factory_dashboard)
    dashboard["editable"] = True
    self._request_json(
        f"{base}/api/dashboards/db",
        method="POST",
        payload={
            "dashboard": dashboard,
            "folderId": 0,
            "overwrite": False,
            "message": "RadMon initial monitoring seed",
        },
    )
else:
    saved = current.get("dashboard") if isinstance(current, dict) else None
    if isinstance(saved, dict) and saved.get("editable") is False:
        editable = dict(saved)
        editable["editable"] = True
        self._request_json(
            f"{base}/api/dashboards/db",
            method="POST",
            payload={"dashboard": editable, "folderId": 0, "overwrite": True,
                     "message": "RadMon unlock existing monitoring dashboard"},
        )
```

The only permitted `overwrite=True` path is this one-time metadata unlock that sends back the saved dashboard body unchanged.

- [ ] **Step 4: Keep Grafana at one stable production address**

Preserve `_candidate_base_urls() -> [self.fallback_base_url]` and `_find_free_port()` raising when the configured port is occupied rather than silently selecting 3301/3302.

- [ ] **Step 5: Keep anonymous Grafana read-only while leaving the editor login available**

The native environment must include exactly:

```python
env["GF_SERVER_HTTP_ADDR"] = "0.0.0.0"
env["GF_AUTH_ANONYMOUS_ENABLED"] = "true"
env["GF_AUTH_ANONYMOUS_ORG_ROLE"] = "Viewer"
env["GF_AUTH_DISABLE_LOGIN_FORM"] = "false"
```

and use the external persistent data directory under `runtime/grafana/data`.

- [ ] **Step 6: Verify**

Run:

```bash
pytest -q tests/test_grafana_persistence.py tests/test_grafana_landing.py tests/test_grafana_tv.py
```

Expected: all pass; saved dashboards produce no normal-start overwrite calls.

- [ ] **Step 7: Commit**

```bash
git add radmon/grafana_persistent.py radmon/grafana_tv.py radmon/web_host.py tests/test_grafana_persistence.py tests/test_grafana_landing.py
git commit -m "feat: make saved Grafana dashboards authoritative"
```

---

### Task 3: Lock the Anonymous-vs-Authenticated HTTP Boundary

**Files:**
- Modify: `radmon/web_host.py`
- Modify: `radmon/web_api.py`
- Modify: `radmon/secure_api.py`
- Create: `tests/test_web_role_matrix.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Consumes: existing `SESSION_COOKIE`, `SecurityStore.session_user()`, `Role`, existing secure login/logout routes.
- Produces: `current_user(request) -> UserIdentity`, `require_role(minimum: Role)` backend dependencies shared by web APIs; `/` stays anonymous while `/app` static shell may load but all app data requires authentication.

- [ ] **Step 1: Write the permission matrix first**

```python
@pytest.mark.parametrize(
    "role,path,method,expected",
    [
        (None, "/api/v1/web/overview", "GET", 401),
        ("Viewer", "/api/v1/web/overview", "GET", 200),
        ("Viewer", "/api/v1/control/alarm-events", "GET", 403),
        ("Operator", "/api/v1/control/alarm-events", "GET", 200),
        ("Viewer", "/api/v1/web/system", "GET", 403),
        ("Administrator", "/api/v1/web/system", "GET", 200),
    ],
)
def test_web_role_matrix(role, path, method, expected, web_client_for_role):
    client = web_client_for_role(role)
    assert client.request(method, path).status_code == expected
```

Use existing security fixtures/helpers; do not create a parallel auth store.

- [ ] **Step 2: Run the matrix and capture current mismatches**

Run: `pytest -q tests/test_web_role_matrix.py tests/test_web_api.py`

- [ ] **Step 3: Centralize the backend role dependency**

Add a helper in `web_api.py`:

```python
ROLE_RANK = {
    Role.VIEWER: 1,
    Role.OPERATOR: 2,
    Role.ADMINISTRATOR: 3,
}


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

Reuse this same semantic threshold from new web routes; do not trust role values sent by React.

- [ ] **Step 4: Ensure Viewer is authenticated, never anonymous**

All `/api/v1/web/*` read models must depend on at least `require_role(security, Role.VIEWER)`.

- [ ] **Step 5: Verify session cookie behavior**

Run existing secure API tests plus the new matrix:

```bash
pytest -q tests/test_security.py tests/test_secure_api.py tests/test_web_api.py tests/test_web_role_matrix.py
```

- [ ] **Step 6: Commit**

```bash
git add radmon/web_host.py radmon/web_api.py radmon/secure_api.py tests/test_web_api.py tests/test_web_role_matrix.py
git commit -m "feat: enforce authenticated web role boundaries"
```

---

### Task 4: Split the Kumo Application Shell into Focused Components

**Files:**
- Create: `web/src/auth.tsx`
- Create: `web/src/layout.tsx`
- Create: `web/src/pages/OverviewPage.tsx`
- Create: `web/src/pages/StationsPage.tsx`
- Create: `web/src/pages/HistoryPage.tsx`
- Create: `web/src/pages/ArchivesPage.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_platform_contract.py`

**Interfaces:**
- Consumes: `login`, `logout`, `currentUser`, `api` from `web/src/api.ts`; Kumo `Sidebar`, `LayerCard`, `Table`, `Button`, `Input`, `Badge`.
- Produces: `AuthProvider`, `useSession`, `AppLayout`, route pages, and `ROLE_RANK` role-filtered navigation.

- [ ] **Step 1: Add static contract tests that reject a parallel custom design system**

```python
def test_web_uses_kumo_as_primary_component_system():
    app_files = list((ROOT / "web" / "src").rglob("*.tsx"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in app_files)
    assert "@cloudflare/kumo" in combined
    assert "bootstrap" not in combined.lower()
    assert "material-ui" not in combined.lower()
    assert "antd" not in combined.lower()
```

- [ ] **Step 2: Verify the frontend still builds before refactor**

Run: `cd web && npm ci && npm run check && npm run build`

Expected: PASS; this establishes refactor parity.

- [ ] **Step 3: Extract session ownership into `auth.tsx`**

Expose:

```tsx
export type SessionContextValue = {
  user: SessionUser | null;
  loading: boolean;
  signIn(username: string, password: string): Promise<void>;
  signOut(): Promise<void>;
};

export function AuthProvider({ children }: { children: React.ReactNode }) { /* current session/login/logout flow */ }
export function useSession(): SessionContextValue { /* context guard */ }
```

- [ ] **Step 4: Extract the Cloudflare-style Kumo shell into `layout.tsx`**

Use `Sidebar` and Kumo primitives for the chrome. Keep role-filtered entries exactly:

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

- [ ] **Step 5: Move Viewer pages out of `App.tsx` without changing API behavior**

Each page owns only its data query and presentation. `App.tsx` becomes route/session orchestration rather than a 300+ line mixed-responsibility file.

- [ ] **Step 6: Keep custom CSS to layout glue**

`radmon.css` may define page grids, width constraints, responsive spacing, and RadMon-specific measurements; buttons/forms/tables/sidebar states must come from Kumo variants rather than copied Cloudflare CSS.

- [ ] **Step 7: Verify type/build parity**

Run:

```bash
cd web
npm run check
npm run build
```

and:

```bash
pytest -q tests/test_web_platform_contract.py
```

- [ ] **Step 8: Commit**

```bash
git add web/src web/package-lock.json tests/test_web_platform_contract.py
git commit -m "refactor: split Kumo web control plane shell"
```

---

### Task 5: Complete Authenticated Viewer Web Parity

**Files:**
- Modify: `radmon/web_api.py`
- Modify: `web/src/pages/OverviewPage.tsx`
- Modify: `web/src/pages/StationsPage.tsx`
- Modify: `web/src/pages/HistoryPage.tsx`
- Modify: `web/src/pages/ArchivesPage.tsx`
- Test: `tests/test_web_api.py`
- Test: `tests/test_web_role_matrix.py`

**Interfaces:**
- Consumes: repository methods `stations()`, `latest(serid)`, `history(serid, limit=...)`, existing archive/control read routes.
- Produces: authenticated Viewer-safe overview, station, history, archive/report read models with no control actions.

- [ ] **Step 1: Write failing API tests for Viewer-safe models**

```python
def test_viewer_overview_contains_only_read_model_fields(viewer_client):
    payload = viewer_client.get("/api/v1/web/overview").json()
    assert set(payload) == {"counts", "stations", "role"}
    assert payload["role"] == "Viewer"


def test_viewer_history_limit_is_bounded(viewer_client):
    assert viewer_client.get("/api/v1/web/stations/5201/history?limit=2001").status_code == 422
```

- [ ] **Step 2: Run focused tests**

Run: `pytest -q tests/test_web_api.py tests/test_web_role_matrix.py`

- [ ] **Step 3: Keep status computation server-side**

The overview API continues to classify `normal`, `warning`, `alarm`, and `offline` using repository thresholds; React renders the result and does not duplicate alarm policy calculations.

- [ ] **Step 4: Finish Kumo Viewer screens**

Use Kumo `LayerCard`, `Table`, `Badge`, form inputs, and page headers. Viewer pages must not render ACK, suppression, station editing, user editing, or system mutation controls.

- [ ] **Step 5: Verify Viewer cannot mutate through crafted requests**

Run:

```bash
pytest -q tests/test_web_api.py tests/test_web_role_matrix.py tests/test_security.py
cd web && npm run check && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add radmon/web_api.py web/src/pages tests/test_web_api.py tests/test_web_role_matrix.py
git commit -m "feat: complete authenticated Viewer web parity"
```

---

### Task 6: Add Lightweight Authenticated SSE for Live Browser Updates

**Files:**
- Create: `radmon/web_events.py`
- Modify: `radmon/central_service.py`
- Modify: `radmon/web_api.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/pages/OverviewPage.tsx`
- Create: `tests/test_web_events.py`

**Interfaces:**
- Produces: `WebEventBroker.publish(event: dict[str, Any]) -> None`, `WebEventBroker.subscribe() -> queue.Queue`, authenticated `GET /api/v1/web/events` SSE stream.
- Consumes: existing LAN runtime/status updates; REST remains authoritative for actions.

- [ ] **Step 1: Write broker unit tests first**

```python
def test_broker_fans_out_without_unbounded_queue_growth():
    broker = WebEventBroker(max_queue=8)
    q = broker.subscribe()
    for index in range(20):
        broker.publish({"type": "tick", "index": index})
    assert q.qsize() <= 8
```

Also test that an unauthenticated request to `/api/v1/web/events` returns 401 before streaming begins.

- [ ] **Step 2: Implement a bounded fan-out broker**

```python
class WebEventBroker:
    def __init__(self, max_queue: int = 32):
        self.max_queue = max_queue
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for target in subscribers:
            if target.full():
                try:
                    target.get_nowait()
                except queue.Empty:
                    pass
            target.put_nowait(event)
```

- [ ] **Step 3: Serve SSE with heartbeat and cleanup**

Use FastAPI `StreamingResponse` with `text/event-stream`; emit `event: update` JSON frames plus a lightweight heartbeat so dead connections are released.

- [ ] **Step 4: Connect React without a Node runtime**

Add an `EventSource("/api/v1/web/events")` helper. On update events, Viewer pages refetch the relevant REST read model; do not push full historical datasets through SSE.

- [ ] **Step 5: Verify bounded-memory behavior and frontend build**

Run:

```bash
pytest -q tests/test_web_events.py tests/test_web_api.py
cd web && npm run check && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add radmon/web_events.py radmon/central_service.py radmon/web_api.py web/src/api.ts web/src/pages/OverviewPage.tsx tests/test_web_events.py
git commit -m "feat: add lightweight authenticated web events"
```

---

### Task 7: Complete Operator Alarm, ACK, and Suppression Web Parity

**Files:**
- Create: `web/src/pages/AlarmsPage.tsx`
- Refactor: `web/src/Actions.tsx`
- Modify: `web/src/App.tsx`
- Modify: `tests/test_web_role_matrix.py`
- Modify: `tests/test_alarm_policy_api.py`
- Modify: `tests/test_alarm_suppression.py`

**Interfaces:**
- Consumes: existing protected control APIs for alarm events, response/ACK, and suppression; existing PIN policy remains authoritative.
- Produces: Operator UI actions only; no new client-side alarm semantics.

- [ ] **Step 1: Add explicit role tests for every Operator mutation**

For each mutation endpoint, assert Viewer=403, Operator=success with valid PIN, Administrator=success with valid PIN, and anonymous=401.

- [ ] **Step 2: Run the focused backend tests**

Run:

```bash
pytest -q tests/test_web_role_matrix.py tests/test_alarm_policy_api.py tests/test_alarm_suppression.py
```

- [ ] **Step 3: Refactor action forms into explicit Kumo dialogs**

The browser submits the same required fields as desktop policy: event/detector identity, PIC, action/reason, duration/auto-resume where relevant, and PIN. Never cache PIN in localStorage/sessionStorage.

- [ ] **Step 4: Refresh authoritative state after each action**

After a successful REST mutation, close the dialog, clear PIN state, and reload `/api/v1/control/alarm-events`; SSE can trigger additional refreshes but is not the source of truth.

- [ ] **Step 5: Verify no Viewer controls leak into the rendered navigation/page**

Use the role-filtered router and TypeScript checks; backend tests remain the security guarantee.

- [ ] **Step 6: Verify**

Run:

```bash
pytest -q tests/test_alarm_policy_api.py tests/test_alarm_suppression.py tests/test_web_role_matrix.py
cd web && npm run check && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/AlarmsPage.tsx web/src/Actions.tsx web/src/App.tsx tests/test_web_role_matrix.py tests/test_alarm_policy_api.py tests/test_alarm_suppression.py
git commit -m "feat: add Operator alarm web controls"
```

---

### Task 8: Complete Administrator Web Parity for Users, Stations, and Diagnostics

**Files:**
- Create: `web/src/pages/UsersPage.tsx`
- Create: `web/src/pages/SystemPage.tsx`
- Modify: `radmon/web_api.py`
- Modify: `web/src/App.tsx`
- Modify: `web/src/Actions.tsx`
- Modify: `tests/test_web_role_matrix.py`
- Modify: `tests/test_secure_api.py`

**Interfaces:**
- Consumes: existing security user-management and device/station administration services exposed through secure APIs.
- Produces: Administrator-only pages; `GET /api/v1/web/system` returns source health and `grafana_admin_url` without exposing credentials.

- [ ] **Step 1: Write Administrator boundary tests**

```python
def test_grafana_admin_url_is_admin_only(viewer_client, admin_client):
    assert viewer_client.get("/api/v1/web/system").status_code == 403
    payload = admin_client.get("/api/v1/web/system").json()
    assert payload["grafana_admin_url"] == "http://localhost:3300"
    assert "password" not in str(payload).lower()
```

- [ ] **Step 2: Run focused tests and capture missing parity**

Run: `pytest -q tests/test_web_role_matrix.py tests/test_secure_api.py`

- [ ] **Step 3: Implement Kumo user and system pages**

`UsersPage` uses existing create/list/enable-disable semantics and never displays password hashes. `SystemPage` shows source health, runtime diagnostics, and an explicit “Open Grafana editor on server” link/instruction for Administrator.

- [ ] **Step 4: Keep station configuration mutations behind Administrator + existing sensitive-operation checks**

Do not add a browser-only bypass. Reuse server APIs and PIN/lease rules already used by the desktop station administration flow.

- [ ] **Step 5: Verify**

Run:

```bash
pytest -q tests/test_secure_api.py tests/test_web_role_matrix.py tests/test_security.py
cd web && npm run check && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add radmon/web_api.py web/src/pages/UsersPage.tsx web/src/pages/SystemPage.tsx web/src/App.tsx web/src/Actions.tsx tests/test_web_role_matrix.py tests/test_secure_api.py
git commit -m "feat: add Administrator web control plane"
```

---

### Task 9: Package the Static Kumo App into `RadMon.exe`

**Files:**
- Modify: `RadMon.spec`
- Modify: `.github/workflows/windows-build.yml`
- Modify: `tests/test_bundle.py`
- Modify: `tests/test_windows_packaging.py`

**Interfaces:**
- Consumes: `web/dist` from Task 1.
- Produces: packaged `RadMon.exe` where `bundled_web_dist()` resolves to bundled static assets and no Node runtime exists in the installed application.

- [ ] **Step 1: Add a failing packaging test**

```python
def test_pyinstaller_bundles_compiled_web_not_node_sources():
    spec = (ROOT / "RadMon.spec").read_text(encoding="utf-8")
    assert "web/dist" in spec.replace("\\", "/")
    assert "node_modules" not in spec
```

- [ ] **Step 2: Make the Windows workflow build web assets before PyInstaller**

Use `actions/setup-node@v4`, `npm ci`, `npm run check`, and `npm run build` before the existing PyInstaller step.

- [ ] **Step 3: Add `web/dist` to PyInstaller data**

The spec must map compiled assets to runtime `web/`; it must not bundle `web/src`, `node_modules`, npm cache, or TypeScript sources.

- [ ] **Step 4: Extend packaged smoke testing**

After building/installing, run existing `RadMon.exe --smoke-test` and assert the installed static web index exists in the bundled runtime path.

- [ ] **Step 5: Verify locally where possible and through Windows CI**

Run Linux-safe contract tests locally:

```bash
pytest -q tests/test_bundle.py tests/test_windows_packaging.py
```

Expected Windows Actions outcome: PyInstaller succeeds and packaged smoke test succeeds.

- [ ] **Step 6: Commit**

```bash
git add RadMon.spec .github/workflows/windows-build.yml tests/test_bundle.py tests/test_windows_packaging.py
git commit -m "build: bundle Kumo web app into RadMon"
```

---

### Task 10: Replace Interactive Startup Ownership with Real Windows Service Supervision

**Files:**
- Create: `packaging/RadMon.Service.xml`
- Create: `packaging/Grafana.Service.xml`
- Modify: `packaging/install_server.ps1`
- Modify: `packaging/RadMon.iss`
- Modify: `.github/workflows/windows-build.yml`
- Create: `tests/test_windows_service_packaging.py`
- Modify: `tests/test_server_mode.py`

**Interfaces:**
- Consumes: `RadMon.exe --server`; native Grafana path from `RADMON_GRAFANA_BIN` or detected standard install locations.
- Produces: auto-start service `RadMonServer`; optional managed service `RadMonGrafana` when a native Grafana executable is available; restart-on-failure; no interactive desktop dependency.

- [ ] **Step 1: Write service packaging contracts first**

```python
def test_radmon_service_runs_headless_server_mode():
    xml = (ROOT / "packaging" / "RadMon.Service.xml").read_text(encoding="utf-8")
    assert "<id>RadMonServer</id>" in xml
    assert "--server" in xml
    assert "<startmode>Automatic</startmode>" in xml
    assert "<onfailure action=\"restart\"" in xml
```

Also assert the installer does not create the legacy Scheduled Task as the final ownership mechanism.

- [ ] **Step 2: Bundle a pinned WinSW executable in Windows CI**

Download a pinned WinSW x64 release during the build and rename copies to `RadMon.Service.exe` and `Grafana.Service.exe` before compiling the installer. Pin the exact URL/version in workflow YAML; do not download anything during production startup.

- [ ] **Step 3: Define the RadMon service**

`packaging/RadMon.Service.xml`:

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

Adjust `%BASE%` layout to the actual installer output and cover it with the packaging test.

- [ ] **Step 4: Define Grafana service ownership without bundling Grafana itself**

`Grafana.Service.xml` points to the detected/configured native `grafana-server.exe`, sets the working directory/config environment, and uses automatic restart. If Grafana is not installed, the installer leaves RadMon installed but reports that monitoring cannot start until native Grafana is installed/configured.

- [ ] **Step 5: Replace Scheduled Task registration in `install_server.ps1`**

Use service wrapper commands:

```powershell
& "$InstallRoot\RadMon.Service.exe" stop 2>$null
& "$InstallRoot\RadMon.Service.exe" uninstall 2>$null
& "$InstallRoot\RadMon.Service.exe" install
& "$InstallRoot\RadMon.Service.exe" start
```

Keep idempotent firewall rules for TCP 8090 and 3300 limited to `LocalSubnet`.

- [ ] **Step 6: Verify server mode remains headless**

`tests/test_server_mode.py` must assert `run_server()` owns central start/stop and does not call `run_admin_ui` or launch a browser.

- [ ] **Step 7: Verify packaging tests and Windows build**

Run:

```bash
pytest -q tests/test_server_mode.py tests/test_windows_service_packaging.py tests/test_windows_packaging.py
```

Then require Windows Actions to compile installer and execute silent install/service-file smoke checks.

- [ ] **Step 8: Commit**

```bash
git add packaging/RadMon.Service.xml packaging/Grafana.Service.xml packaging/install_server.ps1 packaging/RadMon.iss .github/workflows/windows-build.yml tests/test_windows_service_packaging.py tests/test_server_mode.py
git commit -m "feat: run RadMon as an automatic Windows service"
```

---

### Task 11: Harden Installer Persistence for Grafana, Config, Runtime, Archives, and Reports

**Files:**
- Modify: `packaging/RadMon.iss`
- Modify: `radmon/paths.py`
- Modify: `radmon/grafana_persistent.py`
- Modify: `tests/test_windows_packaging.py`
- Modify: `tests/test_grafana_persistence.py`

**Interfaces:**
- Consumes: external application paths and native Grafana data environment.
- Produces: update-safe install where application binaries/static assets are replaceable but operator config and state survive install/update/uninstall unless explicitly removed.

- [ ] **Step 1: Write persistence assertions first**

Assert installer scripts never delete or overwrite these directories during normal upgrade:

```text
config/
runtime/
runtime/grafana/data/
archives/
reports/
```

and never replace an existing production `.env` with `.env.example`.

- [ ] **Step 2: Keep Grafana data path external to replaceable application files**

`PersistentGrafanaBootstrap._native_environment()` must resolve `GF_PATHS_DATA` from the external runtime path supplied through `Settings.for_application_paths()`.

- [ ] **Step 3: Make installer upgrade idempotent**

Install new `app/` binaries and web assets, preserve external directories, reinstall/update service definitions, then restart services. Do not perform dashboard import during installer execution; application seed-once bootstrap handles missing resources.

- [ ] **Step 4: Verify**

Run:

```bash
pytest -q tests/test_windows_packaging.py tests/test_grafana_persistence.py tests/test_paths.py
```

- [ ] **Step 5: Commit**

```bash
git add packaging/RadMon.iss radmon/paths.py radmon/grafana_persistent.py tests/test_windows_packaging.py tests/test_grafana_persistence.py
git commit -m "fix: preserve Grafana and RadMon state across upgrades"
```

---

### Task 12: Tune the Runtime for the Fixed 6 GB Windows Server

**Files:**
- Modify: `radmon/production_app.py`
- Modify: `radmon/logging_setup.py`
- Modify: `.env.example`
- Test: `tests/test_server_mode.py`
- Test: `tests/test_logging.py`

**Interfaces:**
- Consumes: `run_server()`, existing logging setup and LAN poll settings.
- Produces: one RadMon backend process, bounded logs, no browser/UI launch, no Docker fallback, predictable memory behavior.

- [ ] **Step 1: Write contracts for server-mode resource discipline**

Assert `run_server()` never calls `webbrowser.open`, `run_admin_ui`, Selenium unless WhatsApp is explicitly enabled, or Docker compose by default.

- [ ] **Step 2: Make production defaults explicit in `.env.example`**

Include:

```env
RADMON_GRAFANA_DOCKER_FALLBACK=0
RADMON_WEB_COOKIE_SECURE=0
RADMON_GRAFANA_FALLBACK_PORT=3300
RADMON_LAN_POLL_INTERVAL=2
RADMON_WHATSAPP_ENABLED=0
```

Do not turn HTTPS-cookie mode on until HTTPS/reverse proxy is actually deployed.

- [ ] **Step 3: Bound log retention**

Use rotating file logging with a fixed max size/file count appropriate to the existing disk, e.g. 10 MB × 5 files per primary service logger, rather than unbounded log growth.

- [ ] **Step 4: Verify headless behavior**

Run:

```bash
pytest -q tests/test_server_mode.py tests/test_logging.py
```

- [ ] **Step 5: Commit**

```bash
git add radmon/production_app.py radmon/logging_setup.py .env.example tests/test_server_mode.py tests/test_logging.py
git commit -m "perf: bound RadMon server runtime for 6GB Windows host"
```

---

### Task 13: Update Operational Documentation for the Web-First Platform

**Files:**
- Modify: `README.md`
- Modify: `docs/INSTALLATION.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/manual/installation.html`
- Modify: `docs/manual/user-manual.html`
- Modify: `grafana/README.md`
- Test: existing documentation/runtime-resource tests.

**Interfaces:**
- Produces: exact operator SOP for anonymous monitoring, authenticated app, Grafana editing, restart persistence, Windows service status/recovery, and update procedure.

- [ ] **Step 1: Update the route model exactly**

Document:

```text
http://<server>:8090/      -> redirects to full Grafana kiosk monitoring
http://<server>:8090/app   -> RadMon login and role-based application
http://localhost:3300      -> Grafana editor/login on the server
```

State explicitly that Viewer still requires RadMon login and anonymous access is monitoring-only.

- [ ] **Step 2: Document dashboard persistence**

State that saved Grafana dashboards are authoritative, startup does not overwrite them, and reset-to-factory is not automatic.

- [ ] **Step 3: Document Windows service operations**

Include exact Administrator PowerShell commands matching the installed service names, for example:

```powershell
Get-Service RadMonServer
Restart-Service RadMonServer
Get-Service RadMonGrafana
```

Only document commands that the final installer actually creates.

- [ ] **Step 4: Document hardware/OS constraint honestly**

State the deployed server is the existing Windows 10 Enterprise Dell i5-4460/6 GB host, and that the implementation is intentionally lightweight. Do not claim the old OS is security-supported; BRIN network restriction remains a required deployment control.

- [ ] **Step 5: Run doc/runtime tests**

Run the existing manual/document tests plus:

```bash
pytest -q tests/test_docs.py tests/test_bundle.py
```

(adjust to the actual existing documentation-test filenames discovered in the repository; do not invent a new duplicate test file if the repository already has one).

- [ ] **Step 6: Commit**

```bash
git add README.md docs grafana/README.md
git commit -m "docs: document RadMon web platform operations"
```

---

### Task 14: Full Regression, Windows Installer Verification, and Temporary-Artifact Cleanup

**Files:**
- Delete: `docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md`
- Delete: `docs/superpowers/plans/2026-09-13-radmon-web-platform.md`
- Verify: entire repository and release artifact.

**Interfaces:**
- Consumes: every previous task.
- Produces: a merge-ready `feature` branch with no temporary engineering docs, full Python/web/Windows gates green, and only `main`/`feature` persistent branches.

- [ ] **Step 1: Run the full Python regression suite from a fresh environment**

Run:

```bash
python -m pytest -q
python -m compileall -q radmon packaging
```

Expected: zero failures.

- [ ] **Step 2: Run a clean frontend build**

Run:

```bash
cd web
npm ci
npm run check
npm run build
```

Expected: zero TypeScript errors and a fresh `web/dist`.

- [ ] **Step 3: Run Grafana-specific regression**

Run:

```bash
pytest -q tests/test_grafana_persistence.py tests/test_grafana_landing.py tests/test_grafana_tv.py
```

Expected: existing saved dashboards generate zero normal-start dashboard overwrite writes; missing resources seed once.

- [ ] **Step 4: Require Windows GitHub Actions to prove the installed artifact**

The `windows-build.yml` job must demonstrate:

1. frontend `npm ci/check/build` success;
2. PyInstaller `RadMon.exe` build success;
3. Inno Setup `RadMon-Setup.exe` build success;
4. silent install success;
5. packaged `RadMon.exe --smoke-test` success;
6. service wrapper/config files installed;
7. no `.bat`, source `.py`, test tree, `node_modules`, or temporary design docs in release payload.

- [ ] **Step 5: Remove temporary spec and plan only after all gates are green**

```bash
git rm docs/superpowers/specs/2026-09-13-radmon-web-platform-design.md
git rm docs/superpowers/plans/2026-09-13-radmon-web-platform.md
git commit -m "chore: remove temporary web platform planning docs"
```

- [ ] **Step 6: Verify branch policy**

Confirm GitHub shows only persistent branches:

```text
main
feature
```

- [ ] **Step 7: Final commissioning checklist on the Dell server**

After installing the verified artifact on the production Dell, collect evidence for each item rather than assuming CI proves field wiring:

```text
[ ] RadMonServer starts automatically after Windows boot
[ ] Native Grafana starts automatically and stays on configured port 3300
[ ] / is reachable from an allowed BRIN-LAN client and shows only Grafana kiosk monitoring
[ ] /app requires login even for Viewer
[ ] Viewer cannot call Operator/Admin actions
[ ] Operator ACK and suppression work against production policy
[ ] Administrator management operations work
[ ] editing a Grafana dashboard at localhost:3300 changes the anonymous monitoring presentation
[ ] saved Grafana edit survives RadMon service restart
[ ] saved Grafana edit survives Grafana restart
[ ] saved Grafana edit survives Windows restart
[ ] update install preserves .env, SQLite/runtime, archives, reports, and Grafana data
[ ] source .50/.52/.38 remain read/write-compatible with no schema mutation
```

Do not claim commissioning complete until this checklist is executed on the physical server.
