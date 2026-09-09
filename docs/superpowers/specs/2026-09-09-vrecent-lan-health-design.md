# VRecent LAN Monitoring Alignment Design

## Goal

Align RadMon central PC `192.168.1.2` with the production `ipradmon` schema demonstrated by `ipradmon-filled.sql`, while keeping history in `measurement`, authoritative live state in `recent`/`vrecent`, polling all three LAN sources every 2 seconds, and surfacing source connectivity failures to operators.

## Production schema contract

The database name remains `ipradmon`.

- `device`: detector metadata and thresholds.
- `measurement`: append-only measurement/history storage.
- `recent`: one operational snapshot row per detector, including `doserate`, `dose`, `lastrate`, `minrate`, `maxrate`, `avgrate`, `lastdose`, `mindose`, `maxdose`, `avgdose`, `firstmea`, `lastmea`, `lastmeasec`, `meacount`.
- `vrecent`: required view joining `device LEFT JOIN recent`, and the authoritative relation for current monitoring.
- `alarm`: legacy production fields `serid`, `dtoa`, `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, `i_flag` with primary identity `dtoa + serid`.
- `applog`: `ts`, `id`, `msg`.
- `news`: `ts`, `code`, `content`.
- `rawdata`: `serid`, `dtom`, `val`.

## Live and history data lanes

Every configured source is polled on a 2-second cadence. Each source iteration performs live-state and alarm work before bounded history catch-up.

1. Read source `vrecent` and upsert source metadata into central `device` plus the complete snapshot fields into central `recent`.
2. Read only alarm events newer than the source alarm checkpoint and mirror them into the central legacy `alarm` table and security sidecar.
3. Pull at most one configured batch of `measurement` history per detector per cycle. This prevents a first synchronization with millions of history rows from blocking live state and alarm polling.
4. Central `vrecent` is then the live read model for Admin/Grafana.

`measurement` remains the source for charts, reports, archives, exports, and time-series trends.

## Monitoring read path

Admin Recent and Grafana live/status panels query `vrecent`, never scan `measurement` for the latest value. Current average/dose values come from the source-maintained `recent` aggregate fields. Historical trend panels continue to query `measurement` using time-bounded predicates.

## Source health service

The security sidecar stores one health row per LAN source with: state, host, last success, last failure, last live poll, last alarm poll, last history import, last error, and consecutive failures.

States are `CONNECTED`, `DEGRADED`, `OFFLINE`, and `RECOVERED`. A first failure becomes `DEGRADED`; repeated failures transition to `OFFLINE`; a successful poll after an outage records `RECOVERED` and then healthy `CONNECTED` state on subsequent success. State transitions are audit/logged and exposed to Admin's Recent Message panel and secure control API. Failures of one source never stop the other sources.

## Alarm semantics

Alarm polling uses the legacy production schema and a per-source `(dtoa, serid)` checkpoint. The initial collector import mirrors existing rows without triggering historical WhatsApp delivery. ACK/Response remains explicit write-through to the originating source row guarded by `i_op IS NULL`, using the remote SERID and event `dtoa`.

## Station identity

Production metadata wins at runtime. The canonical fallback catalog is corrected to production identities `3003` for R. Sementasi and `5501` for PSLAT. The catalog remains fallback/dummy data only.

## Operational constraints

- Database name stays `ipradmon`.
- LAN default poll interval stays 2 seconds.
- Source database reads are read-only except explicit ACK/Response.
- No source schema migrations are performed.
- One source outage must not stop other source polling or erase central history.
- WhatsApp remains separately enableable and must not resend historical acknowledged/flagged source alarms during initial synchronization.
