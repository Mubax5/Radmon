# RadMon Responsive Mobile-First UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the authenticated RadMon web control plane into a compact, robust, mobile-first application with a native-app-style mobile shell while preserving and improving the desktop Kumo control-plane experience.

**Architecture:** Keep one shared React/FastAPI application, shared routes, shared authenticated API state, and shared RBAC. Introduce adaptive presentation boundaries: a desktop/tablet Kumo sidebar shell and a mobile shell with sticky top bar, role-aware bottom navigation, and a More sheet. Data-heavy pages use shared typed data with desktop tables/grids and mobile cards/lists; History uses a dependency-free SVG trend chart. REST remains authoritative and SSE remains a refresh hint.

**Tech Stack:** React 19, TypeScript 5.7, Vite 6, `@cloudflare/kumo` 2.13.2, FastAPI, pytest. No new production/runtime dependency and no new frontend package is required.

**Spec:** `docs/superpowers/specs/2026-09-14-radmon-responsive-mobile-ui-design.md`

## Global Constraints

- Breakpoints are exactly `< 640 px` mobile, `640-1023 px` tablet/adaptive, and `>= 1024 px` desktop control plane.
- Base CSS is mobile-first; larger layouts progressively enhance from the mobile base.
- BRIN logo remains the only product brand mark; no decorative letter `R` badges/icons and no duplicate BRIN wordmark outside the logo.
- Do not reintroduce decorative navigation icons.
- Keep server-side RBAC authoritative; frontend role filtering is only a usability layer.
- Keep REST as source of truth and SSE as refresh hint only.
- Keep source MariaDB schemas unchanged.
- Keep the frontend static-build only; no Node/SSR runtime on the Dell server.
- No heavyweight charting library; History trend chart is a small internal SVG component.
- Preserve browser Back/Forward and deep-route refresh behavior.
- Preserve installer/runtime architecture and existing security/alarm policy semantics.
- Remove `docs/superpowers/specs/...` and `docs/superpowers/plans/...` before final merge/release to preserve the repository cleanup invariant.

---

## File Structure

Create or evolve the frontend toward these boundaries:

- `web/src/navigation.ts` — route metadata, role visibility, path/query navigation helpers, mobile primary/More routing.
- `web/src/responsive.ts` — `useMediaQuery` and `useMobileLayout` only; no business logic.
- `web/src/layout/DesktopShell.tsx` — desktop/tablet Kumo sidebar shell and account/footer actions.
- `web/src/layout/MobileShell.tsx` — mobile top bar, bottom navigation, safe content shell.
- `web/src/layout/MobileMoreSheet.tsx` — role-filtered More dialog/sheet and account actions.
- `web/src/layout.tsx` — compatibility facade exporting `AppLayout`, `AppRoute`, `useAppRoute`, and navigation helpers to minimize page churn.
- `web/src/components/ResponsiveDataView.tsx` — presentation switch between desktop and mobile representations without duplicate fetching.
- `web/src/components/StationViews.tsx` — station table, station cards, station detail summary.
- `web/src/components/TrendChart.tsx` — dependency-free accessible SVG dose-rate trend chart.
- `web/src/ui.tsx` — common headings, status badge mapping, metric/page section primitives, loading/error/empty surfaces.
- `web/src/radmon.css` — mobile-first spacing, viewport, shell, responsive data, sheet/dialog, motion, overflow rules.
- Existing pages under `web/src/pages/` — page-specific composition and data flow.
- `web/src/Actions.tsx` — mutation pending states, dialog workflow, secret-field clearing.
- `web/src/api.ts` / `web/src/auth.tsx` — session-expiry propagation and clean login redirect.
- `tests/test_web_responsive_ui_contract.py` — static/runtime contracts for responsive shell, no `R` badges/icons, breakpoints, role navigation, deep links, and no unsafe viewport CSS.

---

### Task 1: Lock Responsive and Workflow Contracts With Failing Tests

**Files:**
- Create: `tests/test_web_responsive_ui_contract.py`
- Modify: none

**Interfaces:**
- Consumes: current `web/src` source tree.
- Produces: regression contracts used by every later task.

- [ ] **Step 1: Write failing source-contract tests**

Create tests that assert the planned boundaries exist and reject the current desktop-first implementation:

```python
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_adaptive_shell_files_exist_and_mobile_navigation_is_role_aware():
    assert (WEB / "layout/DesktopShell.tsx").exists()
    assert (WEB / "layout/MobileShell.tsx").exists()
    assert (WEB / "layout/MobileMoreSheet.tsx").exists()
    nav = read("navigation.ts")
    assert 'Viewer' in nav and 'Operator' in nav and 'Administrator' in nav
    assert 'Overview' in nav and 'Stations' in nav and 'History' in nav and 'Alarms' in nav and 'More' in nav


def test_mobile_first_css_has_exact_breakpoints_safe_areas_and_no_unsafe_page_width():
    css = read("radmon.css")
    assert "100dvh" in css
    assert "env(safe-area-inset-bottom" in css
    assert "@media (min-width: 640px)" in css
    assert "@media (min-width: 1024px)" in css
    assert "@media (max-width: 640px)" not in css
    assert "100vw" not in css
    assert "prefers-reduced-motion" in css


def test_mobile_and_desktop_data_presentations_are_explicit():
    source = read("components/ResponsiveDataView.tsx")
    assert "desktop" in source
    assert "mobile" in source
    station = read("components/StationViews.tsx")
    assert "StationTable" in station
    assert "StationCards" in station


def test_history_has_dependency_free_svg_trend_chart():
    chart = read("components/TrendChart.tsx")
    package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    assert "<svg" in chart
    assert "polyline" in chart or "path" in chart
    assert "recharts" not in package.lower()
    assert "chart.js" not in package.lower()


def test_control_plane_never_reintroduces_letter_r_brand_badges_or_phosphor_nav_icons():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in WEB.rglob("*.tsx"))
    assert re.search(r">\s*R\s*<", combined) is None
    layout_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (WEB / "layout").glob("*.tsx")
    ) if (WEB / "layout").exists() else ""
    assert "@phosphor-icons/react" not in layout_sources
```

Also assert thin pages gain relevant composition markers:

```python
def test_pages_have_relevant_compact_sections():
    assert "attention" in read("pages/OverviewPage.tsx").lower()
    assert "station-search" in read("pages/StationsPage.tsx")
    assert "history-summary" in read("pages/HistoryPage.tsx")
    assert "archive-summary" in read("pages/ArchivesPage.tsx")
    assert "active-alarm" in read("pages/AlarmsPage.tsx")
    assert "user-summary" in read("pages/UsersPage.tsx")
    assert "source-health" in read("pages/SystemPage.tsx")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
```

Expected: FAIL because adaptive shell/component files and mobile-first CSS do not exist yet.

- [ ] **Step 3: Commit the red tests**

```bash
git add tests/test_web_responsive_ui_contract.py
git commit -m "test: define responsive mobile UI contracts"
```

---

### Task 2: Build Shared Navigation and Adaptive Shells

**Files:**
- Create: `web/src/navigation.ts`
- Create: `web/src/responsive.ts`
- Create: `web/src/layout/DesktopShell.tsx`
- Create: `web/src/layout/MobileShell.tsx`
- Create: `web/src/layout/MobileMoreSheet.tsx`
- Modify: `web/src/layout.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_responsive_ui_contract.py`

**Interfaces:**
- Produces: `AppRoute`, `NAV_ITEMS`, `roleAllows`, `routeFromLocation`, `navigate`, `mobilePrimaryRoutes`; `useMobileLayout`; adaptive `AppLayout`.
- Consumes: `SessionUser`, Kumo `Sidebar`, `Button`, `Dialog`, BRIN logo asset.

- [ ] **Step 1: Add navigation primitives**

Implement `web/src/navigation.ts` with exact shared route metadata:

```ts
import type { Role } from "./api";

export type AppRoute = "overview" | "stations" | "history" | "archives" | "alarms" | "users" | "system";
export type NavItem = { id: AppRoute; label: string; minimum: Role };

export const ROLE_RANK: Record<Role, number> = { Viewer: 1, Operator: 2, Administrator: 3 };
export const NAV_ITEMS: readonly NavItem[] = [
  { id: "overview", label: "Overview", minimum: "Viewer" },
  { id: "stations", label: "Stations", minimum: "Viewer" },
  { id: "history", label: "History", minimum: "Viewer" },
  { id: "archives", label: "Archives", minimum: "Viewer" },
  { id: "alarms", label: "Alarms", minimum: "Operator" },
  { id: "users", label: "Users", minimum: "Administrator" },
  { id: "system", label: "System", minimum: "Administrator" },
] as const;

export function roleAllows(role: Role, minimum: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export function routeFromLocation(): AppRoute {
  const part = window.location.pathname.replace(/^\/app\/?/, "").split("/")[0];
  const route = (part && part !== "login" ? part : "overview") as AppRoute;
  return NAV_ITEMS.some((item) => item.id === route) ? route : "overview";
}

export function navigate(route: AppRoute, query?: Record<string, string | number | undefined>): void {
  const pathname = route === "overview" ? "/app" : `/app/${route}`;
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value));
  });
  const suffix = params.size ? `?${params.toString()}` : "";
  window.history.pushState({}, "", `${pathname}${suffix}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function mobilePrimaryRoutes(role: Role): Array<AppRoute | "more"> {
  return role === "Viewer"
    ? ["overview", "stations", "history", "more"]
    : ["overview", "stations", "alarms", "more"];
}
```

- [ ] **Step 2: Add a stable media-query hook**

Implement `web/src/responsive.ts`:

```ts
import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

export function useMobileLayout(): boolean {
  return useMediaQuery("(max-width: 639px)");
}
```

- [ ] **Step 3: Implement desktop and mobile shells**

`DesktopShell` retains Kumo Sidebar and text-only navigation. `MobileShell` renders only on mobile and includes top bar + role-aware bottom navigation + `MobileMoreSheet`. Both receive the same contract:

```ts
export type ShellProps = {
  user: SessionUser;
  route: AppRoute;
  onSignOut: () => Promise<void>;
  children: ReactNode;
};
```

Use BRIN logo with preserved aspect ratio. Do not import Phosphor icons.

- [ ] **Step 4: Turn `layout.tsx` into the compatibility facade**

Keep existing imports stable:

```tsx
export function AppLayout(props: ShellProps) {
  const mobile = useMobileLayout();
  return mobile ? <MobileShell {...props} /> : <DesktopShell {...props} />;
}
```

Keep `useAppRoute` role-aware using `NAV_ITEMS` and `roleAllows`.

- [ ] **Step 5: Replace shell CSS with mobile-first viewport rules**

Base rules must include:

```css
html, body, #root { margin: 0; min-height: 100%; }
body { min-height: 100dvh; overflow-x: hidden; }
.app-shell { min-height: 100dvh; width: 100%; }
.mobile-shell { min-height: 100dvh; display: flex; flex-direction: column; }
.mobile-topbar { position: sticky; top: 0; z-index: 30; }
.mobile-content {
  flex: 1;
  min-width: 0;
  padding: 12px 12px calc(84px + env(safe-area-inset-bottom));
}
.mobile-bottom-nav {
  position: fixed;
  left: 0; right: 0; bottom: 0;
  z-index: 40;
  padding-bottom: env(safe-area-inset-bottom);
}

@media (min-width: 640px) { /* tablet rules */ }
@media (min-width: 1024px) { /* desktop rules */ }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
```

No `100vw` and no `max-width` breakpoint rules.

- [ ] **Step 6: Run focused tests and frontend build**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
cd web && npm run check && npm run build
```

Expected: shell/breakpoint/navigation assertions pass; page-composition assertions may remain RED until later tasks.

- [ ] **Step 7: Commit**

```bash
git add web/src/navigation.ts web/src/responsive.ts web/src/layout web/src/layout.tsx web/src/radmon.css tests/test_web_responsive_ui_contract.py
git commit -m "feat: add adaptive desktop and mobile shells"
```

---

### Task 3: Add Shared Responsive Data and UI Primitives

**Files:**
- Create: `web/src/components/ResponsiveDataView.tsx`
- Create: `web/src/components/StationViews.tsx`
- Create: `web/src/components/TrendChart.tsx`
- Modify: `web/src/ui.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_responsive_ui_contract.py`

**Interfaces:**
- Produces: `ResponsiveDataView`, `StationTable`, `StationCards`, `StationDetail`, `TrendChart`, `PageSection`, `MetricCard`, `formatTimestamp`, `freshnessLabel`.
- Consumes: `Station`, `useMobileLayout`, Kumo `Badge`, `LayerCard`, `Table`, `Button`.

- [ ] **Step 1: Implement responsive data presentation**

```tsx
export function ResponsiveDataView({ desktop, mobile }: { desktop: ReactNode; mobile: ReactNode }) {
  return useMobileLayout() ? <>{mobile}</> : <>{desktop}</>;
}
```

This switches presentation only; pages own fetching and pass the same typed dataset into both views.

- [ ] **Step 2: Move station rendering into `StationViews.tsx`**

Implement table and mobile cards from the same `Station[]`. Mobile card content must include station name, location, status badge, dose rate, updated/freshness, and optional `onOpen(station)` / `onHistory(station)` actions. Keep every primary touch action at least 44 px via CSS.

- [ ] **Step 3: Add dependency-free trend chart**

`TrendChart` accepts:

```ts
export type TrendPoint = { at: string; value: number };
export function TrendChart({ points, unit }: { points: TrendPoint[]; unit: string }): JSX.Element;
```

Use `viewBox="0 0 640 220"`, normalize min/max values, and generate a `<polyline>` string. For zero/one point, render an accessible empty/single-state instead of invalid geometry. Include `<title>Dose rate trend</title>` and a text summary for screen readers.

- [ ] **Step 4: Expand common UI helpers**

Add:

```ts
export function formatTimestamp(value?: string | null): string;
export function freshnessLabel(value?: string | null): string;
export function PageSection({ title, description, action, children }: ...): JSX.Element;
export function MetricCard({ label, value, badge, className }: ...): JSX.Element;
```

Keep `LoadingCard`, `ErrorCard`, and `JsonTable` for compatibility, but pages migrated later should prefer explicit domain views over raw JSON tables.

- [ ] **Step 5: Add shared compact/mobile CSS**

Define stable classes for `.page-stack`, `.page-section`, `.metric-grid`, `.mobile-card-list`, `.station-card`, `.station-detail`, `.responsive-table`, `.trend-chart`, `.skeleton-block`, long text wrapping, and internal table scrolling. Base grid is one/two compact columns on mobile and progressively enhances at 640/1024.

- [ ] **Step 6: Verify**

```bash
cd web && npm run check && npm run build
cd .. && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
```

- [ ] **Step 7: Commit**

```bash
git add web/src/components web/src/ui.tsx web/src/radmon.css tests/test_web_responsive_ui_contract.py
git commit -m "feat: add responsive data presentation primitives"
```

---

### Task 4: Recompose Overview and Stations Into Operational Workspaces

**Files:**
- Modify: `web/src/pages/OverviewPage.tsx`
- Modify: `web/src/pages/StationsPage.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_responsive_ui_contract.py`

**Interfaces:**
- Consumes: `/api/v1/web/overview`, `ResponsiveDataView`, station views, `navigate("history", { station })`.
- Produces: compact operational Overview and searchable/filterable Stations page.

- [ ] **Step 1: Upgrade Overview composition**

Keep one overview fetch. Derive:

```ts
const attention = data.stations.filter((s) => s.status !== "normal");
const timestamps = data.stations.flatMap((s) => s.dtom ? [Date.parse(s.dtom)] : []);
const latest = timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null;
```

Render in this order:

1. `PageHeading`.
2. 2x2/4-column status metrics.
3. `PageSection` with class `attention-panel`; show Warning/Alarm/Offline cards first or a compact “No stations need attention” state.
4. Freshness summary card using `latest`.
5. Responsive station view.

Do not duplicate API fetching for mobile.

- [ ] **Step 2: Upgrade Stations composition**

Fetch `/api/v1/web/overview` instead of metadata-only `/api/v1/web/stations` so current dose/status/freshness are available. Maintain states:

```ts
const [query, setQuery] = useState("");
const [status, setStatus] = useState<"all" | Station["status"]>("all");
const [selected, setSelected] = useState<number | null>(null);
```

Filter name/location/SERID case-insensitively. Add marker class `station-search`. Desktop shows responsive list/table plus detail panel for selection. Mobile shows cards and an in-page/detail sheet surface. `View history` calls `navigate("history", { station: station.serid })`.

- [ ] **Step 3: Add compact filter/detail CSS**

Ensure search/action rows wrap, no overlap at 360 px, selected detail has `min-width: 0`, and tablet/desktop split uses `grid-template-columns: minmax(0, 1fr) minmax(260px, 340px)` only when space permits.

- [ ] **Step 4: Verify**

```bash
cd web && npm run check && npm run build
cd .. && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
```

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/OverviewPage.tsx web/src/pages/StationsPage.tsx web/src/radmon.css tests/test_web_responsive_ui_contract.py
git commit -m "feat: make overview and stations operationally compact"
```

---

### Task 5: Upgrade History and Archives With Compact Context

**Files:**
- Modify: `web/src/pages/HistoryPage.tsx`
- Modify: `web/src/pages/ArchivesPage.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_responsive_ui_contract.py`

**Interfaces:**
- Consumes: `/api/v1/web/stations`, `/api/v1/web/stations/{serid}/history`, `/api/v1/control/archives`, `TrendChart`, `ResponsiveDataView`.
- Produces: linked station history workflow, trend/stats, archive summary/filter/cards.

- [ ] **Step 1: Make History respect `?station=` deep links**

Read query once station metadata is available:

```ts
const requested = Number(new URLSearchParams(window.location.search).get("station"));
const initial = items.some((item) => item.serid === requested) ? requested : items[0]?.serid ?? null;
setSelected(initial);
```

On selector change, update the current History URL with `history?station=<serid>` using `history.replaceState`, without resetting route state.

- [ ] **Step 2: Compute History summary and chart points**

Normalize rows with numeric `doserate`, derive latest/min/max/average, and add marker class `history-summary`. Render `TrendChart` before the record view. Mobile uses chronological cards; desktop/tablet uses table.

- [ ] **Step 3: Recompose Archives**

Derive summary without backend changes:

```ts
const complete = items.filter((item) => String(item.state) === "COMPLETE").length;
const latestQuarter = items.map((item) => String(item.quarter_id ?? "")).filter(Boolean).sort().at(-1) ?? "—";
const years = [...new Set(items.map((item) => /^([0-9]{4})-Q/.exec(String(item.quarter_id ?? ""))?.[1]).filter(Boolean))];
```

Add marker class `archive-summary`. Filter by year when the quarter id supports it. Desktop uses explicit archive columns; mobile uses archive cards. Do not invent verification fields that are not present.

- [ ] **Step 4: Verify**

```bash
cd web && npm run check && npm run build
cd .. && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
```

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/HistoryPage.tsx web/src/pages/ArchivesPage.tsx web/src/radmon.css tests/test_web_responsive_ui_contract.py
git commit -m "feat: add responsive history and archive context"
```

---

### Task 6: Make Alarm and User Workflows Safe, Compact, and Mobile-Friendly

**Files:**
- Modify: `web/src/Actions.tsx`
- Modify: `web/src/pages/AlarmsPage.tsx`
- Modify: `web/src/pages/UsersPage.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_responsive_ui_contract.py`

**Interfaces:**
- Consumes: existing alarm response/suppression and user-create endpoints unchanged.
- Produces: pending-safe mutation dialogs, active-alarm-first page, user summary + dialog creation.

- [ ] **Step 1: Add mutation pending state to `AlarmOperations`**

Use separate booleans or a single operation enum:

```ts
const [pending, setPending] = useState<"respond" | "suppress" | null>(null);
```

Set before each request, clear in `finally`, disable submit/cancel controls while active, and change copy to `Saving…` / `Starting…`. Preserve PIN clearing in every `finally` and reset other fields on successful close.

- [ ] **Step 2: Add pending state to `CreateUserPanel`**

Add `busy`, disable form actions while submitting, preserve secret clearing in `finally`.

Refactor the exported component so Users page can place it inside a Dialog:

```ts
export function CreateUserForm({ onCreated, onDone }: { onCreated: () => void; onDone?: () => void }) { ... }
```

Keep `CreateUserPanel` as a small compatibility wrapper only if another caller exists; otherwise migrate fully.

- [ ] **Step 3: Recompose Alarms**

Derive active events and render:

1. active alarm cards with class `active-alarm-list`;
2. summary metrics (active, retrigger-locked, suppressed/recent where derivable from returned events);
3. `AlarmOperations`;
4. responsive event history.

Mobile action/dialog surfaces must fit `calc(100dvh - 24px - env(safe-area-inset-top) - env(safe-area-inset-bottom))` and scroll internally.

- [ ] **Step 4: Recompose Users**

Derive total/enabled/role counts into `user-summary`. Replace permanent form with a `Create user` button that opens a Kumo Dialog containing `CreateUserForm`. Render user cards on mobile and table on larger viewports.

- [ ] **Step 5: Verify**

```bash
cd web && npm run check && npm run build
cd .. && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
```

- [ ] **Step 6: Commit**

```bash
git add web/src/Actions.tsx web/src/pages/AlarmsPage.tsx web/src/pages/UsersPage.tsx web/src/radmon.css tests/test_web_responsive_ui_contract.py
git commit -m "feat: harden responsive alarm and user workflows"
```

---

### Task 7: Make System Diagnostics Human-Readable and Handle Session Expiry Cleanly

**Files:**
- Modify: `web/src/pages/SystemPage.tsx`
- Modify: `web/src/api.ts`
- Modify: `web/src/auth.tsx`
- Modify: `web/src/radmon.css`
- Test: `tests/test_web_responsive_ui_contract.py`

**Interfaces:**
- Consumes: `/api/v1/web/system` with source fields `source_id`, `host`, `state`, `last_success`, `last_failure`, `last_live_poll`, `last_alarm_poll`, `last_history_import`, `last_error`, `consecutive_failures`, `updated_at`.
- Produces: explicit source health view and `radmon:session-expired` browser event.

- [ ] **Step 1: Replace raw System JSON table with explicit domain view**

Type source health explicitly:

```ts
type SourceHealth = {
  source_id: string;
  host: string;
  state: string;
  last_success?: string | null;
  last_failure?: string | null;
  last_live_poll?: string | null;
  last_alarm_poll?: string | null;
  last_history_import?: string | null;
  last_error?: string | null;
  consecutive_failures: number;
  updated_at?: string | null;
};
```

Derive connected/degraded/offline counts and render class `source-health-summary`; render human-readable cards/table rather than `JsonTable`. Keep Grafana admin action desktop/mobile reachable.

- [ ] **Step 2: Propagate authenticated API expiry**

In `api()` before throwing on 401, dispatch an event except for `/auth/login` and `/auth/me`:

```ts
if (response.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
  window.dispatchEvent(new Event("radmon:session-expired"));
}
```

- [ ] **Step 3: Make AuthProvider react to expiry**

Add an effect:

```ts
useEffect(() => {
  const expire = () => {
    setUser(null);
    window.history.replaceState({}, "", "/app/login");
    window.dispatchEvent(new PopStateEvent("popstate"));
  };
  window.addEventListener("radmon:session-expired", expire);
  return () => window.removeEventListener("radmon:session-expired", expire);
}, []);
```

Do not create a redirect loop for failed login/current-user probes.

- [ ] **Step 4: Verify**

```bash
cd web && npm run check && npm run build
cd .. && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py
```

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/SystemPage.tsx web/src/api.ts web/src/auth.tsx web/src/radmon.css tests/test_web_responsive_ui_contract.py
git commit -m "feat: improve system diagnostics and session expiry flow"
```

---

### Task 8: Final Responsive QA Contracts and Full Regression

**Files:**
- Modify: `tests/test_web_responsive_ui_contract.py`
- Modify: `tests/test_batch2_live_ui_regressions.py` only if assertions reference superseded file locations/classes.
- Modify: no production code unless a failing contract exposes a real defect.

**Interfaces:**
- Consumes: completed responsive frontend.
- Produces: complete source-level regression coverage and verified build/test evidence.

- [ ] **Step 1: Expand final contract coverage**

Add assertions for:

```python
def test_dialogs_and_mobile_navigation_reserve_viewport_space():
    css = read("radmon.css")
    assert "calc(84px + env(safe-area-inset-bottom))" in css
    assert "max-height: calc(100dvh" in css or "height: min(" in css


def test_mutating_forms_have_pending_guards():
    actions = read("Actions.tsx")
    assert "pending" in actions
    assert "disabled={" in actions


def test_session_expiry_returns_to_radmon_login():
    api = read("api.ts")
    auth = read("auth.tsx")
    assert "radmon:session-expired" in api
    assert "radmon:session-expired" in auth
    assert '"/app/login"' in auth


def test_history_route_accepts_station_query_context():
    history = read("pages/HistoryPage.tsx")
    assert 'get("station")' in history
    assert "replaceState" in history
```

Also assert login logo still uses `brin-logo.png`, `.login-brand` remains centered, and no page imports Phosphor icons solely for navigation decoration.

- [ ] **Step 2: Run complete frontend verification**

```bash
cd web
npm ci
npm run check
npm run build
cd ..
```

Expected: all commands exit 0.

- [ ] **Step 3: Run focused and complete Python regression**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_web_responsive_ui_contract.py tests/test_batch2_live_ui_regressions.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
python -m compileall -q radmon packaging
```

Expected: all tests pass; compileall exits 0.

- [ ] **Step 4: Inspect the built frontend payload contract**

Verify `web/dist/index.html` references hashed assets, contains no direct development server URLs, and `web/dist/assets` includes the BRIN logo/bundled CSS/JS. Do not commit `web/dist` if the repo ignores it; Windows packaging builds it in CI.

- [ ] **Step 5: Commit any final test-only adjustments**

```bash
git add tests/test_web_responsive_ui_contract.py tests/test_batch2_live_ui_regressions.py
git commit -m "test: lock responsive RadMon workflows"
```

Skip this commit if no files changed.

---

### Task 9: Windows Packaging Verification, Spec Cleanup, and Release-Ready Branch

**Files:**
- Delete before final merge/release: `docs/superpowers/specs/2026-09-14-radmon-responsive-mobile-ui-design.md`
- Delete before final merge/release: `docs/superpowers/plans/2026-09-14-radmon-responsive-mobile-ui.md`
- No production file changes unless Windows verification exposes a defect.

**Interfaces:**
- Consumes: all prior tasks green on `feature`.
- Produces: release-clean feature branch ready to fast-forward/merge to `main` after verification.

- [ ] **Step 1: Push/observe CI on `feature`**

Require Linux CI success for type-check, Vite build, pytest, compileall, and Grafana payload validation.

- [ ] **Step 2: Require Windows workflow success**

Require success through:

- Build Kumo web frontend
- Build `RadMon.exe`
- Assemble portable layout
- Packaged EXE smoke test
- Build installer
- Installed smoke test
- Installer upgrade over running RadMon
- Installer checksum
- Artifact upload

On `feature`, release publishing is expected to be skipped.

- [ ] **Step 3: Remove temporary Superpowers design/plan files**

```bash
git rm docs/superpowers/specs/2026-09-14-radmon-responsive-mobile-ui-design.md
git rm docs/superpowers/plans/2026-09-14-radmon-responsive-mobile-ui.md
git commit -m "chore: clean temporary UI planning docs"
```

This must happen before `feature` is merged/fast-forwarded into `main`.

- [ ] **Step 4: Re-run cleanup-sensitive tests after doc removal**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```

Expected: all tests pass, including repository cleanup contracts.

- [ ] **Step 5: Final branch verification**

Confirm the only persistent branches remain `main` and `feature`, `feature` contains the complete UI implementation but no `docs/superpowers` artifacts, and the branch is ready for final integration.

---

## Self-Review Result

- Spec coverage: every approved shell, page composition, workflow, branding, motion, session, performance, and cleanup requirement maps to a task above.
- Placeholder scan: no TBD/TODO/“implement later” instructions remain.
- Type consistency: route names, role names, station fields, source-health fields, and shared component signatures are defined once and used consistently.
- Scope: the work is one coherent frontend-control-plane refactor; backend domain/security contracts remain unchanged, so it does not need subdivision into separate product specs.
