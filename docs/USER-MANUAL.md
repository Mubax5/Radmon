# RadMon User Manual

## Desktop layout

The desktop keeps the established Radiation Monitoring workflow: station list on the left, station details below it, and `Recent`, `Tabular`, `Chart`, `Reports`, `Alarm`, and `Logs` tabs on the right.

## Recent

`Recent` is the multi-station live overview. It shows measurement time, dose rate, average dose rate, stored approximate dose, alert/alarm thresholds, and status. The `Date/Time | Message` panel is part of **Recent only**. Active central/LAN alarm messages and source-health warnings are shown there.

When a detector is **SUPPRESSED**, measurements do not stop. The actual dose rate and underlying `NORMAL` / `ALERT` / `ALARM` condition remain visible together with suppression PIC, reason, and expiry information.

## Tabular / Chart / Reports

Use `Select period...` to choose From/To time and presets such as Today, Yesterday, Last 7 days, This month, Last month, This year, or Last year. Reports can read the active central quarter and valid quarterly archives directly without restoring SQL.

Use `Save As CSV...`, Report PDF export, Print Preview, and Print as required for reporting workflows.

## Alarm policy

Operator-facing alarms use the central restart-safe alarm policy while the original source alarm rows remain raw evidence/history.

- A burst surfaces at most **3 ALARMs** under the rolling five-minute rule.
- The five-minute window is anchored to ALARM #1. A HIGH at `<= 5 minutes` remains in that burst; after `> 5 minutes`, a new burst starts if #3 was not reached.
- ALARM #3 immediately enters **RETRIGGER LOCKED**.
- `ALERT` does **not** reset the episode. The trigger count/lock resets only after a later true `NORMAL`, meaning dose rate `< LOW/WARN`.
- Historical/backfill seed rows remain visible as evidence but are not emitted as fresh operator notifications.

## ACK / Response

Select a policy alarm row, press **ACK / Response**, then enter Action, PIC, Note/Reason, and the sensitive-action PIN. Administrator and Operator may respond; Viewer is read-only.

The source-side response preserves legacy production semantics: RadMon writes `i_op`, `pic`, and `note`, transitions `i_flag` from `0` to `1`, and **does not change `ack`**. The source schema is not migrated by this feature.

If source write-through fails, the central policy response/suppression state is retained and the source-silence failure is audited/retried with bounded backoff rather than creating another operator-facing event.

## Timed suppression

Administrator and Operator may use **Suppress Alarm...** for a detector. Viewer cannot start suppression.

Suppression rules:

- duration is mandatory and must be **1 minute through 24 hours**;
- PIN, PIC, and reason are mandatory;
- suppression is per detector and only one active session may exist per detector;
- **Auto resume on NORMAL** is optional and enabled by default in the dialog;
- with auto-resume enabled, suppression ends only when dose rate becomes `< LOW/WARN`;
- a session that never sees HIGH creates **zero** `SUPPRESSED` policy events;
- a session that sees one or many HIGH states creates **exactly one** `SUPPRESSED` policy event;
- suppression never hides or stops measurements and never hides the underlying dose condition;
- expiry while the dose is still HIGH allows the normal alarm policy to surface a fresh alarm unless the detector remains `RETRIGGER LOCKED`.

Explicitly entering a wrong PIN is rejected even when the same user still has a short sensitive-operation lease.

## Grafana status

Grafana Operations joins the central-only `radmon_runtime_status` projection. `SUPPRESSED` is shown as a separate operational state while dose rate and `Underlying` remain visible. The existing WIB conversion, 2-second dashboard refresh, and 15-item/10-second playlist behavior are unchanged.

## Station properties

Administrator can open `Station properties` and edit `Attributes`, `Alarm`, and `Hardware` metadata. In LAN mode the production `device.serid` is authoritative, so Tag/SERID cannot be casually changed or manually created.

## Tools

- `Options...`: Administrator-only non-secret display/report/server preferences.
- `Test Server...`: read-only health GET against the configured RadMon central server.
- `Test Hardware...`: local detector serial open/read/close diagnostic only; it sends no serial command and no buzzer/relay command.
- `Acquisition Control...`: Administrator-only pause/resume for local detector/dummy acquisition. LAN acquisition remains owned by `central_server.py` and cannot be started from the desktop.

## About

RadMon creator: **Hilmi Mubarok**.

GitHub: https://github.com/Mubax5

Website: https://mubacs.site
