# RadMon User Manual

## Desktop layout

The desktop keeps the established Radiation Monitoring workflow: station list on the left, station details below it, and `Recent`, `Tabular`, `Chart`, `Reports`, `Alarm`, and `Logs` tabs on the right.

## Recent

`Recent` is the multi-station live overview. It shows measurement time, dose rate, average dose rate, stored approximate dose, alert/alarm thresholds, and status. The `Date/Time | Message` panel is part of **Recent only**. Active central/LAN alarm messages are shown there; changing to another tab removes the Message panel from view because it is not a global dock or popup.

## Tabular / Chart / Reports

Use `Select period...` to choose From/To time and presets such as Today, Yesterday, Last 7 days, This month, Last month, This year, or Last year. Reports can read the active central quarter and valid quarterly archives directly without restoring SQL.

Use `Save As CSV...`, Report PDF export, Print Preview, and Print as required for reporting workflows.

## Alarm

Select a date and number of days to browse alarm history. LAN alarms can be acknowledged by Administrator or Operator. ACK/Response requires Action, PIC, Note, and the sensitive-action PIN and is written through to the original production alarm row using the secured legacy contract.

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
