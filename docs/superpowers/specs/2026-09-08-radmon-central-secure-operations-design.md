# RadMon Secure Central LAN Operations — Design

Date: 2026-09-08
Repository: `Mubax5/Radmon`
Base: `main` at `15df15fc579e4866b425120087d5ebc015710654`

## 1. Goal

Extend the current RadMon system so one central PC can consolidate radiation data from the three production LAN databases, provide the existing PySide6 Admin and Grafana TV views, support operator ACK/Response for legacy alarms, add role-based authentication with PIN-gated sensitive actions, and preserve a clear audit trail.

The design must remain compatible with the existing production `ipradmon` databases and must not require schema changes on the three source servers.

The security model must be reusable by a future URL-accessible web control surface. Authentication therefore lives in a UI-independent service layer rather than only inside Qt widgets.

## 2. Legacy reference findings

The supplied legacy RadMon source is treated as behavioral reference, not as code to copy wholesale.

Relevant behavior confirmed from the legacy source:

- alarm identity is `(serid, dtoa)`;
- legacy alarm fields include `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `i_flag`, `i_op`, `pic`, and `note`;
- ACK/Response writes operator response data and sets `i_op` only while `i_op` is still null;
- legacy device metadata can be edited;
- legacy web monitoring exposes current time and recent measurements;
- the supplied WhatsApp script reads separate LAN databases at the building servers and marks alarm notification state after sending.

This revision implements ACK/Response only. It does not send a physical silence/relay command to Raspberry Pi or detector hardware.

## 3. Target topology

```text
Production DB Gd.50 ----\
Production DB Gd.52 -----+--> LAN Pull Aggregator --> Central ipradmon on PC3
Production DB Gd.38 ----/                              |
                                                        +--> PySide6 Admin
                                                        +--> Grafana TV
                                                        +--> secured control service / future web UI
                                                        +--> WhatsApp alarm dispatcher

Admin operator on PC2/PC3 --> authenticated control service --> ACK write-through --> source DB
                                                               |
                                                               +--> central mirror + audit
```

### Central history policy

PC3 stores full measurement history. Data is not a latest-value-only overwrite. Pulling is incremental and resumable, and duplicate samples are ignored.

If a source is temporarily unavailable, previously consolidated history remains available and station status can become `OFFLINE` based on staleness.

## 4. LAN source configuration

Add LAN-source configuration through environment variables. No production password from supplied reference scripts is committed to Git.

Proposed configuration surface:

```env
RADMON_LAN_ENABLED=0
RADMON_LAN_SOURCES=gd50@192.168.1.50;gd52@192.168.1.52;gd38@192.168.1.38
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=
RADMON_LAN_DB_PASSWORD=
RADMON_LAN_DB_NAME=ipradmon
RADMON_LAN_BATCH_SIZE=1000
RADMON_LAN_POLL_INTERVAL=2
RADMON_LAN_STATE_DIR=runtime/lan
```

A single shared credential is sufficient initially because the supplied production topology uses the same database role. The parser will keep source identity separate from host so later per-source credentials can be added without changing the aggregator contract.

## 5. LAN aggregation behavior

Introduce a LAN pull component with one independent source adapter per configured remote DB.

For each source:

1. connect over MariaDB TCP;
2. inspect remote schema capabilities;
3. read `device` metadata;
4. import measurement history incrementally per station;
5. preserve remote `dtom`, `doserate`, `dose`, `previnterval`, and `stat` values;
6. mirror new source alarms;
7. persist per-source/per-station checkpoints locally;
8. retry failures without blocking other sources.

The importer must not recompute remote stored dose values during historical import.

### Device metadata authority

The first discovery of a source station inserts missing central `device` rows. Subsequent LAN pulls do not overwrite an existing central device row, so operator edits on PC3 remain authoritative for presentation.

## 6. Remote alarm compatibility

Two alarm schemas must be supported:

### Current RadMon alarm schema

```text
alarmid, serid, dtom, type, msg
```

### Legacy production alarm schema

```text
serid, dtoa, lvl, mvalue, thvalue, nhit,
ack, i_flag, i_op, pic, note
```

The LAN adapter detects which contract exists.

Legacy `lvl` mapping:

```text
1 -> ALERT
2 -> ALARM
```

Remote legacy alarms are mirrored into the current central `alarm` table with a readable synthesized message so current Grafana/Reports remain compatible. Full remote alarm state and source identity are cached in a local LAN sidecar store used by the Alarm control UI.

## 7. ACK/Response workflow

ACK is a sensitive write action.

Operator flow:

1. select an unacknowledged alarm;
2. choose an Action;
3. fill PIC and Note;
4. enter the logged-in user's PIN;
5. server validates user permission and PIN;
6. source DB is updated using `(serid, dtoa)` with a condition equivalent to `i_op IS NULL`;
7. response time is written to `i_op`;
8. central mirror is refreshed;
9. structured audit and human-readable application log are written.

Default Action choices preserve the legacy workflow and include at minimum:

- `Confirm to Location`
- `Checked / Condition Normal`
- `Follow-up Required`
- `Other`

The response form also permits a concise free-text note.

ACK does not modify hardware state.

If source write-through fails, the operation is reported as failed and the central copy is not falsely marked acknowledged.

## 8. Authentication and authorization

Use a local SQLite security store, default:

```text
runtime/radmon-security.db
```

It is separate from production `ipradmon`.

### Roles

#### Administrator

- all Operator and Viewer capabilities;
- manage users;
- enable/disable accounts;
- reset password/PIN;
- edit station metadata;
- edit thresholds/configuration;
- manage LAN source configuration where exposed by UI.

#### Operator

- monitoring and reports;
- ACK/Response alarm;
- read audit/logs;
- no user administration;
- no protected system configuration changes.

#### Viewer

- read-only monitoring, charts, reports, alarms, and logs.

### Credentials

- login uses username + password;
- each user has a separate PIN;
- password and PIN are never stored plaintext;
- hashing uses a modern salted KDF available without an external authentication service;
- PIN is checked again for each sensitive action;
- account can be disabled without deleting audit history.

### Web-ready session design

Auth logic is implemented as a reusable service independent of PySide6. A web layer can use the same users/roles/PIN verification later.

For URL access, the control surface must use server-side authorization on every write endpoint. Hiding buttons in the browser is never treated as authorization.

Web sessions use opaque, expiring server-side session IDs with HttpOnly cookies. Production deployment must place the service behind TLS/reverse proxy before exposing it outside the trusted network.

## 9. Bootstrap administrator

There will be no hard-coded default production password or PIN.

On an empty security store, first-run bootstrap reads explicitly configured bootstrap credentials from environment or presents a local bootstrap flow. The bootstrap secret is not persisted after the user record is created.

`.env.example` contains placeholders only.

## 10. Audit contract

Every security-relevant or mutating action must be auditable. High-frequency refresh/read polling is excluded to avoid meaningless log flooding.

Structured audit fields include:

- timestamp;
- username;
- role;
- action name;
- target type;
- target identifier;
- source host/source id when applicable;
- before value;
- after value;
- success/failure;
- failure reason;
- client/context information where available.

Examples:

- LOGIN_SUCCESS / LOGIN_FAILED / LOGOUT;
- ALARM_ACK;
- DEVICE_UPDATE;
- USER_CREATE / USER_UPDATE / USER_DISABLE;
- PASSWORD_RESET / PIN_RESET;
- LAN_SOURCE_CHANGE.

Each mutating/security action also writes a concise human-readable summary to central `ipradmon.applog`, including exactly what changed (`before -> after`) when applicable.

Sensitive values such as password hash, PIN hash, database password, and session token are never written to audit/applog.

## 11. Device metadata editing

Administrator + PIN can edit presentation/configuration fields including:

- Name;
- Location;
- Description;
- warning threshold;
- alarm threshold;
- max idle time;
- unit;
- Tag/SERID through a dedicated high-risk operation.

Changing SERID is not implemented as a simple `device` update because it is a relational identifier. The operation must verify uniqueness and migrate all central references transactionally. It is Administrator-only, requires PIN, shows a confirmation describing affected records, and produces an explicit before/after audit record.

Remote production SERID is not automatically rewritten during ordinary central metadata edits. A source identity mapping keeps central presentation separate from remote identity after a central tag change.

## 12. PySide6 Admin changes

Keep the existing Admin application.

Add:

- Login gate before normal Admin access;
- current user + role in the window status/header area;
- Logout action;
- user-management page/dialog for Administrator;
- station edit dialog for Administrator;
- improved Alarm page containing full legacy-style response information when available;
- `ACK / Response` action for Operator and Administrator;
- PIN dialog for protected actions;
- audit-aware action handlers;
- legacy-style visible active-alarm message area at the bottom of Admin;
- Silk icons for every new menu/toolbar/action/dialog where an equivalent bundled icon exists.

Viewer receives disabled/hidden mutating actions, but backend permission checks remain mandatory.

## 13. Future URL control surface

The implementation must make security reusable for the future online system.

The first revision may expose a minimal secure control surface alongside the central API, but the architectural requirement is that all protected business actions live behind services that can be called by both Qt and HTTP.

The intended eventual URL functions are:

- authenticated login/logout;
- current monitoring status;
- alarm list/detail;
- PIN-gated ACK/Response;
- station metadata management for Administrator;
- user management for Administrator;
- audit/log review;
- link/open Grafana monitoring.

Grafana remains the primary unattended public/TV presentation and should not receive admin write privileges.

## 14. WhatsApp alarm dispatcher

The supplied `wabot.py` is a behavioral reference for alarm notification, not code to copy directly.

The new dispatcher should:

- consume central mirrored alarm events rather than independently polling all source databases;
- send only newly eligible alert/alarm events;
- track sent state locally/centrally so restarts do not spam duplicate messages;
- include source/location, event time, station id/name, measured value, threshold, alarm level, and hit count when available;
- log send success/failure;
- keep WhatsApp-specific automation optional and disabled by default.

No production database credentials or WhatsApp browser profile are committed.

## 15. Grafana fixes and additions

### Page 1 measurement time regression

The current string-valued `DATE_FORMAT(MAX(m.dtom), ...)` stat introduced the observed `No data` regression.

Return the per-detector measurement-time query to a numeric epoch-millisecond value:

```sql
SELECT UNIX_TIMESTAMP(MAX(m.dtom)) * 1000 AS value
```

and use Grafana datetime field formatting (`dateTimeAsLocal`).

This keeps the reducer numeric and avoids the string-stat regression.

### Shared header row on every dashboard

Keep the existing main title panel unchanged.

Replace the current organization row with three aligned panels on the same grid row:

- left: small Indonesian day/date;
- center: existing two-line organization text with exactly the current center font sizing;
- right: small current update time in WIB.

The left/right typography is smaller than the center organization text so it does not distract. Widths and wrapping are tested to prevent clipping on a 1920x1080 kiosk layout.

The day/date and update time use explicit WIB conversion rather than depending on browser timezone.

### Existing TV contract

Preserve unless a test must change for the header geometry:

- 3 logical pages;
- 5 Operations variants;
- 7 generated dashboard payloads;
- 15 playlist items;
- playlist interval 10s;
- dashboard refresh 2s;
- no-scroll maximum grid bottom <= 24.

## 16. Launcher/runtime surface

Add a LAN/central runner because this is explicitly required by the new topology.

Proposed operator entry point:

```text
RUN_LAN.bat
```

It runs RadMon against the central local DB while the LAN aggregator collects source data.

`main.py` gains a `lan` source/runtime mode while preserving `detector` and `dummy` behavior.

The single-instance guard continues preventing conflicting local acquisition/admin modes.

## 17. Error handling

- one failed LAN source does not stop the other source workers;
- DB errors use bounded retry delays;
- failed ACK never reports success;
- source identity is shown in actionable errors;
- login and PIN failure are generic enough not to leak secret values;
- corrupted/missing security DB fails closed for protected writes;
- no password/PIN/DB secret is logged;
- Grafana bootstrap remains non-blocking;
- existing Admin read-only views should still open when optional WhatsApp support is unavailable.

## 18. Test contract

Tests will cover at least:

### Security

- password and PIN hashing/verification;
- role permission matrix;
- disabled user behavior;
- session expiry;
- PIN-gated sensitive operations;
- audit redaction.

### Alarm ACK

- legacy schema detection;
- `(serid, dtoa)` targeting;
- `i_op IS NULL` protection;
- Action/PIC/Note update;
- write-through failure behavior;
- audit/applog details.

### LAN aggregation

- multi-source independence;
- incremental checkpoints;
- duplicate measurement suppression;
- first-run historical backfill;
- imported dose preservation;
- source outage behavior;
- central metadata not overwritten after operator edit.

### Admin

- login gate;
- role-aware actions;
- PIN dialog paths;
- station update flow;
- alarm message/ACK flow;
- new icons resolve.

### Grafana

- Page 1 time target uses numeric epoch and datetime unit;
- every dashboard has left date / unchanged center org / right WIB update time;
- headers fit without clipping assumptions in grid contract;
- existing 7-dashboard/15-playlist/no-scroll contract remains green.

### CI

Existing pytest, compile, Grafana payload serialization, and YAML parsing remain required.

## 19. Files/components expected to change

Likely existing files:

- `main.py`
- `.env.example`
- `requirements.txt` if a minimal web/template dependency is needed
- `README.md`
- `radmon/config.py`
- `radmon/repository.py`
- `radmon/runtime.py`
- `radmon/admin/main_window.py`
- `radmon/admin/alarm_page.py`
- `radmon/grafana_tv.py`
- Grafana/bootstrap tests

Likely new focused components:

- `radmon/security.py`
- `radmon/audit.py`
- `radmon/lan.py`
- `radmon/remote_alarm.py`
- Qt login/PIN/user/device dialogs or pages under `radmon/admin/`
- LAN/security/alarm tests
- `RUN_LAN.bat`

The implementation should keep modules focused rather than expanding `main_window.py` into a catch-all.

## 20. Explicit non-goals for this revision

- no hardware buzzer/relay silence command;
- no replacement of Grafana with a custom public dashboard;
- no modification of production source database schemas;
- no plaintext production credentials in Git;
- no destructive pruning of production measurement history;
- no anonymous write/control endpoints;
- no exposure of the service directly to the public Internet without TLS/reverse-proxy deployment controls.

## 21. Delivery rules

- implement test-first where practical;
- every sensitive/mutating action has backend authorization and audit;
- update docs when behavior changes;
- run full tests and compile validation;
- validate generated Grafana payloads;
- push final implementation to `main`;
- verify remote branch list contains only `main` after completion.
