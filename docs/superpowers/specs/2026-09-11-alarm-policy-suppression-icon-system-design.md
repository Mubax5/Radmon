# RadMon Alarm Policy, Suppression, and Icon System Design

Date: 2026-09-11  
Status: Approved design, pending implementation plan  
Target branch: `main`

## 1. Purpose

This design adds three coordinated revisions to RadMon:

1. a central alarm-policy layer with a three-trigger rolling-five-minute rule;
2. timed per-detector alarm suppression with mandatory PIC/reason/PIN, optional auto-resume on NORMAL, and strict anti-spam behavior;
3. a coherent Tabler Outline icon registry where distinct visible features/commands use distinct semantic icons.

The production source databases at `192.168.1.50`, `192.168.1.52`, and `192.168.1.38` stay legacy-compatible. No source schema migration is allowed. The central PC at `192.168.1.2` remains the policy owner for operator-facing alarm behavior.

## 2. Non-goals

This work does not change detector firmware, source-side acquisition logic, physical buzzer/relay control, or the production source schema. It does not delete source alarm history. It does not provide indefinite suppression. It does not hide the actual dose rate or underlying dose condition.

## 3. Existing production contract

RadMon pulls measurements and legacy alarm rows from the three production sources. Central realtime monitoring uses `recent`/`vrecent`. Source alarm rows use:

- key: `serid + dtoa`
- fields: `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, `i_flag`
- response write-through: set `i_op`, `pic`, `note`, transition `i_flag 0 -> 1`, preserve `ack`

Source failures remain isolated: one source being unavailable must not stop the others.

## 4. Policy ownership and component boundaries

The central service becomes the single owner of operator-facing alarm policy. Source systems may keep generating legacy alarm rows exactly as today; central decides whether an event is surfaced, notified, coalesced, suppressed, or blocked.

Implementation boundaries are intentionally separated:

- `AlarmPolicyService`: detector state machine, rolling window, three-trigger limit, normal reset, policy-event creation.
- `AlarmSuppressionService`: create/restore/expire timed suppression and auto-resume on NORMAL.
- `RemoteAlarmMirror`: raw source traceability and source-event idempotency; it does not decide operator-visible alarm behavior.
- `AlarmControlService`: operator response and source write-through.
- `RuntimeStatusProjector`: projects current policy state to central MariaDB for Grafana.
- Desktop/Admin UI: consumes policy services and shows effective state plus underlying dose state.
- Secure API: exposes the same policy/suppression operations for authenticated clients.
- Icon registry: maps semantic UI slots to vendored Tabler Outline assets.

The policy applies to HIGH/ALARM threshold events. WARN/ALERT remains visible but does not consume the three-alarm budget.

## 5. Dose state and reset rule

Dose classification remains:

- `NORMAL`: dose rate `< LOW/WARN`
- `ALERT`: dose rate `>= LOW/WARN` and `< HIGH/ALARM`
- `ALARM`: dose rate `>= HIGH/ALARM`
- `OFFLINE`: existing stale/offline rule

The alarm-policy episode resets only at `NORMAL`, meaning below LOW/WARN. Falling below HIGH but staying at/above LOW/WARN does not reset it.

Example with LOW/WARN = 100 and HIGH/ALARM = 150:

- `155` -> ALARM
- `120` -> ALERT, episode remains active
- `99` -> NORMAL, counter and lock reset

## 6. Three-alarm retrigger rule

A detector may surface at most three operator-facing ALARM events in a burst:

1. ALARM #1
2. ALARM #2
3. ALARM #3
4. further qualifying events are blocked until NORMAL

After #3 is surfaced, the detector enters `RETRIGGER_LOCKED` immediately. The third alarm itself remains a real operator-facing alarm; only later alarms are blocked.

Only one operator-facing ALARM can be active per detector. Repeated source rows while that alarm is still active are coalesced and do not increment the counter.

A retrigger is eligible only after the previous operator-facing alarm has been responded to/silenced by a PIC and a new qualifying HIGH/ALARM event is observed.

## 7. Rolling five-minute window

The five-minute window is anchored to ALARM #1 of the current burst.

```text
00:00  #1
00:03  #2
00:04  #3 -> RETRIGGER_LOCKED
```

After #3, elapsed time does not unlock the detector. Only NORMAL does.

If #3 is not reached before the window expires, the next eligible alarm starts a new burst:

```text
00:00  #1
00:03  #2
00:07  #1 of new burst
```

Boundary rule: `event_time - window_started_at <= 5 minutes` remains in the same burst; greater than five minutes starts a new burst.

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

Duration presets are 5, 15, 30, and 60 minutes plus custom duration. Custom duration is 1 minute through 24 hours. No indefinite mode exists.

PIC is prefilled from the signed-in user's display name and remains editable when the actual responsible PIC differs. The authenticated username is stored separately as immutable `started_by`.

The auto-resume checkbox defaults to checked.

### 8.2 What suppression changes

Suppression affects operator-facing alarm surfacing, sound, and notification. It does not stop measurement collection and does not erase raw source alarm rows.

During an active session, effective policy status is `SUPPRESSED`.

The UI must show the actual dose and underlying dose state, for example:

```text
SUPPRESSED
Dose status: ALARM
142.5 uSv/h
PIC: Operator A
Reason: Calibration
Remaining: 12:34
```

### 8.3 Entering suppression and existing retrigger state

Starting suppression first resolves/silences any currently active operator-facing alarm using the suppression PIC and reason.

For a detector that is not already `RETRIGGER_LOCKED`, starting suppression closes the current non-locked burst and clears its rolling-window counter. This intentionally makes the next post-suppression HIGH alarm a fresh #1 rather than continuing an old pre-maintenance burst.

For a detector already in `RETRIGGER_LOCKED`, suppression does **not** clear the lock. The lock still requires an actual NORMAL reading before it may reset. This preserves the approved rule that a three-trigger lock is reset only by dose returning below LOW/WARN.

### 8.4 Auto-resume on NORMAL

If `auto_resume_on_normal` is checked, suppression ends immediately when dose becomes NORMAL (`< LOW/WARN`) with end reason `AUTO_NORMAL`.

If unchecked, suppression remains active until expiry even if dose becomes NORMAL. The alarm policy counter/lock still resets on that NORMAL reading, while suppression itself continues until expiry.

### 8.5 Expiry while dose is HIGH

At `expires_at`, suppression ends with reason `EXPIRED`.

If dose is still HIGH/ALARM:

- if the detector is still `RETRIGGER_LOCKED`, no new alarm is surfaced; it remains locked until NORMAL;
- otherwise central immediately creates a fresh operator-facing ALARM #1 with a new rolling-five-minute burst, without waiting for a future source row.

The post-expiry event may be central-policy-originated and does not require inserting a new legacy source alarm row.

## 9. Strict suppression anti-spam contract

The rule is exact:

- if no qualifying HIGH occurs during a suppression session, zero `SUPPRESSED` alarm events are created;
- if one or more qualifying HIGH states/events occur during the session, exactly one operator-facing `SUPPRESSED` event is created for that detector/session;
- never more than one.

The central policy evaluates current dose every live cycle, so the first HIGH during suppression creates the single SUPPRESSED policy event even if a source alarm row has not yet appeared. If suppression starts while dose is already HIGH, the first policy evaluation under the new session creates that one SUPPRESSED event immediately.

That event is auto-silenced by policy and does not send the normal alarm notification.

Every later HIGH/ALARM source event in the same session:

- may remain in raw source history;
- may remain mirrored centrally for traceability;
- is linked/coalesced to the same suppression session;
- does not create another operator-facing alarm row;
- does not play sound;
- does not notify;
- does not increment the three-alarm counter;
- is written back as source-silenced (`i_flag = 1`) when possible.

The one-visible-event rule must be enforced by persistence uniqueness/transaction logic, not only by an in-memory condition.

## 10. Raw mirror vs operator-facing policy events

### 10.1 `remote_alarm_state`

The existing raw mirror remains the traceable representation of source alarm rows. Add policy metadata as required:

```text
policy_decision
suppression_id
operator_visible
policy_event_id
source_silence_state
source_silence_retry_at
```

Policy decisions include:

- `ACTIVE`
- `COALESCED_DUPLICATE`
- `SUPPRESSED_PRIMARY`
- `SUPPRESSED_DUPLICATE`
- `RETRIGGER_LOCKED`

Raw rows are not deleted merely because they are hidden from operators.

### 10.2 `alarm_policy_event`

A new central SQLite table stores operator-facing and central synthetic events:

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

- deterministic `event_key` prevents duplicates across polling/restart;
- one `SUPPRESSED` policy event per `suppression_id` is enforced transactionally;
- synthetic post-expiry alarms use deterministic keys too.

## 11. Persistent policy tables

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

- `trigger_count` is 0..3;
- `retrigger_locked = 1` requires `trigger_count = 3`;
- updates are atomic per detector.

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

Only one active suppression may exist per detector. Persistence prevents overlap.

Normal end reasons are `AUTO_NORMAL` and `EXPIRED`.

## 12. Central MariaDB projection for Grafana

Grafana reads MariaDB, so canonical SQLite state is projected to a small central-only table on PC `.2`:

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

Projection failure must not disable alarm policy; it only makes Grafana policy display temporarily stale and is logged/audited.

Grafana joins `vrecent` with `radmon_runtime_status`.

Effective visual priority:

1. `OFFLINE`
2. `SUPPRESSED`
3. `ALARM`
4. `ALERT`
5. `NORMAL`

When SUPPRESSED, actual dose and `underlying_dose_status` remain visible.

## 13. Operator response and source write-through

Operator response remains a sensitive action.

For source-backed policy events, response writes:

- `i_op`
- `pic`
- `note`
- `i_flag: 0 -> 1`
- preserves `ack`

For a central synthetic event with no source row, response is central-only. If a later source row corresponds to the same already-resolved policy condition, it must not create a new operator-facing event; central may auto-apply the existing response/suppression decision to that source row.

Every response is audited.

## 14. Source write-through failure behavior

Central policy enforcement does not depend on remote write-through succeeding.

If a source-side silence write fails:

- central still suppresses sound/notification according to policy;
- the raw row records failed/pending source-silence state;
- audit records the failure;
- retry occurs later with bounded backoff;
- UI indicates source-side silence is not yet confirmed.

A source write failure must never cause duplicate operator notifications.

## 15. Permissions and audit

Role behavior:

- Administrator: view, respond, suppress
- Operator: view, respond, suppress
- Viewer: view only

Add permission `suppress_alarm` to Administrator and Operator only.

Suppression uses existing sensitive-operation PIN handling. An explicitly supplied wrong PIN is rejected even if a short sensitive-operation lease is active.

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

## 16. API surface

Add authenticated endpoints:

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

- authentication required;
- role must allow `suppress_alarm`;
- PIN required and valid;
- duration 60..86400 seconds;
- PIC non-empty;
- reason non-empty;
- detector must exist;
- overlapping active suppression returns conflict.

Existing `/api/v1/control/alarms` may remain as a compatibility facade, but operator UI consumes policy-filtered events rather than raw mirror rows.

## 17. Concurrency and idempotency

Collector cycles, source mirroring, operator calls, suppression expiry, and desktop refresh can overlap.

Requirements:

- policy evaluation is serialized/atomic per detector;
- SQLite transactions protect state transitions;
- policy events use deterministic unique keys;
- one active suppression per detector is persistence-enforced;
- one SUPPRESSED event per session is persistence-enforced;
- repeated polling of a source row is idempotent;
- notification attempts consult persisted `notification_sent_at`;
- trigger counter increments only when a new operator-facing ALARM is successfully created;
- coalesced, SUPPRESSED, and RETRIGGER_LOCKED rows do not increment the counter.

After central restart:

- active suppression is restored until expiry or AUTO_NORMAL;
- trigger count survives;
- retrigger lock survives;
- notification-sent state survives;
- historical source rows are not resent as new alarms.

## 18. Desktop suppression UI

`Suppress Alarm...` is available from the selected detector and Alarm page.

Dialog fields:

- detector identity, read-only;
- current dose and underlying dose state, read-only;
- duration preset/custom;
- PIC, prefilled;
- reason, required;
- checkbox `Aktifkan kembali otomatis saat laju dosis kembali NORMAL`;
- sensitive PIN;
- notice that measurements continue and only alarm surfacing/notification is suppressed.

SUPPRESSED appears prominently in:

- station tree;
- Recent page;
- Alarm page;
- status/details panel;
- Grafana monitoring.

Where space allows, show PIC, reason, expiry/remaining time, and underlying dose state. Compact views use tooltip/detail panel for complete metadata.

A detector that reached #3 while still abnormal shows `RETRIGGER LOCKED` in detailed views without replacing the underlying ALARM/ALERT dose state.

## 19. Icon-system redesign

The current Silk set is too small and causes unrelated features to share symbols. This redesign vendors a selected subset of Tabler Icons under the Tabler MIT license and uses only Tabler Outline for migrated visible feature/command icons.

Icons are local assets with no runtime network dependency.

UI code calls a semantic registry such as `app_icon(slot)` rather than raw filenames. Distinct visible features/commands receive distinct semantic slots. The same icon may be reused only when it is literally the same action exposed in multiple UI locations, such as one Refresh action in both menu and toolbar.

### 19.1 Primary navigation and operational features

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

### 19.2 File/menu/toolbar commands

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

`Station Properties`, `Application Options`, and `Printer Setup` deliberately use different settings-related icons. Monitoring, Station group, detector child, Server Test, Alarm, and Suppress Alarm all use distinct icons.

No generic `feed`, `monitor`, `lock`, or similar catch-all symbol may remain mapped to unrelated visible features after migration. No emoji literals are used as UI icons.

Tests verify asset existence, non-null QIcons, one visual family, and semantic uniqueness.

## 20. Grafana behavior

Grafana panels expose:

- current dose rate;
- underlying dose status;
- effective policy status;
- suppression PIC/reason/expiry while suppressed;
- trigger count/retrigger lock in detailed views.

SUPPRESSED must be prominent and must not be styled or worded as NORMAL.

Existing WIB timestamp handling, 2-second dashboard refresh, and TV playlist behavior remain unchanged unless a separate performance problem is found.

## 21. Notification behavior

Only operator-facing policy events can notify.

Rules:

- ALARM #1/#2/#3 may notify once each;
- duplicate source rows for an active alarm do not notify;
- SUPPRESSED event does not send normal alarm notification;
- later source rows in the same suppression do not notify;
- RETRIGGER_LOCKED rows do not notify;
- historical/backfill alarms do not notify;
- synthetic post-expiry ALARM #1 may notify once when not locked.

Notification state is persisted and idempotent across restart.

## 22. Migration and startup ordering

Central SQLite migration is additive/idempotent. Existing users, sessions, audit history, raw alarm mirror, LAN checkpoints, station mappings, and archive records are preserved.

Central MariaDB migration creates only the central runtime projection on PC `.2`; source schemas remain untouched.

First startup after upgrade:

1. migrate central SQLite policy tables/columns;
2. create central MariaDB runtime projection if absent;
3. load persistent policy/suppression state;
4. seed/refresh source alarm mirror as historical without notifications;
5. derive current dose state from central `vrecent`;
6. apply NORMAL reset, suppression expiry, or lock rules as required;
7. publish runtime projection;
8. enable normal policy notification processing.

This prevents historical alarms from becoming new spam during rollout.

## 23. Automated test matrix

Implementation is incomplete until automated tests cover all of these behaviors.

### Threshold/reset

- below LOW -> NORMAL;
- exactly LOW -> ALERT;
- between LOW/HIGH -> ALERT;
- exactly HIGH -> ALARM;
- below HIGH but still at/above LOW does not reset;
- below LOW resets counter and lock.

### Three-alarm rule

- #1 surfaces, count 1;
- response then #2 in window, count 2;
- response then #3 in window, count 3 and lock;
- fourth qualifying event is hidden and not notified;
- repeated raw rows while one alarm remains active are coalesced;
- locked state survives restart;
- NORMAL clears lock.

### Five-minute window

- 00:00 #1, 00:03 #2, 00:04 #3 -> lock;
- 00:00 #1, 00:03 #2, 00:07 next eligible -> new #1;
- exactly +5:00 remains same burst;
- greater than +5:00 starts new burst.

### Suppression

- Administrator can start;
- Operator can start;
- Viewer cannot;
- invalid/missing PIN rejected;
- missing PIC rejected;
- missing reason rejected;
- duration outside 1 minute..24 hours rejected;
- overlapping suppression rejected;
- non-locked pre-suppression burst is cleared on suppression start;
- pre-existing RETRIGGER_LOCKED survives suppression until NORMAL;
- suppression survives restart;
- expiry ends suppression;
- auto-normal ends early only when checked;
- ALERT does not count as NORMAL;
- no HIGH during session -> zero SUPPRESSED event;
- HIGH during session -> exactly one SUPPRESSED event;
- suppression starting while already HIGH creates the one SUPPRESSED event immediately;
- many source ALARM rows during one suppression create no duplicate visible event or notification;
- SUPPRESSED events do not consume retrigger budget;
- starting suppression while active ALARM resolves/silences that active event;
- expiry while still HIGH and not locked creates one fresh ALARM #1;
- expiry while still HIGH and already locked creates no new alarm until NORMAL.

### Source write-through

- writes `i_op`, `pic`, `note`, `i_flag = 1`, preserves `ack`;
- failure audited;
- failure retried;
- failure never re-notifies same policy event;
- source recovery applies outstanding silence decisions without new operator spam.

### Concurrency/idempotency

- duplicate polling creates one policy event;
- concurrent evaluation cannot create duplicate #1;
- concurrent suppression start creates at most one active session;
- simultaneous first HIGH observations during suppression create one SUPPRESSED event.

### UI/icons

- all semantic registry icons load;
- distinct feature slots map to distinct icon files;
- migrated visible feature/command icons are Tabler Outline;
- Station group != detector icon;
- Monitoring != Server Test;
- Alarm != Suppress Alarm;
- Station Properties != Application Options != Printer Setup;
- SUPPRESSED visible in station tree, Recent, Alarm page, and Grafana tests;
- underlying dose remains visible while SUPPRESSED.

### Regression

- source health isolation remains correct;
- LIVE collection and bounded backfill remain correct;
- historical alarm sync does not resend old alerts;
- legacy source response compatibility remains intact;
- Grafana WIB time handling remains correct;
- archive/security settings remain intact;
- full existing test suite remains green.

## 24. Acceptance criteria

The revision is accepted only when:

- unrelated visible features/commands no longer share icons;
- all migrated icons use one Tabler Outline family;
- one detector surfaces no more than three ALARMs in a five-minute burst;
- #3 blocks later alarms until dose is below LOW/WARN;
- timed suppression requires PIN, PIC, reason, and duration;
- optional auto-resume on NORMAL works;
- SUPPRESSED is prominent and never hides underlying dose;
- any suppression session with HIGH produces exactly one operator-facing SUPPRESSED event, never more;
- source alarm history is preserved;
- suppressed/locked duplicates never sound or notify;
- restart preserves suppression, counter, lock, and notification idempotency;
- source write failures are visible/audited and do not cause spam;
- desktop Admin, Grafana, and authenticated API expose consistent effective policy state;
- source MariaDB schemas remain unchanged;
- all new tests and the full existing suite pass before release.
