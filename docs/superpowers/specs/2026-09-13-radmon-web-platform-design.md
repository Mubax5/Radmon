# RadMon Web Platform Design

## Goal
Convert RadMon into a Windows-hosted, BRIN-network web platform while preserving the existing Python backend and legacy MariaDB sources. Anonymous users may access only the full Grafana monitoring landing page; every RadMon application route requires authentication and RBAC.

## Hard constraints
- Production host remains the existing Dell Inspiron 3847, i5-4460, 6 GB RAM, current Windows installation and storage.
- No Docker requirement in production.
- No Node.js server in production; frontend is static build output.
- Existing source MariaDB hosts and schemas remain unchanged.
- Grafana runs natively, defaults to localhost:3300, uses admin/admin unless overridden, anonymous Viewer for monitoring only.
- Saved Grafana dashboards are authoritative and must survive restart/update; bootstrap may seed missing resources but never overwrite existing dashboards/playlists.
- `/` is Grafana fullscreen/kiosk monitoring only, with no RadMon sign-in affordance.
- `/app` and `/api/v1/control/*` require RadMon authentication. Viewer is authenticated; anonymous users are not RadMon Viewers.
- Roles: Viewer (read-only), Operator (Viewer + alarm response/suppression), Administrator (Operator + users/stations/system/admin actions).
- Frontend uses React + TypeScript + Vite + @cloudflare/kumo + @phosphor-icons/react; production ships only static assets.

## Architecture
A single native RadMon background process owns the existing LAN runtime and FastAPI application. FastAPI serves authenticated JSON APIs and the compiled `/app` SPA. Grafana remains a separate native process with persistent `runtime/grafana` data. The web platform avoids Docker, PostgreSQL, Redis, SSR, and other always-on services that are unnecessary on the fixed 6 GB Windows host.

## Monitoring
`/` redirects directly to the configured Grafana playlist/dashboard kiosk URL. Grafana anonymous access is Viewer-only. There is no RadMon login button, wrapper, sidebar, or navigation on the monitoring landing experience. Grafana editor remains available locally at `http://localhost:3300`; administrator credentials default to `admin/admin` and are configurable.

Grafana provisioning changes from repair/overwrite to seed-only:
- datasource: create if missing; existing datasource is left unchanged during normal startup.
- dashboards: query by UID; POST only when missing; never `overwrite: true` during normal startup.
- playlist: create if missing; never rewrite a saved playlist during normal startup.

## Auth/RBAC
Existing session-cookie auth remains canonical. Every application route under `/app` requires a session except `/app/login`. Viewer is an authenticated role. Every write endpoint continues enforcing permissions server-side; UI visibility is secondary and is never the security boundary.

## Web UI
`/app/login` is the unauthenticated SPA screen. The authenticated shell uses Kumo components and Kumo standalone styling. Navigation is role-aware:
- Viewer: Overview, Stations, History, Reports/Archives.
- Operator: Viewer + Alarms + Suppression workflows.
- Administrator: Operator + Users + System/Diagnostics + Grafana Admin link.

## 24/7 Windows operation
The packaged executable gains `--server` mode that runs the central stack without the PySide desktop. The installer registers an ONSTART Scheduled Task using Windows Task Scheduler so RadMon starts before user login. The long-running server process owns central API, LAN collector, and Grafana bootstrap and exits cleanly on system termination. Desktop mode remains available only as an emergency/local tool.

## Packaging
Windows CI builds the frontend first, embeds `web/dist` into the PyInstaller onedir bundle, and then creates `RadMon-Setup.exe`. Installer preserves config/runtime/archive/report directories and creates/removes the startup scheduled task. Production runtime does not require Node.js.