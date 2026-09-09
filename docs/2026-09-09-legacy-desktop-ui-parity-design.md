# RadMon Legacy Desktop UI Parity Design

Date: 2026-09-09
Status: Approved from screenshot review and direct implementation instruction
Target branch: `main`

## 1. Goal

Bring the current PySide6 RadMon desktop Admin workflow up to functional parity with the supplied legacy Radiation Monitoring screenshots while preserving the current secure backend, LAN-central architecture, quarterly archive subsystem, Grafana monitoring, roles/PIN, audit, and ACK write-through safety.

This is workflow parity, not a full rewrite and not a pixel-for-pixel clone. Existing secure/newer capabilities remain authoritative where the legacy application is weaker.

## 2. Desktop shell

The main window keeps the established legacy structure:

- menu bar: `File`, `View`, `Tools`, `Help` plus the existing security/account controls;
- Silk-icon toolbar;
- station tree on the left;
- selected-station detail panel below the tree with `Tag`, `Name`, `Location`, `Description`, `Update`;
- tabs in this order: `Recent`, `Tabular`, `Chart`, `Reports`, `Alarm`, `Logs`;
- status bar at the bottom.

The selected station drives all station-aware pages.

## 3. Recent tab and Message panel

The legacy Recent screen is restored as a multi-station overview table with these user-facing columns:

- Station
- Measurement Time
- Dose Rate `[µSv/h]`
- Avg. Dose Rate `[µSv/h]`
- Approx. Dose `[µSv]`
- Low Threshold
- High Threshold
- Alarm

The Alarm cell uses an icon/visual state consistent with the existing status classifier.

A `Date/Time | Message` panel is embedded at the bottom of **RecentPage itself**.

Hard requirement: the Message panel is **not** a separate top-level window, dock, modal, or global widget, and it is **not present** in Tabular, Chart, Reports, Alarm, or Logs. Active-alarm information that previously used the global bottom `QDockWidget` is routed into this Recent-only message panel instead.

## 4. Period selection

A reusable `PeriodSelectionDialog` mirrors the supplied legacy dialog:

- `From` date/time;
- `To` date/time;
- grouping selector;
- presets `Today`, `Yesterday`, `Last 7 days`, `This month`, `Last month`, `This year`, `Last year`;
- OK/Cancel.

It exposes a simple result contract `(start, end, grouping)` and can be used by Tabular, Chart, Reports, and other range-based pages without duplicating date logic.

## 5. Station properties

Station editing is expanded to the legacy three-tab dialog:

### Attributes
- Tag / SERID
- Name
- Location
- Description

### Alarm
- Low/Alert threshold
- High/Alarm threshold
- Max Idle in minutes
- optional Audio path presentation field

### Hardware
- Type
- Address/serial binding
- Unit

Current security rules remain in force: station mutation requires Administrator role + PIN.

In LAN-central mode, production `device.serid` remains authoritative. The UI must not silently invent or migrate production SERIDs. Any SERID migration remains an explicit Administrator action using the existing secured service and is not enabled as a casual LAN edit.

`New Station...` may exist for legacy parity only where local detector/dummy administration can safely support it; LAN-central mode must not create synthetic production identities.

## 6. Options

An `OptionsDialog` mirrors the legacy three-tab structure.

### Display
- refresh interval;
- date format;
- date/time format;
- dose-rate format;
- dose format;
- threshold format;
- Warning display color;
- Alarm display color.

### File & Report
- CSV delimiter;
- report directory;
- institution;
- institution address.

### Server
- server URI;
- API path;
- API version display;
- URI date/time format.

Non-secret desktop preferences are stored using Qt `QSettings` under the RadMon application namespace. Production DB passwords, user passwords, PIN hashes, API secrets, and other sensitive credentials are never persisted through this dialog.

## 7. File / View / Tools / Help parity

### File
- Save As...
- Save As CSV...
- Printer Setup...
- Print Preview...
- Print...
- Exit

These actions delegate to the active page where meaningful. Report/Tabular export capabilities already present are reused rather than duplicated.

### View
- Recent Values
- Tabular View
- Chart Display
- Reports
- Alarm
- Log
- Refresh

### Tools
- Options...
- Test Server...
- Test Hardware...
- Acquisition Control...

### Help
- Installation Manual...
- User Manual...
- About...

Unavailable documentation files show a friendly message instead of crashing.

## 8. Server Test

`ServerTestDialog` follows the supplied legacy screenshot style: a read-only scrolling result pane with Save/Close controls and line-oriented diagnostics such as server target, configuration, response/status, and completion.

It performs only read-only probes. The default RadMon target is the configured central API, normally `http://<RADMON_CENTRAL_HOST>:8090/health`, unless a non-secret Server URI preference overrides it.

No production DB mutation, ACK, credential display, or secret logging is permitted.

## 9. Hardware Test

`HardwareTestDialog` follows the legacy diagnostic presentation: a scrolling log plus Save/Close.

It may enumerate configured detector serial bindings and attempt read-only serial open/read diagnostics. It must never send serial commands, buzzer/relay commands, or arbitrary hardware writes.

For LAN mode it clearly reports that detector hardware acquisition belongs to production sources / central ingestion and does not create a second LAN collector.

## 10. Acquisition Control

The desktop can show acquisition status for local detector/dummy runtime. A small control dialog may pause/resume local acquisition using an explicit runtime gate.

- detector/dummy: pause/resume the local runtime safely;
- LAN: control is read-only/disabled because `central_server.py` is the single LAN collector owner.

Pausing detector acquisition closes/releases the serial port until resumed; it does not terminate the application.

## 11. Alarm tab

The Alarm page retains the current secure ACK/Response workflow and is adjusted toward the legacy table presentation:

- Tag
- Event time
- Threshold
- Dose rate
- Hit count
- Action Time
- PIC
- Action
- Note

A date selector and day-count/range control are provided for history browsing. LAN ACK still uses the secured source write-through keyed by source/SERID/event time and remains Operator/Administrator + PIN only.

## 12. Reports

Existing archive-aware Reports remains intact. Presentation is brought closer to the legacy report workflow while preserving:

- mandatory preview before print/PDF;
- active + archived-quarter reading without SQL restore;
- PDF and CSV export;
- institution header and station summary;
- range selection using the reusable period dialog where appropriate.

## 13. About

The About dialog includes current RadMon identity and explicitly credits:

- Creator: **Hilmi Mubarok**
- GitHub: `https://github.com/Mubax5`
- Website: `https://mubacs.site`

The links are clickable and open externally through Qt desktop services.

## 14. Security / safety preservation

The legacy parity work must not weaken:

- login/authentication;
- Viewer / Operator / Administrator authorization;
- separate sensitive-action PIN;
- structured audit;
- production DB read-only policy except ACK;
- LAN single-collector ownership;
- quarterly archive and 5-year archive reading;
- source-authoritative production SERID behavior;
- no physical buzzer/relay command requirement.

## 15. Testing contract

Automated tests must verify at minimum:

1. Message panel is implemented inside `RecentPage` only and no global `QDockWidget` active-alarm strip remains;
2. six legacy tabs remain in the expected order;
3. File/View/Tools/Help action labels are present;
4. period presets calculate correct boundaries;
5. Options persistence contains no secret fields;
6. Server Test uses a read-only health request and presents line-oriented output;
7. Hardware Test never writes to serial;
8. LAN mode cannot pause/resume or start a second collector through Acquisition Control;
9. local runtime pause/resume gate works for dummy/detector loops;
10. station property tabs and secured edit path remain present;
11. Alarm legacy columns are present while ACK role/PIN behavior stays intact;
12. About contains Hilmi Mubarok, GitHub, and `mubacs.site`;
13. existing archive/report/security/Grafana tests remain green;
14. full `pytest`, `compileall`, and Grafana payload validation pass on the final `main` HEAD.
