# RadMon Alarm Policy, Suppression, and Icon System Design

Date: 2026-09-11  
Status: Approved design, pending implementation plan  
Target branch: `main`

## 1. Purpose

This design adds a central alarm-policy layer for RadMon, timed detector-level alarm suppression with strict auditability and anti-spam behavior, and a coherent Tabler Outline icon system where distinct visible features/commands use distinct semantic icons.

The production source databases at `192.168.1.50`, `192.168.1.52`, and `192.168.1.38` stay legacy-compatible. No source schema migration is allowed. The central PC at `192.168.1.2` is the policy owner for operator-facing alarm behavior.

## 2. Non-goals

This work does not change detector firmware, source-side acquisition logic, physical buzzer/relay control, or the production source schema. It does not delete source alarm history. It does not provide indefinite suppression. It does not hide the actual dose rate or underlying dose condition.

## 3. Current production contract

RadMon pulls measurements and legacy alarm rows from the three production sources. Central realtime monitoring uses `recent`/`vrecent`. Source alarm rows use the legacy `alarm` fields:

- key: `serid + dtoa`
- fields: `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, `i_flag`
- response write-through: set `i_op`, `pic`, `note`, transition `i_flag 0 -> 1`, preserve `ack`

Source failures remain isolated: one source being unavailable must not stop the other sources.

## 4. Central policy ownership

The central service becomes the single policy owner for operator-facing alarms. Source systems may continue creating legacy rows exactly as they do today, but central decides whether an event:

- becomes visible to operators
- plays alarm sound
- sends notification
- is coalesced as a duplicate
- is suppressed
- is blocked by retrigger lock

This policy applies to HIGH/ALARM threshold events. WARN/ALERT remains visible as dose status but does not consume the three-alarm retrigger budget.

## 5. Dose-state and reset rule

Dose classification remains:

- `NORMAL`: dose rate `< LOW/WARN`
- `ALERT`: dose rate `>= LOW/WARN` and `< HIGH/ALARM`
- `ALARM`: dose rate `>= HIGH/ALARM`
- `OFFLINE`: existing stale/offline rule

The alarm-policy episode resets only when dose returns to `NORMAL`, meaning below LOW/WARN. Falling below HIGH while still at/above LOW/WARN does not reset it.

Example with LOW/WARN = 100 and HIGH/ALARM = 150:

- `155` -> ALARM
- `120` -> ALERT, policy episode remains active
- `99` -> NORMAL, counter and lock reset

## 6. Three-alarm retrigger rule

A detector may surface at most three operator-facing ALARM events in a burst:

1. ALARM #1
2. ALARM #2
3. ALARM #3
4. further qualifying events are blocked until NORMAL

After #3 is surfaced, the detector enters `RETRIGGER_LOCKED` immediately. The third alarm itself still remains a real operator-facing alarm and may require PIC response; only later alarms are blocked.

Only one operator-facing ALARM can be active for a detector at a time. Repeated source rows while the same operator-facing alarm is still active are coalesced and do not increment the counter.

A retrigger becomes eligible only after the previous operator-facing alarm has been responded to/silenced by a PIC and a new qualifying HIGH/ALARM event is observed.

## 7. Rolling five-minute burst window

The five-minute window is anchored to ALARM #1 of the current burst.

Example reaching lock:

```text
00:00  #1
00:03  #2
00:04  #3 -> RETRIGGER_LOCKED
```

After #3, time no longer unlocks the detector. Only dose returning below LOW/WARN unlocks it.

If #3 is not reached before the window expires, the next eligible alarm starts a new burst at #1:

```text
00:00  #1
00:03  #2
00:07  #1 of new burst
```

Boundary rule: an eligible event with `event_time - window_started_at <= 5 minutes` stays in the current burst; greater than five minutes starts a new burst.

## 8. Timed suppression

Suppression is per detector and always time-bounded.

### 8.1 Required input

Starting suppression requires:

- authenticated Administrator or Operator
- sensitive-operation PIN
- detector
- duration
- PIC
- reason
- checkbox `Aktifkan kembali otomatis saat laju dosis kembali NORMAL`

Duration presets are 5, 15, 30, and 60 minutes plus custom duration. Custom duration is 1 minute through 24 hours. There is no indefinite mode.

PIC is prefilled from the signed-in user's display name and remains editable when the actual responsible PIC differs. The authenticated username is always stored separately as immutable `started_by` for audit integrity.

The auto-resume checkbox defaults to checked. The operator may uncheck it if suppression must remain active for the full selected duration.

### 8.2 SUPPRESSED presentation

During an active session, the effective policy status is `SUPPRESSED`.

`SUPPRESSED` must be visually prominent and must never imply safe dose. The UI always exposes the actual dose rate and underlying dose condition. Example:

```text
SUPPRESSED
Dose status: ALARM
142.5 uSv/h
PIC: Operator A
Reason: Calibration
Remaining: 12:34
```

### 8.3 Auto-resume on NORMAL

If the checkbox is checked, suppression ends immediately when dose becomes `NORMAL` (`< LOW/WARN`) with end reason `AUTO_NORMAL`.

If the checkbox is unchecked, suppression remains active until expiry even if dose becomes NORMAL. The alarm episode itself still resets on NORMAL, but the suppression session continues until its timer expires.

### 8.4 Expiry

At `expires_at`, suppression ends with reason `EXPIRED`.

If dose is still HIGH/ALARM at expiry, central immediately creates a new operator-facing ALARM #1. It does not wait silently for a future source alarm row. This may be a central-policy synthetic event and does not require inserting a new source alarm row.

### 8.5 Starting suppression during an active alarm

If suppression starts while a detector already has an active operator-facing alarm, the active alarm is responded to/silenced with the suppression PIC and reason. If a matching active source row exists, normal legacy write-through is performed. The original alarm remains in history as the pre-suppression alarm.

## 9. Suppression anti-spam contract

The user-visible rule is strict: **at most one operator-facing `SUPPRESSED` event per detector per suppression session**.

The first qualifying HIGH/ALARM source event during the session may create that single `SUPPRESSED` event. It is immediately auto-silenced by policy and records suppression PIC/reason.

Every later HIGH/ALARM source event in the same session:

- may remain in raw source history
- may remain mirrored centrally for traceability
- does not create another operator-facing row
- does not play sound
- does not notify
- does not increment the three-alarm counter
- is written back as source-silenced (`i_flag = 1`) when possible

The one-event rule must be enforced by persistence uniqueness/transaction logic, not only by in-memory checks.

## 10. Raw alarm mirror vs operator-facing events

Raw traceability and operator-facing alarm state are separate.

### 10.1 `remote_alarm_state`

The existing raw mirror remains the representation of source alarm rows. Add policy metadata as needed:

```text
policy_decision
suppression_id
operator_visible
policy_event_id
```

Policy decisions include:

- `ACTIVE`
- `COALESCED_DUPLICATE`
- `SUPPRESSED_PRIMARY`
- `SUPPRESSED_DUPLICATE`
- `RETRIGGER_LOCKED`

Raw mirrored rows are not deleted simply because they are hidden from the operator-facing Alarm page.

### 10.2 `alarm_policy_event`

A new central SQLite table contains operator-facing and central synthetic policy events:

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

Requirements:

- deterministic `event_key` prevents duplicates across polling/restart
- one `SUPPRESSED` policy event per `suppression_id` is enforced transactionally
- synthetic expiry alarms use deterministic keys as well

## 11. Persistent alarm-policy state

Canonical policy state lives in the existing central runtime/security SQLite database.

### 11.1 `alarm_policy_state`

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

- `trigger_count` is 0..3
- `retrigger_locked = 1` requires `trigger_count = 3`
- updates are atomic per detector

### 11.2 `alarm_suppression`

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

Only one active suppression may exist per detector. Persistence must prevent overlapping active sessions.

Allowed normal end reasons:

- `AUTO_NORMAL`
- `EXPIRED`

There is no ordinary operator path for indefinite suppression or un-audited force-disable.

## 12. Grafana runtime projection

Grafana reads MariaDB, not central SQLite, so canonical SQLite policy state is projected into a small central-only MariaDB table on PC `.2`:

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

This table is never created on `.50`, `.52`, or `.38`.

Projection is rebuilt/upserted from canonical policy state plus current central `vrecent`. Projection failure must not disable policy enforcement; it only affects Grafana freshness and is logged/audited.

Grafana joins `vrecent` to `radmon_runtime_status`.

Effective visual priority:

1. `OFFLINE`
2. `SUPPRESSED`
3. `ALARM`
4. `ALERT`
5. `NORMAL`

When SUPPRESSED, actual dose and `underlying_dose_status` remain visible.

## 13. Operator response behavior

Operator response remains a sensitive action.

For source-backed policy events, response writes:

- `i_op`
- `pic`
- `note`
- `i_flag: 0 -> 1`
- preserves `ack`

For central synthetic events with no source row, response is central-only. If a later source row matches the same already-resolved policy condition, it must not create a new operator-facing event; central may auto-apply the existing response/suppression decision to that source row.

Every response is audited.

## 14. Permissions and audit

Role behavior:

- Administrator: view, respond, suppress
- Operator: view, respond, suppress
- Viewer: view only

Add dedicated permission `suppress_alarm` to Administrator and Operator only.

Suppression uses existing sensitive-operation PIN handling. Explicitly supplied wrong PIN is rejected even if a short sensitive-operation lease is currently active.

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

Audit captures actor, role, detector, source when applicable, before/after state, success, and failure reason.

## 15. API surface

Add authenticated central endpoints:

```text
GET  /api/v1/control/alarm-events
POST /api/v1/control/alarm-events/{event_id}/response
GET  /api/v1/control/alarm-policy/{serid}
GET  /api/v1/control/suppressions
POST /api/v1/control/suppressions/{serid}
```

Suppression request:

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

- authentication required
- role must allow `suppress_alarm`
- PIN required and valid
- duration 60..86400 seconds
- PIC non-empty
- reason non-empty
- detector must exist
- overlapping active suppression returns conflict

Existing `/api/v1/control/alarms` may remain as a compatibility facade, but operator-facing UI must consume policy-filtered events rather than raw mirrored rows.

## 16. Concurrency and idempotency

Collector cycles, source mirroring, operator API calls, suppression expiry, and desktop refresh can overlap.

Requirements:

- policy evaluation serialized/atomic per detector
- SQLite transaction boundaries around state transitions
- deterministic unique keys for policy events
- persistence-enforced one active suppression per detector
- persistence-enforced one visible SUPPRESSED event per session
- repeated polling of a source row is idempotent
- repeated notification attempts consult persisted `notification_sent_at`
- trigger counter increments only when a new operator-facing ALARM is successfully created
- coalesced duplicates, SUPPRESSED events, and RETRIGGER_LOCKED rows do not increment the counter

After central restart:

- active suppression is restored until expiry or AUTO_NORMAL
- trigger count survives
- retrigger lock survives
- notification-sent state survives
- historical source rows are not resent as new alarms

## 17. Source write-through failure behavior

Central policy enforcement must not depend on remote write-through succeeding.

If `i_flag = 1` write-through fails:

- central still suppresses sound/notification according to policy
- raw row records pending/failed source silence state
- audit records failure
- retry happens on later cycle with bounded backoff
- UI shows source-side silence is not yet confirmed

A source write failure must never cause duplicate operator notifications for the same policy event.

## 18. Desktop suppression UI

`Suppress Alarm...` is available from the selected detector and Alarm page.

Dialog fields:

- detector identity, read-only
- current dose and underlying dose status, read-only
- duration preset/custom
- PIC, prefilled
- reason, required
- checkbox `Aktifkan kembali otomatis saat laju dosis kembali NORMAL`
- sensitive PIN
- explicit notice that measurements continue and only alarm surfacing/notification is suppressed

While active, SUPPRESSED appears prominently in:

- station tree
- Recent page
- Alarm page
- status/details panel
- Grafana monitoring

Where space allows, show PIC, reason, expiry/remaining time, and underlying dose state. Compact views use tooltip/detail panel for full metadata.

A detector that reached #3 while still abnormal shows `RETRIGGER LOCKED` in detailed views without replacing the underlying ALARM/ALERT dose state.

## 19. Icon-system redesign

The existing Silk set is too small and currently causes unrelated features to share icons. The redesign vendors a selected subset of Tabler Icons under the Tabler MIT license and uses the Tabler Outline family for every visible feature/command migrated in this scope.

Icons are local assets with no runtime network dependency.

### 19.1 Semantic registry

UI code calls a semantic registry such as `app_icon(slot)` rather than raw filenames.

Distinct visible features/commands receive distinct semantic slots. The same icon may be reused only when the UI is literally the same action in multiple places, for example Refresh in menu and toolbar, or the same Print action exposed twice.

### 19.2 Primary navigation and operational features

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

### 19.3 File/menu/toolbar commands

| UI command | Tabler Outline icon |
| --- | --- |
| Save As / generic export | `file-export` |
| Save As CSV | `table-export` |
| Printer Setup | `settings-2` |
| Print Preview | `eye-check` |
| Print | `printer` |
| Select Period | `calendar` |
| New Station | `plus` |
| Application Options | `settings` |
| About | `file-info` |

`Station Properties` deliberately uses `settings-cog`, while general `Options` uses `settings`; they are related but visually distinct commands. `Printer Setup` uses `settings-2` and is not reused for either station configuration command.

No generic `feed`, `monitor`, `lock`, or other catch-all icon may be reused across unrelated features after migration. No emoji literals are used as UI icons.

Tests verify that all required assets exist, registry slots resolve to non-null QIcons, and distinct semantic features in the registry map to distinct icon files.

## 20. Grafana behavior

Grafana panels expose:

- current dose rate
- underlying dose status
- effective policy status
- suppression PIC/reason/expiry while suppressed
- trigger count and retrigger lock in detailed views

SUPPRESSED must be visually prominent and must not be styled or worded as NORMAL.

Existing WIB timestamp handling, 2-second dashboard refresh, and TV playlist behavior remain unchanged unless a separate performance issue is found during implementation.

## 21. Notification behavior

Only operator-facing policy events can notify.

Rules:

- ALARM #1/#2/#3 may notify once each
- duplicate source rows for an active alarm do not notify
- SUPPRESSED primary event does not send normal alarm notification
- SUPPRESSED duplicate rows do not notify
- RETRIGGER_LOCKED rows do not notify
- historical/backfill alarms do not notify
- synthetic ALARM #1 created at suppression expiry while still HIGH may notify once

Notification state is persisted and idempotent across restart.

## 22. Migration and startup ordering

Central SQLite migration is additive and idempotent. Existing users, sessions, audit history, mirrored alarms, LAN checkpoints, station mappings, and archive records are preserved.

Central MariaDB migration only creates/updates the central runtime projection on PC `.2`; source schemas remain untouched.

First startup after upgrade:

1. migrate central SQLite policy tables/columns
2. create central MariaDB runtime projection if absent
3. load persistent policy/suppression state
4. seed/refresh source alarm mirror as historical without notifications
5. derive current dose state from central `vrecent`
6. apply NORMAL reset or suppression-expiry transitions as required
7. publish runtime projection
8. enable normal policy notification processing

This ordering prevents old alarm rows from becoming new spam during rollout.

## 23. Automated test matrix

Implementation is not complete until automated tests cover at least the following.

### Threshold/reset

- below LOW -> NORMAL
- exactly LOW -> ALERT
- between LOW/HIGH -> ALERT
- exactly HIGH -> ALARM
- below HIGH but still at/above LOW does not reset
- below LOW resets counter and lock

### Three-alarm rule

- #1 surfaces, count 1
- response then #2 in window, count 2
- response then #3 in window, count 3 and lock
- fourth qualifying event is hidden/notified zero times
- duplicate raw rows while one alarm remains active are coalesced
- locked state survives restart
- NORMAL clears lock

### Five-minute window

- 00:00 #1, 00:03 #2, 00:04 #3 -> lock
- 00:00 #1, 00:03 #2, 00:07 next eligible -> new #1
- exactly +5:00 remains same burst
- greater than +5:00 starts new burst

### Suppression

- Administrator can start suppression
- Operator can start suppression
- Viewer cannot
- invalid/missing PIN rejected
- missing PIC rejected
- missing reason rejected
- duration outside 1 minute..24 hours rejected
- overlapping suppression rejected
- suppression survives restart
- expiry ends suppression
- auto-normal ends early only when checked
- ALERT does not count as NORMAL
- exactly one visible SUPPRESSED event per session
- many source ALARM rows during one suppression create no duplicate visible events or notifications
- SUPPRESSED events do not consume retrigger budget
- starting suppression while active ALARM safely silences/responds to it
- expiry while still HIGH immediately creates one ALARM #1

### Source write-through

- source response writes `i_op`, `pic`, `note`, `i_flag = 1`, preserves `ack`
- failure audited
- failure retried
- failure never re-notifies same policy event
- source recovery applies outstanding silence decisions without new operator spam

### Concurrency/idempotency

- duplicate polling creates one policy event
- concurrent policy evaluation cannot create duplicate #1
- concurrent suppression start creates at most one active session
- simultaneous first HIGH observations during suppression create one SUPPRESSED policy event

### UI/icons

- all semantic registry icons load
- distinct feature slots map to distinct icon files
- all migrated visible feature/command icons are Tabler Outline
- Station group != detector icon
- Monitoring != Server Test
- Alarm != Suppress Alarm
- Station Properties != Options != Printer Setup
- SUPPRESSED visible in station tree, Recent, Alarm page, and Grafana tests
- underlying dose remains visible while SUPPRESSED

### Regression

- source health isolation remains correct
- LIVE collection and bounded backfill remain correct
- historical alarm sync does not resend old alerts
- legacy source response compatibility remains intact
- Grafana WIB time handling remains correct
- archive/security settings remain intact
- full existing test suite remains green

## 24. Acceptance criteria

The revision is accepted only when:

- unrelated visible features/commands no longer share icons
- all migrated icons use one Tabler Outline visual family
- one detector surfaces no more than three ALARMs in a five-minute burst
- #3 locks further alarm surfacing until dose is below LOW/WARN
- timed suppression requires PIN, PIC, reason, and duration
- optional auto-resume on NORMAL works
- SUPPRESSED is prominent and never hides the underlying dose state
- exactly one operator-facing SUPPRESSED event exists per detector per suppression session
- source alarm history is preserved
- suppressed/locked duplicates never sound or notify
- restart preserves suppression, counter, lock, and notification idempotency
- source write failures are visible/audited and do not cause spam
- desktop Admin, Grafana, and authenticated API expose consistent effective policy state
- source MariaDB schemas remain unchanged
- all new tests and the full existing suite pass before release
