# RadMon API reference

This is a concise contract reference for integrations and diagnostics. The
browser Control Plane uses the same routes, but its session cookie must not be
copied into scripts or tickets.

## Authentication

### Web API

The web API uses a server-side session created by `POST /auth/login` and sent
as the `radmon_session` HttpOnly cookie. All Viewer, Operator, and Administrator
routes require a session. Remote login requires HTTPS in a production
installation; configure the real reverse-proxy origin, not a wildcard.

Sensitive mutations also require a valid numeric PIN of **4–8 digits**. A
password is **8–256 characters**. Do not place either value in examples,
source, or logs.

### Central ingestion API

LAN synchronization uses a separate bearer token:

```http
Authorization: Bearer <CENTRAL_TOKEN>
```

`<CENTRAL_TOKEN>` is a placeholder, not a usable credential. It is never the
browser session cookie.

## Health and ingestion routes

| Method and path | Auth | Purpose |
| --- | --- | --- |
| `GET /health` | none | Central service and central database health. It does not prove every source or Grafana datasource is healthy. |
| `POST /api/v1/measurements/batch` | central bearer | Idempotent central measurement ingestion. |
| `GET /api/v1/stations` | central bearer | Central station configuration. |
| `GET /api/v1/latest/{serid}` | central bearer | Latest genuine sample; `404` means no measurement exists. |

Example read-only health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8090/health
```

## Authenticated read routes

All routes below require the web session.

| Method and path | Minimum role | Result |
| --- | --- | --- |
| `GET /auth/me` | Viewer | Current user identity. |
| `GET /api/v1/web/overview` | Viewer | Status counts and station read model. |
| `GET /api/v1/web/stations` | Viewer | Station list and last-known context. |
| `GET /api/v1/web/stations/{serid}` | Viewer | One station detail. |
| `GET /api/v1/web/stations/{serid}/history?limit=240` | Viewer | Historical samples, bounded to 1–2,000 rows. |
| `GET /api/v1/web/active-alarms` | Viewer | Current source alarm snapshot. |
| `GET /api/v1/web/alarm-history?limit=100&offset=0` | Viewer | Paginated, sanitized source/policy lifecycle view. |
| `GET /api/v1/control/alarms` | Viewer | Sanitized source alarm compatibility view. |
| `GET /api/v1/control/sources/health` | Viewer | Per-source health state and timestamps. |
| `GET /api/v1/control/archives` | Viewer | Verified archive inventory. |
| `GET /api/v1/control/archives/{quarter_id}/recap` | Viewer | Archive recap without SQL restore. |
| `GET /api/v1/web/system` | Administrator | System and source details. |

The offline history route uses genuine `recent_last` samples when the station
is offline. It returns at most 30 rows, preserves original timestamps, and
does not fabricate values.

## Operator routes

Operator and Administrator sessions may use:

| Method and path | Purpose and important rule |
| --- | --- |
| `GET /api/v1/control/alarm-events` | Central policy events. These are not automatically source-response targets. |
| `POST /api/v1/control/alarm-events/{event_id}/response` | Record a policy response; requires PIN, action, and reason. |
| `GET /api/v1/control/suppressions` | List timed suppression records. |
| `POST /api/v1/control/suppressions/{serid}` | Start suppression for 60–86,400 seconds; requires PIN, PIC, and reason. |
| `POST /api/v1/control/suppressions/{suppression_id}/cancel` | End suppression; requires PIN and reason. |
| `POST /api/v1/control/alarms/{source_id}/{serid}/ack` | Handle the exact source alarm row only when its source state is still `i_flag=0`; reads back `i_flag=1`. |
| `POST /api/v1/control/stations` | Add a central station configuration; requires station-edit permission and PIN. |
| `POST /api/v1/control/stations/{serid}` | Update allowed station fields; source schema is not migrated. |
| `DELETE /api/v1/control/stations/{serid}` | Remove a central station configuration only after checking history/source ownership. |
| `GET /api/v1/control/reports` | List the caller's report jobs; Administrator can see all jobs. |
| `POST /api/v1/control/reports` | Queue a full report after preflight. |
| `GET /api/v1/control/reports/draft-preview?...` | Generate a PDF preview for the selected range. |
| `GET /api/v1/control/reports/{job_id}/preview` | View a completed PDF job. |
| `GET /api/v1/control/reports/{job_id}/download` | Download a completed PDF owned by the caller or by an Administrator. |
| `POST /api/v1/control/archive-exports` | Queue a verified archive SQL export for one quarter, one year, or all complete archives. |

## Administrator routes

Only Administrator sessions may use user and audit routes:

```text
GET    /api/v1/control/users
POST   /api/v1/control/users
PATCH  /api/v1/control/users/{username}
POST   /api/v1/control/users/{username}/enabled
POST   /api/v1/control/users/{username}/password
POST   /api/v1/control/users/{username}/pin
DELETE /api/v1/control/users/{username}
GET    /api/v1/control/audit
POST   /api/v1/control/archives/{quarter_id}/retry
```

User changes require the current Administrator PIN. The last enabled
Administrator cannot be disabled or deleted. Audit history remains after a
user is deleted.

## Reports and response semantics

- The elapsed report range is greater than zero and at most **24 hours**;
  exactly 24 hours is valid.
- A full report contains all rows in the selected range up to **50,000
  measurements** and **10,000 alarms**. It fails rather than silently
  producing a partial full report.
- A preview contains at most **250 measurement and alarm rows** and is
  explicitly a partial view. Its summary can still describe the full selected
  range.
- Report timestamps are rendered in **WIB** (`Asia/Jakarta`); displayed dose
  values use two decimals.
- Source alarm response is separate from policy response. It must not be
  treated as successful until the exact source row is read back with
  `i_flag=1`; `ack` remains unchanged.
