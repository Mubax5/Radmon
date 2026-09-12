# RadMon Web Platform Design

## Status
Approved conversational design, written as the implementation gate for the web-first RadMon platform. This file is temporary engineering documentation and must be deleted before the final merge/release, consistent with the repository-cleanup policy.

## Hard Constraints

- Final server remains the existing Dell Inspiron 3847 with Intel i5-4460, 6 GB RAM, existing storage, and the current Windows 10 Enterprise installation/build.
- No hardware or OS upgrade is part of this work.
- Production must be lightweight: no Kubernetes, no Redis, no PostgreSQL, no always-on Node server, and no Docker requirement.
- Existing detector/source MariaDB hosts and schemas remain authoritative legacy sources and must not receive schema migrations.
- Existing RadMon alarm policy, ACK, suppression, archive, reports, audit, and LAN collection semantics remain intact.
- Only `main` and `feature` are allowed as persistent repository branches.

## Product Model

RadMon becomes a web-first internal BRIN platform while the existing desktop application remains available during migration until required web parity is proven.

### Anonymous route

`/` is monitoring only. It must display the full Grafana monitoring experience in kiosk/fullscreen form with no RadMon sign-in button, no application navigation, and no RadMon account controls. Anonymous access is read-only and intended to be restricted to the BRIN network by network/firewall/reverse-proxy policy.

### Authenticated application

`/app` and all `/app/*` routes require RadMon authentication. There is no anonymous Viewer role.

Roles:

- Viewer: authenticated read-only access to permitted RadMon application data and reports.
- Operator: Viewer permissions plus operational alarm response, ACK, suppression, and approved controls.
- Administrator: Operator permissions plus users, station/system configuration, diagnostics, and monitoring administration.

Every permission is enforced server-side. Hiding controls in React is not considered authorization.

## UI System

The authenticated application uses React + TypeScript + Vite with `@cloudflare/kumo` as the primary component system and Phosphor Icons. The visual target is Cloudflare-style control-plane UX using Kumo components and conventions, while keeping RadMon/BRIN branding. Custom CSS is allowed only for layout glue and RadMon-specific visualization needs that Kumo does not provide; it must not replace Kumo with a parallel design system.

Node/Vite is build-time only. Production serves static compiled assets and does not run a Node server.

## Backend

The existing Python backend remains authoritative:

- FastAPI serves authenticated APIs and the compiled web application.
- Existing RadMon services retain LAN collection, alarm policy, source safety, archive, reports, security, and audit behavior.
- SQLite remains the lightweight central application/security/state database for this hardware constraint.
- Realtime browser updates should prefer lightweight server-to-browser mechanisms (SSE where appropriate) and REST for actions. WebSocket is only added where bidirectional realtime is truly required.

## Grafana Architecture

Grafana is the visualization engine and anonymous monitoring landing page, not the primary RadMon application.

Production uses native Grafana on Windows where available. Docker is not a required production dependency.

### Stable address

The configured Grafana address remains stable, with `localhost:3300` as the administrative/editor address on the server unless explicitly configured otherwise. RadMon must not silently move Grafana to another port because a port is busy.

### Anonymous monitoring

Grafana anonymous access is Viewer-only for the monitoring presentation. The root RadMon route redirects/proxies to the Grafana playlist/dashboard kiosk URL without exposing a RadMon sign-in control.

### Editing

Grafana's normal login form remains enabled for administrative editing. The default Grafana account can be used initially, subject to deployment policy. Editing through Grafana must affect the exact dashboards used by the anonymous monitoring presentation.

### Persistence and no rollback

Saved Grafana state is authoritative after initial provisioning.

RadMon provisioning follows seed-once semantics:

1. If the required datasource/dashboard/playlist is missing, create the factory resource.
2. If it already exists, preserve saved content.
3. Never overwrite an existing saved dashboard during normal startup, service restart, Windows restart, installer update, or RadMon upgrade.
4. A one-time compatibility migration may unlock an old read-only dashboard while preserving its saved content.
5. Any future factory-reset action must be explicit and Administrator-only.

Grafana data (`grafana.db` or the native configured data directory) is persistent production state and must be preserved by install/update/uninstall flows unless the operator explicitly removes it.

## Windows 24/7 Runtime

The platform must not depend on an interactive Windows user keeping a GUI window open.

Production service model:

- RadMon backend/collector runs as an auto-start Windows service.
- Grafana runs as a native auto-start Windows service/process managed by the installation.
- Reverse proxy is optional for the first LAN-only phase; when enabled, Caddy is preferred because of low resource use. HTTPS/network exposure must not delay functional LAN deployment if BRIN infrastructure is not yet available.
- Service recovery restarts crashed RadMon processes.
- Logging must rotate/bound disk growth.
- Browser/React rendering occurs on client machines; the server only serves static assets/API data.

Because the server has only 6 GB RAM, Docker Desktop, local PostgreSQL, Redis, Elasticsearch, SSR Node services, and heavyweight observability stacks are out of scope.

## Deployment and Installer

`RadMon-Setup.exe` remains the deployment artifact. Installer changes must support server-mode installation without deleting production state.

Persistent directories/configuration include at minimum:

- RadMon config (`.env`/config directory)
- RadMon runtime/security state
- archives and reports
- native Grafana data/config that contains saved dashboard state

Updates replace application binaries/static web assets while preserving the above state.

## Migration Strategy

The migration is incremental, not a big-bang desktop rewrite.

1. Preserve and harden Grafana persistence/editability and anonymous kiosk landing.
2. Establish authenticated `/app` shell and RBAC boundaries.
3. Provide Viewer web parity for overview, stations, history, archives/reports.
4. Provide Operator web parity for alarm response, ACK, and suppression.
5. Provide Administrator web parity for user/system/station administration and diagnostics.
6. Keep desktop functionality available until the corresponding web workflows pass parity/regression tests; desktop retirement is a separate explicit decision.

## Security Boundaries

- Anonymous access is only to read-only monitoring presentation.
- `/app`, web APIs, control APIs, archive/report access, and administrative operations require RadMon authentication as appropriate.
- Viewer/Operator/Administrator authorization is enforced on the backend.
- Grafana admin/editor access is not exposed as anonymous editing.
- BRIN-network restriction is an infrastructure boundary to be enforced with Windows Firewall, reverse proxy/network ACLs, or upstream BRIN controls when deployed.

## Acceptance Criteria

The implementation is acceptable only when all of the following hold:

- `/` produces the full clean Grafana monitoring view without RadMon sign-in UI.
- Grafana dashboard edits saved by an administrator immediately affect monitoring.
- Saved dashboard edits survive RadMon restart, Grafana restart, Windows restart, and installer update.
- Normal startup never overwrites an existing saved dashboard.
- `/app` requires login for Viewer, Operator, and Administrator.
- Role-protected endpoints reject unauthorized calls even if a user manually crafts requests.
- The web application uses Kumo components as the primary UI system and builds to static assets.
- The production server needs no always-on Node process and no Docker dependency.
- RadMon can run unattended as Windows services after boot.
- Existing detector DB/source safety and alarm behavior remain regression-green.
- Existing full Python tests, web type/build checks, Grafana persistence tests, Windows installer build, and packaged smoke tests pass.
- Repository ends with only `main` and `feature` branches; this temporary spec/plan is removed before final merge/release.
