# RadMon Hosted Web Admin, Grafana Operations, Manuals, and PC3 Hosting Design

Date: 2026-09-09
Status: Approved design baseline, pending implementation plan
Target branch: `main`

> Repository policy intentionally keeps planning/specification artifacts directly under `docs/` rather than `docs/superpowers/`.

## 1. Purpose

This design completes four connected parts of the RadMon system:

1. correct and simplify the Grafana TV Operations flow;
2. replace Markdown/manual file association behavior with proper HTML manuals containing real application screenshots;
3. make the RadMon administration experience available through a hosted fullscreen web interface on PC3 while preserving the existing desktop Admin as a local fallback;
4. expose the hosted system through one HTTPS entry point without exposing MariaDB, Grafana, or the FastAPI service directly to the Internet.

The design preserves the existing central architecture, quarterly archive, LAN collector ownership, production read-only boundary, alarm ACK semantics, authentication model, role model, audit model, and desktop Admin fallback.

## 2. Authoritative deployment facts

- Central host / PC3: `192.168.1.2`.
- PC3 is the single central RadMon runtime host.
- PC3 reads directly from the configured production database servers.
- Production detector identity is authoritative from production/central `device.serid`; old topology drawings are not authoritative.
- Normal production-source access remains read-only. The only approved source write is the guarded legacy ACK/Response write-through.
- `central_server.py` remains the single owner of LAN ingestion in hosted mode.
- Desktop Admin is retained as a local fallback on PC3 and must not start a second LAN collector.

## 3. Product choice: web primary, desktop fallback

The selected architecture is:

```text
Primary control path:    Browser -> HTTPS -> Web Admin on PC3
Fallback control path:   Desktop Admin running locally on PC3
```

Both control paths use the same central data, the same user/security store, the same role definitions, the same PIN verification logic, the same ACK service, and the same structured audit trail.

There must not be separate web-only users, desktop-only users, or duplicated security databases.

The desktop application remains important for local recovery if the browser, reverse proxy, or network-facing web tier is temporarily unavailable.

## 4. Web Admin visual direction

The selected UI direction is **legacy desktop parity**, not a generic modern dashboard redesign.

The web Admin should look and behave recognizably like the Windows RadMon desktop application:

```text
+ File  View  Tools  Help  Security ------------------------------+
| legacy-style toolbar icons                                      |
+--------------+---------------------------------------------------+
| Station tree | Recent | Tabular | Chart | Reports | Alarm | Logs|
|              |                                                   |
| detector     |                 page content                      |
| detector     |                                                   |
| detector     |                                                   |
| ...          |                                                   |
|              |                                                   |
| Tag          |                                                   |
| Name         |                                                   |
| Location     |                                                   |
| Description  |                                                   |
| [Update]     |                                                   |
+--------------+---------------------------------------------------+
| status / connection / current user / role                       |
+------------------------------------------------------------------+
```

The goal is workflow familiarity for operators who already know the legacy application. It is not a pixel-for-pixel reproduction of Windows widgets where browser behavior requires a web-native equivalent.

### 4.1 Required web pages/workflows

The hosted UI must provide at least:

- fullscreen Login;
- Recent;
- Tabular;
- Chart;
- Reports;
- Alarm;
- Logs;
- Station tree and selected-station details;
- Station Properties for permitted Administrator operations;
- Period Selection;
- Options relevant to the web client;
- Server Test;
- Users / Security;
- Audit;
- Archive inventory and recap;
- About;
- Installation Manual;
- User Manual;
- Monitoring/Grafana launch/navigation.

Existing desktop-only hardware/acquisition operations may remain local-only when the browser cannot safely perform them.

## 5. Fullscreen browser behavior

The hosted RadMon experience is designed for a dedicated browser window, operator workstation, wall display, or kiosk-like fullscreen use.

### 5.1 Login

`/login` is a fullscreen authentication page containing the RadMon product identity and only the controls needed to authenticate.

```text
username
password
Login
```

It must not reveal authenticated content before a session is valid.

### 5.2 Application shell

After login, `/app` is also fullscreen. The content area uses the available viewport rather than displaying a small centered desktop-window imitation.

The top menu and toolbar stay compact so the monitoring/reporting area receives most of the screen.

### 5.3 Session expiration

When the server returns an authentication failure because a session is absent, revoked, or expired, the web client redirects to `/login` rather than leaving raw `401` JSON on screen.

Logout revokes the server-side session and redirects to `/login`.

## 6. Authentication and authorization

The existing RadMon security model remains authoritative.

Roles:

- **Administrator**: full monitoring/reporting plus user management, station/configuration changes, archive administrative actions, and other Administrator-only controls;
- **Operator**: monitoring/reporting and ACK/Response workflow with Action/PIC/Note and PIN, without user/system configuration;
- **Viewer**: read-only monitoring/reporting.

The existing separate sensitive-operation PIN remains in use where applicable.

### 6.1 Shared security store

Web and desktop share the existing PC3 security store, currently represented by the local security SQLite sidecar. Passwords and PINs remain salted hashes.

No plaintext password/PIN storage is introduced for the web client.

### 6.2 Session cookie

The existing server session cookie remains HttpOnly. Hosted production deployment must enable the secure-cookie setting when HTTPS is in use.

### 6.3 CSRF / same-origin protection

Because browser authentication uses cookies, mutating browser endpoints must validate same-origin intent. Implementation should use an explicit CSRF token or a strict Origin/Referer validation strategy for state-changing requests in addition to SameSite cookies.

Sensitive operations continue to require server-side role checks and PIN verification; hiding a button in the browser is never considered authorization.

## 7. Hosted web implementation boundary

The web Admin is served by the PC3 RadMon server. The recommended implementation is a lightweight server-served HTML/CSS/JavaScript application rather than introducing a separate Node/npm deployment unless a later requirement makes that necessary.

This keeps deployment on a Windows PC simple and allows the FastAPI server to own:

- authentication routes;
- protected application HTML/static assets;
- JSON control/reporting endpoints;
- manual pages;
- health endpoints;
- integration with the existing central services.

The UI code and API remain logically separated so the desktop fallback and web UI both call the same service layer rather than duplicating business rules.

## 8. Hosted routes

The public reverse proxy exposes one origin. The application uses routes along these lines:

```text
GET  /                       redirect to /login or /app
GET  /login                  fullscreen login page
GET  /app                    protected fullscreen web Admin
GET  /manual/installation    authenticated installation manual HTML
GET  /manual/user            authenticated user manual HTML
GET  /monitoring/...         authenticated Grafana proxy path
GET  /auth/proxy-check       reverse-proxy session authorization check

POST /auth/login
POST /auth/logout
GET  /auth/me

GET  /api/v1/control/...
POST /api/v1/control/...
```

Both hosted manual routes require a valid RadMon session because the manuals may contain deployment and operational information. Desktop Help may still open the same HTML files locally on PC3 without going through HTTP.

Existing secure API endpoints remain the starting point. Additional read endpoints are added only where the web UI needs data that currently exists only through desktop repositories, for example recent measurements, station detail, tabular history, report data, and logs.

## 9. Grafana TV Operations correction

The supplied Grafana Operations JSON is the visual reference for the Operations page structure. The implementation must modify the Python dashboard generator, not only an emitted JSON file, so regenerated dashboards remain correct.

### 9.1 Logical pages

The TV system keeps three logical categories:

1. Realtime;
2. Trends;
3. Operations.

Operations has **three variants**, not five:

```text
Operations Page 1/3 -> 5 detectors
Operations Page 2/3 -> 5 detectors
Operations Page 3/3 -> 5 detectors
```

Total operational detector coverage is exactly 15 rows across the three variants.

### 9.2 Detector identity and ordering

Operations pages must use the detector identity represented in the central `device` dataset and must not reintroduce SERIDs from the discarded physical-topology drawing.

The approved page order is **ascending production/central SERID**. This is deliberately independent of dose value, alarm state, name edits, or measurement refresh, so a detector does not move between Operations pages while the system is running.

For the approved 15-detector deployment baseline:

```text
Page 1/3 = first 5 SERIDs ascending
Page 2/3 = next 5 SERIDs ascending
Page 3/3 = final 5 SERIDs ascending
```

If the central device inventory is not exactly 15, the dashboard must surface the actual inventory safely rather than inventing detectors. Tests for the approved deployment baseline remain 15 detectors / 3 pages / 5 rows each.

### 9.3 Operations layout

Each Operations page keeps the approved visual structure:

- title/header;
- date on the left;
- organization title in the center;
- update time on the right;
- `Status Detector` donut on the left;
- `Kondisi Operasional Detector · Page X/3` table on the right;
- NORMAL / ALERT / ALARM / OFFLINE summary panels;
- `Alarm Terbaru · 24 Jam` table beneath them.

## 10. Grafana date/time typography

All Grafana stat panels whose primary displayed value is a date or time use:

```text
valueSize = 28
```

This includes header date/update-time panels and other dedicated date/time stat displays such as latest measurement time where applicable.

Date/time queries must use a representation Grafana can reliably reduce and render. A regression test must prevent the previously observed `No data` behavior from returning.

The organization center header remains smaller than the main title and may use its existing responsive HTML typography.

## 11. Grafana auto-fit statistic typography

The following value panels must **not** set a fixed `text.valueSize`:

- NORMAL;
- ALERT;
- ALARM;
- OFFLINE;
- Dose Rate Tertinggi Saat Ini;
- Rata-rata Saat Ini;
- Detector Online;
- Detector Offline.

The `text.valueSize` property is omitted so Grafana can auto-fit the value to the panel.

It must not be represented as `0`, because zero is a concrete size rather than an omitted/automatic value.

## 12. Grafana playlist behavior

The approved TV sequence is simplified to five unique dashboard steps:

```text
Realtime
-> Trends
-> Operations 1/3
-> Operations 2/3
-> Operations 3/3
-> repeat
```

Playlist interval remains 10 seconds unless a later explicit requirement changes it.

This means one complete cycle covers all 15 operational detectors without redundantly repeating Realtime and Trends between each Operations variant.

## 13. HTML manuals

The existing behavior of opening Markdown files through the Windows file association is removed for the user-facing Help menu.

Target manual structure:

```text
docs/manual/
  installation.html
  user-manual.html
  manual.css
  assets/
    screenshots/
```

Desktop Help actions open the HTML file in the default browser.

The hosted web Admin serves the same manual content, avoiding two independent documentation sets.

Markdown source may remain internally if useful, but the user-facing manual contract is HTML.

## 14. Manual visual quality

The manuals should look like technical operating documentation, not a generic AI-generated landing page.

Required visual characteristics:

- readable technical typography;
- stable sidebar/table of contents;
- numbered operating procedures;
- screenshots near the step they explain;
- compact warnings/notes where needed;
- tables for configuration/reference information;
- restrained styling;
- no marketing hero blocks;
- no decorative gradient-heavy card wall;
- no excessive icon/emoji decoration.

## 15. Screenshot authenticity requirement

Manual screenshots must come from **the actual RadMon application or actual Grafana/web pages being rendered**, not from image generation, mockups, Figma-style reproductions, or fabricated UI captures.

Deterministic demo/test data may be used to create repeatable documentation captures, but the rendered application must be the real application code.

Required screenshot topics, where the corresponding feature is available:

- fullscreen Login;
- web Recent;
- Alarm / ACK Response;
- Reports and archive selection;
- Station Properties;
- Options;
- Grafana Realtime;
- Grafana Trends;
- Grafana Operations;
- desktop fallback overview if a reliable actual capture is available in the implementation environment.

### 15.1 Screenshot quality gate

A screenshot must not be committed to the manual when it contains:

- a traceback;
- broken authentication state;
- clipped critical text;
- accidental `No data` caused by a rendering/query defect;
- overlapping dialogs;
- incomplete loading state presented as final;
- missing fonts/assets;
- broken image/icon links;
- a mock/fabricated interface.

Automated capture should wait for the target page to reach a stable state. Screenshots are then visually inspected before documentation completion is claimed.

## 16. Hosting architecture on PC3

PC3 is the single hosted system endpoint.

```text
Browser
  |
  | HTTPS :443
  v
PC3 192.168.1.2
  |
  +-- Reverse proxy
  |     |
  |     +-- /              -> RadMon web/login
  |     +-- /app           -> RadMon Web Admin
  |     +-- /api/...       -> FastAPI
  |     +-- /manual/...    -> HTML manuals
  |     +-- /monitoring/...-> Grafana proxy
  |
  +-- central_server.py / FastAPI (private local port)
  +-- Grafana (private local/container port)
  +-- Central MariaDB (private/local LAN policy)
  +-- Security SQLite sidecar
  +-- Archive storage
  +-- Single LAN collector
```

The preferred Windows reverse proxy for this deployment is **Caddy**, because it provides a small configuration surface and straightforward TLS/reverse-proxy behavior. If institutional policy later mandates IIS or another proxy, the same routing/security contract must be preserved.

## 17. Network exposure policy

The following must not be exposed directly to the public Internet:

- MariaDB port 3306;
- raw Grafana administrative port;
- raw FastAPI/Uvicorn port 8090.

The externally reachable service is HTTPS through the reverse proxy.

Firewall rules should allow only the ports and source networks required by deployment policy.

## 18. Grafana authentication boundary

Grafana may retain anonymous Viewer behavior only on a private/loopback integration path when that is required for kiosk rendering.

External users must not reach anonymous Grafana directly.

The Caddy `/monitoring` route uses a forward-auth style check against RadMon, conceptually `GET /auth/proxy-check`, which returns success only for a valid RadMon session. Only after that check succeeds is the request proxied to the internal Grafana endpoint.

A Viewer may view monitoring. Operator and Administrator may also view it. Grafana administrative privileges are not granted through RadMon application roles merely because a user can view the dashboards.

The internal Grafana port remains bound/private according to deployment policy and is not a public bypass around `/monitoring`.

## 19. Reverse proxy and TLS

Production hosting uses HTTPS.

Expected behavior:

- HTTP redirects to HTTPS where policy allows;
- HSTS may be enabled once the deployment domain/certificate path is stable;
- secure session cookie is enabled;
- trusted proxy headers are accepted only from the local reverse proxy;
- the FastAPI service is not trusted to arbitrary Internet-provided forwarded headers;
- request-body size and timeout limits are set conservatively;
- manual/static assets are cached sensibly;
- application/API responses containing authenticated information are not cached publicly.

The final domain name and institutional certificate source are deployment values, not hard-coded source values.

## 20. Desktop Admin fallback behavior

Desktop Admin remains available on PC3.

It continues to provide the existing Windows workflow and does not disappear when Web Admin is introduced.

Changes shared with web hosting include:

- Help menu opens HTML manuals rather than Markdown;
- security and role behavior remains centralized;
- the desktop fallback does not own a second LAN collector in hosted mode;
- user/security changes made in Web Admin are immediately reflected in desktop authentication because they share the same security store;
- ACK operations through either UI reach the same service/audit path.

## 21. Hardware and acquisition behavior in web mode

The browser must not pretend to have direct serial/hardware access that it does not actually have.

Therefore:

- Server Test can be web-accessible as a safe, read-only server health check;
- Hardware Test may be local-only or server-mediated read-only diagnostics if implemented safely;
- physical buzzer/relay control remains outside the approved scope;
- Acquisition Control for local detector/dummy mode remains a desktop/local feature unless a later explicitly approved secure server-side control is designed;
- LAN collection remains owned by `central_server.py`.

## 22. Reporting and archive behavior in Web Admin

The existing quarter archive and direct archive-reading model remains intact.

Web Reports must eventually provide the same user-facing capabilities as the desktop workflow where technically applicable:

- choose station/date range;
- preview;
- use active and archived quarter data transparently;
- generate/download CSV;
- generate/download PDF/report output;
- print through browser print where appropriate;
- view quarter inventory and monthly recap.

No SQL restore should be required merely to view an archived period.

## 23. File/export behavior in browser

Legacy menu labels may remain familiar, but browser behavior follows web security constraints:

- `Save As CSV...` returns/downloads a server-generated or browser-generated CSV;
- `Print...` uses browser print for rendered content or downloads a report artifact where appropriate;
- browser code does not silently read arbitrary files on PC3;
- server-side export paths are controlled and sanitized;
- archive/security data is not exposed as raw local filesystem browsing.

## 24. Error handling

Hosted UI errors should be understandable to operators.

Examples:

- expired session -> redirect to login;
- API unavailable -> visible connection/status message, not a blank screen;
- Grafana unavailable -> monitoring page reports unavailability without breaking Admin;
- central DB unavailable -> web shell may load but clearly shows data backend error;
- archive damaged -> existing `DAMAGED` state is surfaced rather than silently hiding the archive;
- forbidden role action -> disabled/hidden where helpful and always rejected server-side;
- invalid PIN -> clear operation failure, audited where appropriate.

## 25. Deployment configuration

New hosting-related settings should be explicit environment/configuration values rather than hard-coded deployment secrets.

The FastAPI application is private behind the local reverse proxy by default:

```env
RADMON_WEB_HOST=127.0.0.1
RADMON_WEB_PORT=8090
RADMON_WEB_COOKIE_SECURE=1
RADMON_PUBLIC_BASE_URL=https://radmon.example.internal
RADMON_GRAFANA_INTERNAL_URL=http://127.0.0.1:3000
RADMON_REVERSE_PROXY=caddy
```

The exact domain is provided by the deployment environment.

Production DB credentials remain in local `.env` or an approved secret store and are never embedded in HTML/JavaScript/manual screenshots.

## 26. Caddy deployment contract

The implementation should provide a deployable example Caddy configuration for PC3.

It must:

- terminate HTTPS or integrate with the institution's TLS termination model;
- proxy RadMon application/API traffic to the private FastAPI port;
- use RadMon forward-auth/session validation before proxying `/monitoring` to Grafana;
- avoid exposing Grafana admin endpoints unintentionally;
- preserve WebSocket/streaming headers where Grafana requires them;
- set appropriate security headers;
- not contain committed passwords/tokens/certificate private keys.

## 27. Backward compatibility

This work must preserve:

- existing MariaDB schema compatibility;
- production-source read-only rule except ACK;
- LAN checkpoints and source mappings;
- role/PIN/audit behavior;
- quarterly archive lifecycle;
- direct archived report reading;
- WhatsApp architecture;
- desktop Admin fallback;
- existing dummy/detector launch modes;
- two-second Grafana dashboard refresh baseline unless explicitly overridden;
- legacy `measurement.dose` semantics.

## 28. Testing requirements

Implementation is not complete until automated tests cover at minimum:

### Grafana

1. `OPERATIONS_PAGE_COUNT == 3`;
2. exactly three Operations dashboard variants are generated;
3. Operations baseline covers 15 detectors as 5 rows x 3 pages;
4. page titles read `Page 1/3`, `Page 2/3`, `Page 3/3`;
5. Operations page membership is stable and ordered by ascending SERID;
6. playlist order is Realtime, Trends, Operations 1/3, Operations 2/3, Operations 3/3;
7. playlist interval remains 10s;
8. Grafana dashboard refresh remains 2s;
9. date/time stat `valueSize` is 28;
10. the eight approved auto-fit summary stats omit fixed `text.valueSize`;
11. date/time SQL/render contract cannot regress to the previously observed `No data` condition;
12. Grafana payloads remain valid JSON and fit the supported layout bounds.

### Web authentication/security

13. unauthenticated `/app` access is redirected/rejected into login flow;
14. valid login creates a usable session;
15. expired/revoked session returns user to login;
16. Viewer cannot perform Operator/Admin actions;
17. Operator can perform ACK only through the approved role/PIN path;
18. Administrator can access management operations;
19. state-changing browser requests enforce CSRF/same-origin protection;
20. secrets never appear in web payloads/static JS/manual assets;
21. `/auth/proxy-check` rejects absent/invalid sessions;
22. `/monitoring` cannot be reached externally without a valid RadMon authorization boundary;
23. hosted manual routes require authentication.

### Web Admin

24. the fullscreen application shell exposes the legacy menu/tab structure;
25. station navigation and selected-station detail work;
26. Recent/Tabular/Chart/Reports/Alarm/Logs use the central service/data path;
27. web Reports can reach archived and active data without SQL restore;
28. CSV/PDF/print behavior works through browser-safe flows;
29. server-side permissions are enforced independently of UI visibility.

### Manuals

30. desktop Help points to HTML manuals rather than `.md` files;
31. hosted manual routes serve the same manual content;
32. all referenced screenshot files exist;
33. screenshots used by manuals are produced from actual rendered RadMon/Grafana pages, not mock-image assets;
34. HTML has no broken local asset links;
35. manual screenshots do not contain known failure-state markers used by the capture tests.

### Regression

36. full existing test suite remains green;
37. Python compile validation remains green;
38. Grafana payload validation remains green;
39. launchers continue to function and desktop Admin remains available.

## 29. Documentation screenshot capture strategy

The implementation should include deterministic screenshot capture tooling where practical.

For the web Admin and Grafana:

1. start the actual application against a deterministic demo/test dataset;
2. authenticate through the real login flow;
3. navigate to the real target page;
4. wait for a stable selector/data state;
5. capture PNG at a documented viewport;
6. visually inspect the result;
7. commit only accepted screenshots into `docs/manual/assets/screenshots/`.

For desktop Qt pages, screenshots may be captured from the actual Qt application when the execution environment can render them reliably. If a reliable actual desktop capture is not available, the manual must not substitute a fabricated desktop mockup.

## 30. Expected implementation units

Likely changes include:

- `radmon/grafana_tv.py` and Grafana regression tests;
- generated/provisioned Grafana dashboard files where applicable;
- new hosted web/static UI package under `radmon/`;
- extensions to secure/read API routes and service/repository abstractions;
- `central_server.py` static/web routing and startup wiring;
- desktop `main_window.py` manual URL targets;
- `docs/manual/installation.html`;
- `docs/manual/user-manual.html`;
- `docs/manual/manual.css`;
- actual screenshot assets and capture tooling/tests;
- reverse-proxy/Caddy deployment example;
- `.env.example` and README deployment guidance;
- tests for auth, hosted page routing, role behavior, Grafana layout, manuals, and regression contracts.

## 31. Completion criteria

This feature is complete when all of the following are true:

- Operations displays three pages of five detectors each for the 15-detector deployment baseline;
- Operations uses the approved visual template structure;
- Operations detector membership is stable by ascending SERID;
- all Grafana date/time values use font size 28 and no longer regress to `No data`;
- the eight specified summary panels auto-fit without fixed `valueSize`;
- TV playlist rotates through five unique dashboards in the approved order;
- Installation Manual and User Manual open as proper HTML documentation;
- manual screenshots are genuine captures of rendered RadMon/Grafana pages and pass visual quality review;
- PC3 hosts a fullscreen `/login` and fullscreen legacy-style `/app`;
- Web Admin shares users, roles, PIN verification, services, audit, and data with the desktop fallback;
- desktop Admin remains usable locally on PC3;
- only one LAN collector exists in hosted operation;
- external access goes through HTTPS reverse proxy rather than directly to database/Grafana/FastAPI ports;
- Grafana external viewing is protected by a RadMon authorization boundary using the shared RadMon session;
- no production DB mutation is introduced outside the existing ACK contract;
- all regression tests, compile checks, and Grafana validation pass on `main`.
