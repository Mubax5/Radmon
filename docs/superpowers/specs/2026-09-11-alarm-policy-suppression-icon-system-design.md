# RadMon Alarm Policy, Suppression, and Icon System Design

Date: 2026-09-11
Status: Approved design, pending implementation plan
Target branch: `main`

## 1. Purpose

This design adds a central alarm-policy layer for RadMon, introduces timed detector-level alarm suppression with strict auditability and anti-spam behavior, and replaces the current reused Silk icons with a coherent Tabler Outline icon system where each major feature has a distinct semantic icon.

The production source databases at `192.168.1.50`, `192.168.1.52`, and `192.168.1.38` remain legacy-compatible. No schema migration is performed on those source databases. The central PC at `192.168.1.2` remains the policy owner and the authoritative place for operator-facing alarm state.

## 2. Non-goals

This work does not change detector firmware, detector-side acquisition logic, physical buzzer/relay behavior, or the production source schema. It does not delete source alarm history. It does not provide indefinite suppression. It does not make suppression hide the real dose rate or underlying dose condition.

## 3. Baseline architecture

RadMon currently pulls source measurements and legacy alarm rows into the central service. Realtime monitoring is based on central `recent`/`vrecent`; legacy alarm rows are mirrored into the central runtime/security SQLite database and operator responses are written back to the corresponding source alarm row by setting legacy response fields while preserving `ack`.

The existing source-side alarm contract remains:

- key: `serid + dtoa`
- fields: `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, `i_flag`
- operator response write-through: set `i_op`, `pic`, `note`, transition `i_flag 0 -> 1`, preserve `ack`

The central service continues to isolate source failures so one source going offline does not stop the other sources.

## 4. Central alarm-policy owner

The central service becomes the single owner of operator-facing alarm policy. Source systems may continue creating legacy alarm rows exactly as they do today, but the central policy decides whether a source event becomes visible to operators, produces sound or notification, is suppressed, is coalesced as a duplicate, or is blocked because the detector has reached its retrigger limit.

This avoids modifying the three old production systems while still making desktop Admin, future authenticated web UI, notifications, and Grafana consistent.

The policy applies to HIGH/ALARM threshold events. WARN/ALERT status remains visible as dose status but does not consume the three-alarm retrigger budget.

## 5. Alarm episode state machine

Each central detector has one persistent alarm-policy state.

### 5.1 Dose states

Dose classification remains:

- `NORMAL`: dose rate is below the detector LOW/WARN threshold.
- `ALERT`: dose rate is at or above LOW/WARN but below HIGH/ALARM.
- `ALARM`: dose rate is at or above HIGH/ALARM.
- `OFFLINE`: normal RadMon stale/offline rules apply.

A detector is considered recovered for policy-reset purposes only when it reaches `NORMAL`, not merely when it falls below HIGH/ALARM.

Example with LOW/WARN = 100 and HIGH/ALARM = 150:

- `155` -> ALARM
- `120` -> ALERT, alarm episode is not reset
- `99` -> NORMAL, alarm episode is reset

### 5.2 Maximum three alarms per abnormal episode burst

A detector may surface at most three operator-facing ALARM events in a burst before it enters `RETRIGGER_LOCKED`.

The three events are total events, not one initial event plus three retries:

1. ALARM #1
2. ALARM #2
3. ALARM #3
4. any further ALARM attempt is blocked until NORMAL

Only one operator-facing ALARM may be active for a detector at a time. Repeated source rows while that same operator-facing alarm remains active are coalesced and do not increment the counter.

A retrigger becomes eligible after the prior operator-facing alarm has been responded to/silenced by a PIC and a new qualifying HIGH/ALARM event is observed.

### 5.3 Rolling five-minute burst window

The five-minute window starts at ALARM #1 of the current burst.

Example:

```text
00:00  #1
00:03  #2
00:04  #3 -> RETRIGGER_LOCKED
```

After #3 is surfaced, the detector remains locked regardless of how much time passes. Only NORMAL resets the lock.

If #3 is not reached inside the five-minute window, the next eligible event after the original window expires starts a new burst at #1:

```text
00:00  #1
00:03  #2
00:07  #1 of a new burst
```

The burst window is therefore anchored to the first event of that burst rather than extended by every event.

### 5.4 Normal reset

When the current dose falls below LOW/WARN:

- `trigger_count` becomes 0
- `window_started_at` is cleared
- `retrigger_locked` becomes false
- any stale active-event pointer is cleared after normal response/recovery processing
- the next future HIGH event is ALARM #1

The reset is persisted so central restart does not resurrect an old lock after a confirmed normal recovery.

## 6. Timed alarm suppression

Suppression is per detector and always time-bounded.

### 6.1 Required input

Starting suppression requires:

- authenticated Administrator or Operator
- sensitive-operation PIN
- detector
- duration greater than zero
- PIC
- reason
- checkbox `Aktifkan kembali otomatis saat laju dosis kembali NORMAL`

The UI provides presets of 5, 15, 30, and 60 minutes plus a custom duration. Custom duration is limited to 1 minute through 24 hours. There is no indefinite option.

PIC defaults to the signed-in user's display name but remains visible and may be adjusted when the actual responsible PIC differs. The immutable authenticated username is always stored separately as `started_by` so audit identity cannot be spoofed by editing the PIC field.

### 6.2 Suppression states

While a suppression session is active, the detector's operator-facing policy state is `SUPPRESSED`.

The UI must never imply that `SUPPRESSED` means the radiation level is safe. It must show both suppression state and underlying dose condition, for example:

```text
SUPPRESSED
Dose status: ALARM
142.5 uSv/h
PIC: Operator A
Reason: Calibration
Remaining: 12:34
```

If the detector is currently ALERT or NORMAL, that underlying condition is shown in the same way.

### 6.3 Automatic end on NORMAL

If `auto_resume_on_normal` is checked, suppression ends immediately when dose becomes `NORMAL` (below LOW/WARN). End reason is `AUTO_NORMAL`.

If the checkbox is not checked, suppression remains active until its expiry even if the dose becomes normal in the meantime. The alarm episode is still reset when NORMAL is observed, but the suppression session continues until expiry.

### 6.4 Timed expiry

When `expires_at` is reached, suppression ends with reason `EXPIRED`.

If the dose is still HIGH/ALARM at that moment, the central policy immediately creates a new central operator-facing ALARM #1 rather than waiting silently for a future source row. This event may be central-policy-originated and does not require inserting a new legacy row into the source database.

### 6.5 Starting suppression while an alarm is active

If suppression starts while the detector already has an active operator-facing alarm, that active alarm is responded to/silenced using the suppression PIC and reason. If it maps to an active source row, RadMon writes the normal legacy response fields to that source row. The original alarm remains in history as the pre-suppression alarm; it is not deleted or relabeled.

## 7. Suppression anti-spam contract

The user-visible contract is strict: at most one operator-facing `SUPPRESSED` alarm event is created per suppression session per detector.

The first qualifying HIGH/ALARM source event observed during an active suppression session may create that single `SUPPRESSED` policy event. It is immediately auto-silenced by policy and records the suppression PIC and reason.

Every later HIGH/ALARM source event in the same suppression session:

- remains eligible to exist in raw source history
- remains eligible to be mirrored centrally for traceability
- is not exposed as another operator-facing alarm row
- does not play sound
- does not send WhatsApp or another notification
- does not increment the three-alarm retrigger counter
- is written back to the source as silenced (`i_flag = 1`) when possible

The suppression session therefore cannot spam the operator even if a source produces many legacy alarm rows.

A database-level uniqueness guard must enforce the one-visible-suppressed-event rule; it must not rely only on an in-memory `if` statement.

## 8. Raw alarm mirror vs operator-facing policy events

Raw source traceability and operator-facing alarms are separated.

### 8.1 `remote_alarm_state`

The existing `remote_alarm_state` remains the raw mirrored representation of source alarm rows. It can receive additional policy metadata fields such as:

- `policy_decision`
- `suppression_id`
- `operator_visible`
- `policy_event_id`

Possible decisions include:

- `ACTIVE`
- `COALESCED_DUPLICATE`
- `SUPPRESSED_PRIMARY`
- `SUPPRESSED_DUPLICATE`
- `RETRIGGER_LOCKED`

This preserves source evidence without forcing every source row into the operator-facing Alarm page.

### 8.2 `alarm_policy_event`

A new central SQLite table represents operator-facing alarm events and central synthetic events.

Required fields:

```text
event_id TEXT PRIMARY KEY
event_key TEXT UNIQUE NOT NULL
serid INTEGER NOT NULL
source_id TEXT
remote_serid INTEGER
remote_event_time TEXT
origin TEXT NOT NULL              -- source | central_policy
kind TEXT NOT NULL                -- ALARM | SUPPRESSED
trigger_index INTEGER
surfaced_at TEXT NOT NULL
measured_value REAL
threshold REAL
status TEXT NOT NULL              -- ACTIVE | RESPONDED | AUTO_SILENCED
suppression_id TEXT
responded_at TEXT
pic TEXT
action TEXT
reason TEXT
notification_sent_at TEXT
```

A partial/conditional uniqueness rule, or equivalent transactional guard, enforces at most one `kind = SUPPRESSED` policy event per `suppression_id`.

Central synthetic events use a deterministic `event_key` so a restart or repeated evaluation cannot create duplicates.

## 9. Persistent policy tables

All canonical policy state is stored in the existing central runtime/security SQLite database. It is not stored in the source MariaDB schemas.

### 9.1 `alarm_policy_state`

```text
serid INTEGER PRIMARY KEY
window_started_at TEXT
trigger_count INTEGER NOT NULL DEFAULT 0
retrigger_locked INTEGER NOT NULL DEFAULT 0
active_event_id TEXT
last_trigger_at TEXT
last_normal_at TEXT
updated_at TEXT NOT NULL
```

Constraints:

- `trigger_count` is limited to 0..3
- `retrigger_locked = 1` requires `trigger_count = 3`
- state is updated atomically per detector

### 9.2 `alarm_suppression`

```text
suppression_id TEXT PRIMARY KEY
serid INTEGER NOT NULL
started_at TEXT NOT NULL
expires_at TEXT NOT NULL
auto_resume_on_normal INTEGER NOT NULL
pic TEXT NOT NULL
reason TEXT NOT NULL
started_by TEXT NOT NULL
ended_at TEXT
ended_reason TEXT
first_suppressed_alarm_at TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

Only one active suppression may exist for a detector. A uniqueness/index rule must prevent concurrent active sessions.

End reasons include:

- `AUTO_NORMAL`
- `EXPIRED`

No normal operator path provides indefinite suppression or an un-audited force-disable mode.

## 10. Central MariaDB runtime projection for Grafana

Grafana reads MariaDB and cannot directly join to the central SQLite policy database. The canonical state therefore stays in SQLite, while the central service publishes a small current-state projection to the MariaDB on PC `.2`.

The central-only table is:

```text
radmon_runtime_status
serid INTEGER PRIMARY KEY
policy_state VARCHAR(32) NOT NULL
trigger_count INTEGER NOT NULL
retrigger_locked TINYINT NOT NULL
suppressed TINYINT NOT NULL
suppression_expires_at DATETIME NULL
suppression_pic VARCHAR(128) NULL
suppression_reason VARCHAR(1000) NULL
underlying_dose_status VARCHAR(16) NOT NULL
updated_at DATETIME NOT NULL
```

This is not created on `.50`, `.52`, or `.38`.

The projection is rebuilt/upserted from canonical policy state and current `vrecent`. If projection update fails, policy enforcement continues from SQLite and the failure is logged/audited; Grafana may briefly show stale policy status but the alarm engine must not depend on this projection.

Grafana joins `vrecent` to `radmon_runtime_status`.

Visual priority is:

1. `OFFLINE`
2. `SUPPRESSED`
3. `ALARM`
4. `ALERT`
5. `NORMAL`

When `SUPPRESSED`, Grafana still shows the actual dose rate and `underlying_dose_status`.

## 11. Operator response behavior

Operator response remains a sensitive action.

For source-backed operator-facing events, responding writes through to the legacy source row when that row exists:

- set `i_op`
- set `pic`
- set `note`
- transition `i_flag 0 -> 1`
- preserve `ack`

For central-policy synthetic events that have no source row, response is central-only. If a later source row corresponds to the same still-active policy condition, the central policy must not create another operator-facing event; it may auto-apply the already-recorded response/suppression decision to that source row.

Every response is recorded in the central audit trail.

## 12. Permissions and audit

Roles:

- Administrator: view, respond to alarms, start suppression
- Operator: view, respond to alarms, start suppression
- Viewer: view only

Suppression uses a dedicated permission such as `suppress_alarm`; both Administrator and Operator receive it. Viewer does not.

Sensitive PIN validation follows the existing sensitive-operation security path. The existing short sensitive-operation lease may apply, but an explicitly supplied wrong PIN must still be rejected according to the current security contract.

Audit actions include at minimum:

- `ALARM_POLICY_SURFACED`
- `ALARM_POLICY_COALESCED`
- `ALARM_RETRIGGER_LOCKED`
- `ALARM_POLICY_RESET_NORMAL`
- `SUPPRESSION_STARTED`
- `SUPPRESSION_AUTO_NORMAL`
- `SUPPRESSION_EXPIRED`
- `SUPPRESSION_SOURCE_SILENCE_OK`
- `SUPPRESSION_SOURCE_SILENCE_FAILED`
- `ALARM_RESPONSE`

Audit records include actor, role, detector, source where applicable, before/after state, success, and failure reason.

## 13. API surface

The authenticated central API gains policy-oriented endpoints while preserving existing compatibility routes where practical.

Required endpoints:

```text
GET  /api/v1/control/alarm-events
POST /api/v1/control/alarm-events/{event_id}/response
GET  /api/v1/control/alarm-policy/{serid}
GET  /api/v1/control/suppressions
POST /api/v1/control/suppressions/{serid}
```

`POST /api/v1/control/suppressions/{serid}` requires:

```json
{
  "pin": "1234",
  "duration_seconds": 900,
  "pic": "Operator A",
  "reason": "Calibration",
  "auto_resume_on_normal": true
}
```

Validation:

- authenticated user required
- role must allow `suppress_alarm`
- PIN required
- duration 60..86400 seconds
- PIC non-empty
- reason non-empty
- detector must exist
- an already-active suppression returns conflict rather than silently replacing it

The current `/api/v1/control/alarms` route may remain as a compatibility facade, but operator UI must consume policy-filtered events rather than raw mirrored rows.

## 14. Concurrency and idempotency

Collector cycles, source alarm mirroring, operator API calls, suppression expiry, and desktop refresh can overlap. Correctness cannot depend on process timing.

Requirements:

- policy evaluation is serialized/atomic per detector
- SQLite updates use transactions
- operator-facing event creation uses deterministic unique keys
- one active suppression per detector is enforced by persistence
- one visible suppressed event per suppression is enforced by persistence
- repeated polling of the same source row is idempotent
- repeated notification attempts consult `notification_sent_at`
- the three-alarm counter increments only when a new operator-facing ALARM is successfully created
- coalesced raw duplicates do not increment the counter
- SUPPRESSED events do not increment the counter
- RETRIGGER_LOCKED source events do not increment the counter

After central restart:

- active timed suppression is restored until expiry or AUTO_NORMAL
- trigger count is restored
- retrigger lock is restored
- already-notified events stay notified
- historical source rows do not get re-sent as new alarms

## 15. Source write-through failure handling

Central policy enforcement must not depend on source write-through succeeding.

If source-side `i_flag = 1` update fails during suppression or response:

- central operator-facing sound/notification remains silenced according to central policy
- the raw event records the failed write state
- an audit event records the failure
- retry occurs on a later cycle with bounded backoff
- UI indicates that source-side silence is not yet confirmed

A source-side failure must never cause duplicate operator notifications from the same policy event.

## 16. Desktop UI behavior

### 16.1 Suppression control

The selected detector and Alarm page expose a `Suppress Alarm...` action with the Tabler `bell-cancel` icon.

The dialog contains:

- detector identity, read-only
- current dose and dose state, read-only
- duration preset/custom selector
- PIC, prefilled
- reason, required
- checkbox `Aktifkan kembali otomatis saat laju dosis kembali NORMAL`
- sensitive PIN
- clear warning that measurements continue and only alarm surfacing/notification is suppressed

The checkbox defaults to checked because automatic recovery on confirmed NORMAL is the safer operational default. The operator may uncheck it when suppression must last for the full selected duration.

### 16.2 SUPPRESSED visibility

While active, `SUPPRESSED` must be prominent in:

- station tree
- Recent page
- Alarm page
- status/details panel
- Grafana monitoring

The display must include PIC, reason, expiry/remaining time, and underlying dose state where space permits. Tooltips/detail panels carry the full information when compact views cannot show all fields.

### 16.3 RETRIGGER LOCKED visibility

A detector that reached #3 and remains abnormal shows a visible `RETRIGGER LOCKED` policy indicator in detailed views. This must not replace the underlying dose state; the operator still sees ALARM or ALERT as applicable.

## 17. Icon-system redesign

The current small Silk set causes unrelated features to reuse the same symbols. The redesign vendors a selected subset of Tabler Icons under the Tabler MIT license and uses only the Tabler Outline family for the main desktop feature icons.

Icons are vendored with the application and loaded locally; there is no runtime network dependency.

Final semantic mapping:

| UI feature | Tabler Outline icon |
| --- | --- |
| Monitoring dashboard | `chart-line` |
| Station/server group | `server` |
| Radiation detector/station child | `radioactive` |
| Recent realtime values | `activity` |
| Tabular data | `database` |
| Trend chart | `chart-area-line` |
| Reports | `file-chart` |
| Alarm | `alarm` |
| Suppress Alarm | `bell-cancel` |
| Logs | `logs` |
| Station Properties | `settings-cog` |
| Users/Security | `users` |
| Archive | `archive` |
| Refresh | `refresh` |
| Server Test | `server-cog` |
| Hardware Test | `cpu-2` |
| Acquisition Control | `device-analytics` |
| Installation Manual | `book-2` |
| User Manual / Help | `help-circle` |
| Exit / Logout | `logout` |

The first-order rule is semantic uniqueness: unrelated major features may not share a feature icon. Small repeated action icons are allowed only when the action is literally the same action, such as multiple Refresh buttons all using `refresh` or multiple Print commands using the same print icon.

The implementation adds an icon registry such as `app_icon(slot)` so business/UI code names semantic slots rather than raw filenames. Tests verify that all required icon assets exist and the major-feature registry entries are unique.

Existing Silk assets can remain temporarily for compatibility with non-migrated minor controls, but all major navigation, toolbar, station-tree, alarm, and security features in this scope move to Tabler Outline. No emoji literals are used as UI icons.

## 18. Grafana behavior

Grafana status queries must incorporate the central runtime projection while preserving existing WIB timestamp handling.

For each detector, panels expose:

- current dose rate
- underlying dose status
- effective policy status
- suppression PIC/reason/expiry when suppressed
- trigger count and retrigger lock in detail views

`SUPPRESSED` must have a visually distinct, prominent presentation. It must not be colored or worded in a way that implies NORMAL.

Existing 2-second dashboard refresh and TV playlist behavior remain unchanged unless a separate performance issue is found during implementation.

## 19. Notification behavior

Only policy events may trigger operator notifications.

Rules:

- ALARM #1/#2/#3 may notify once each
- duplicate source rows for an active event do not notify
- SUPPRESSED primary event does not send the normal alarm notification
- SUPPRESSED duplicate events do not notify
- RETRIGGER_LOCKED events do not notify
- historical/backfill alarm rows do not notify
- a central synthetic ALARM created when suppression expires while still HIGH may notify once as ALARM #1

Notification-sent state is persisted and idempotent across restart.

## 20. Test matrix

Implementation is not complete until automated tests cover at least the following.

### Threshold and reset

- exactly below LOW -> NORMAL
- exactly at LOW -> ALERT
- between LOW and HIGH -> ALERT
- exactly at HIGH -> ALARM
- falling below HIGH but remaining at/above LOW does not reset policy
- falling below LOW resets count and lock

### Three-alarm rule

- #1 surfaces and count = 1
- response then #2 inside burst surfaces and count = 2
- response then #3 inside burst surfaces and count = 3 and locks
- fourth qualifying event is not surfaced/notified
- repeated raw rows while an active alarm remains unresponded are coalesced
- locked state survives restart
- NORMAL clears locked state

### Five-minute window

- #1 00:00, #2 00:03, #3 00:04 -> lock
- #1 00:00, #2 00:03, event 00:07 -> new #1 burst
- boundary at exactly five minutes is defined consistently in tests; an event with `event_time - window_started_at <= 5 minutes` remains in the current burst, while greater than five minutes starts a new burst

### Suppression

- Administrator can start suppression
- Operator can start suppression
- Viewer cannot
- missing/invalid PIN rejected
- missing PIC rejected
- missing reason rejected
- zero/negative/over-24-hour duration rejected
- overlapping active suppression rejected
- suppression survives restart
- expiry ends suppression
- auto-normal checkbox ends suppression early only when checked
- ALERT does not count as NORMAL for auto-resume
- exactly one visible SUPPRESSED event per suppression session
- dozens of source ALARM rows during one suppression do not create duplicate visible events or notifications
- SUPPRESSED events do not consume retrigger budget
- starting suppression while active ALARM safely responds/silences the active event
- expiry while still HIGH immediately creates central ALARM #1 once

### Source write-through

- suppression writes `i_op`, `pic`, `note`, and `i_flag = 1` while preserving `ack`
- write failure is audited
- write failure is retried
- write failure does not re-notify operator
- source recovery applies outstanding silence decisions without creating new operator events

### Concurrency/idempotency

- duplicate polling of same source event creates one policy event
- two concurrent policy evaluations cannot create two #1 events
- two concurrent suppression-start requests create at most one active suppression
- two simultaneous first HIGH events during suppression create exactly one SUPPRESSED policy event

### UI and icons

- all major feature icon registry slots resolve to non-null QIcons
- major feature icon registry values are unique
- all migrated icons are from the vendored Tabler Outline set
- Station group and detector child use different icons
- Monitoring and Server Test use different icons
- Alarm and Suppress Alarm use different icons
- SUPPRESSED indicator is visible in station tree, Recent, Alarm page, and Grafana payload/query tests
- underlying dose condition remains visible while SUPPRESSED

### Regression

- existing source health isolation still works
- LIVE collection and bounded backfill still work
- legacy alarm response compatibility remains intact
- historical alarm sync does not resend old alerts
- Grafana WIB timestamp handling remains correct
- archive/security settings remain intact
- full existing test suite remains green

## 21. Migration and rollout

The central SQLite schema migration is additive and idempotent. Existing users, sessions, audit history, remote alarm mirror rows, LAN checkpoints, station mappings, and archive records are preserved.

The central MariaDB migration creates only the new central projection table on PC `.2` and is idempotent. It does not modify source schemas.

At first startup after upgrade:

1. migrate central SQLite policy tables/columns
2. create central MariaDB runtime projection table if absent
3. load active suppression/policy state
4. seed source alarm mirror as historical without notifications
5. derive current dose state from central `vrecent`
6. publish runtime projection
7. only then enable normal policy notification processing

This ordering prevents historical rows from becoming new alarm spam during rollout.

## 22. Acceptance criteria

The revision is accepted when all of the following are true:

- no major desktop feature in scope reuses another unrelated feature's icon
- all migrated major icons share the Tabler Outline style
- a detector can produce no more than three operator-facing ALARM events in a five-minute burst before locking
- lock persists until dose is below LOW/WARN
- a timed suppression requires PIC, reason, PIN, and duration
- suppression can optionally auto-end on NORMAL
- SUPPRESSED is prominent and never hides the underlying dose rate/status
- exactly one operator-facing SUPPRESSED event is created per detector per suppression session
- raw source alarm history is not deleted
- suppressed/locked duplicates do not sound or notify
- central restart preserves suppression, counters, locks, and notification idempotency
- source-side silence write failures are visible/audited and do not cause operator spam
- Grafana, desktop Admin, and future authenticated API consumers read consistent effective policy state
- no source MariaDB schema is migrated
- all new tests plus the existing suite pass before release
