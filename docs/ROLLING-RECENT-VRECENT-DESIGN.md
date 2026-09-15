# Rolling `recent` / `vrecent` Monitoring Read Model

Date: 2026-09-15
Status: Design approved in chat; implementation pending
Branch: `feat/rolling-recent-vrecent`

## Goal

Keep RadMon's long-term detector data intact for reporting and audit use while making the monitoring path lightweight and predictable.

`measurement`, `alarm`, `rawdata`, archive/report data, and other historical relations remain the long-term source of truth and are not purged or reshaped by this work. Only `recent` and `vrecent` are redesigned.

The monitoring read model must cover the longest continuous dose trend currently shown by Grafana: three hours. Old rows may be removed from `recent` once they fall outside that rolling window because their authoritative copies remain in `measurement`.

## Non-goals and safety constraints

This work must not:

- delete, truncate, drop, or shorten retention for `measurement`;
- delete, truncate, drop, or shorten retention for `alarm`;
- delete, truncate, drop, or shorten retention for `rawdata`;
- alter detector/source databases on `.38`, `.50`, `.52`, or other LAN sources;
- fabricate detector values, timestamps, alarm states, or online status;
- change Grafana layout, panel placement, titles, or playlist structure unless a SQL field mapping must be updated for the new read model;
- change archive/report retention policy.

`recent` and `vrecent` are disposable/read-optimized structures and may be recreated from central historical data.

## Current problem

The current central `recent` relation is an aggregate/latest-state table with one row per SERID. It stores fields such as `minrate`, `maxrate`, `avgrate`, `meacount`, and latest values. `vrecent` exposes that state with device metadata.

Grafana uses `vrecent` for current values but still reads the large `measurement` history table for sparklines and three-hour trends. That puts high-frequency monitoring reads on the same historical table retained for years of reporting.

The desired architecture separates these workloads:

- historical/audit/reporting reads use `measurement`, `alarm`, archives, and reports;
- monitoring/Grafana dose-series reads use only the bounded rolling read model;
- current operational metadata and status are exposed through `vrecent`.

## Chosen architecture

### `recent`: rolling three-hour sample table

`recent` becomes a bounded table containing real central detector samples for at most the latest three hours.

Required columns:

```text
serid
dtom
doserate
dose
previnterval
stat
```

The implementation preserves compatible MariaDB column types from `measurement` rather than introducing lossy conversions.

Required indexes:

```sql
PRIMARY KEY (serid, dtom)
INDEX idx_recent_dtom (dtom)
```

The primary key makes live writes idempotent for an already-seen detector/timestamp. The time index makes retention cleanup cheap. Queries for one detector over a time range can use the composite primary key efficiently.

`recent` is not an aggregate table after this migration. Aggregate values needed by monitoring are computed over the bounded three-hour dataset.

### `vrecent`: monitoring view

`vrecent` remains a view and exposes the rolling samples from `recent` together with device metadata and existing RadMon runtime status.

Required exposed fields:

```text
serid
name
location
maxidlemin
warnlevel
alarmlevel
unit
audiopath
description
dtom
doserate
dose
previnterval
stat
underlying_status
status
suppressed
trigger_count
retrigger_locked
suppression_expires_at
suppression_pic
suppression_reason
```

`underlying_status` and `status` are derived from the existing `radmon_runtime_status` state, thresholds, suppression state, real `dtom`, and the configured `maxidlemin`. The view may join the existing runtime-status relation, but this work does not alter that table's schema or retention.

Because `vrecent` contains multiple rolling samples per SERID, current/latest consumers must explicitly select the newest row per SERID. Time-series consumers select the requested rows directly.

`vrecent` therefore supports two classes of monitoring query:

1. current/latest state: select the newest row per SERID from the rolling set;
2. bounded time series: select rows for a SERID/building within Grafana's requested interval, which must never exceed the configured rolling retention.

The implementation may use an internal SQL subquery/window expression when callers need one latest row per SERID. It must not restore unbounded reads from `measurement` on the normal monitoring path.

## Data flow

For every real detector sample collected into central MariaDB:

1. write the authoritative sample to `measurement` exactly as today;
2. write the same real sample to rolling `recent` in the same ingestion flow;
3. periodically delete only rows from `recent` older than the retention cutoff;
4. expose the remaining rows through `vrecent`.

No sample is invented to keep a detector online. Offline/online determination continues to use the real timestamp and configured idle threshold.

The authoritative `measurement` write takes precedence. A failure to mirror into `recent` must be logged and repaired by bounded reconciliation; it must not roll back or delete an already-preserved historical measurement.

## Retention

Default rolling retention: three hours.

Central detector timestamps are handled in the same WIB convention already used by RadMon. Cleanup is equivalent to:

```sql
DELETE FROM recent
WHERE dtom < DATE_SUB(CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00'), INTERVAL 3 HOUR)
```

Cleanup does not run for every individual sample. It runs on a low-frequency cadence, default once per minute, or behind a guard that prevents it from executing more frequently than the configured cleanup interval.

A small cleanup lag is acceptable; deleting historical authoritative rows is not.

## Migration strategy

Migration must be restart-safe and must never modify long-term historical relations.

At startup, inspect the central schema for the existing `recent`/`vrecent` shape.

If the new rolling shape is already present, do nothing destructive. Ensure `vrecent` is correct and continue.

If migration is required:

1. create a new temporary rolling table `recent_radmon_next` with the new columns and indexes;
2. backfill it from central `measurement` using only rows newer than the three-hour WIB cutoff;
3. validate the backfill: required columns/indexes exist and no row is outside the allowed retention window beyond cleanup tolerance;
4. drop/recreate only `vrecent` as needed to remove the dependency on the legacy `recent` shape;
5. atomically rename the existing `recent` to `recent_radmon_legacy` and `recent_radmon_next` to `recent` using MariaDB `RENAME TABLE` semantics;
6. create the new `vrecent` view;
7. validate latest timestamps and rolling-window sample counts against the source `measurement` rows;
8. only after validation succeeds may `recent_radmon_legacy` be dropped.

If any migration step fails before the successful swap, long-term tables remain untouched. If failure occurs after the table swap, startup fails visibly rather than silently running an invalid monitoring schema; `recent_radmon_legacy` remains available for recovery until validation has succeeded.

No migration metadata table is required; schema-shape detection makes the migration idempotent without modifying unrelated database structures.

## Source detector compatibility

Remote detector/source databases remain untouched. Their legacy `vrecent` is still read by the LAN collector exactly as required by each source schema.

The new rolling `recent`/`vrecent` schema applies only to the central RadMon MariaDB used by the authenticated web platform and Grafana.

Any targeted fallback to remote `measurement` used to recover a stale source snapshot remains a remote read only and does not alter that source database.

## Grafana query contract

Grafana layout and visual structure remain unchanged.

After migration:

- current dose panels use the newest per-SERID row from `vrecent`;
- latest measurement-time panels use the newest per-SERID row from `vrecent`;
- realtime sparklines use `vrecent`, not `measurement`;
- three-hour building trends use `vrecent`, not `measurement`;
- three-hour minimum/maximum/average summaries, if present, aggregate over `vrecent`;
- detector online/offline/alarm/warning current-state panels read the latest per-SERID `status` fields from `vrecent`.

The existing "Alarm Terbaru · 24 Jam" event table is intentionally allowed to continue querying `alarm`. Alarm events are a separate low-volume event log with a 24-hour dashboard requirement; forcing 24-hour alarm history into a three-hour rolling dose table would either lose required alarm events or violate the bounded three-hour design. This does not change or purge `alarm`.

No continuous dose/time-series Grafana query may contain `FROM measurement` after this migration.

## Web/control-plane contract

The Ringkasan/live monitoring path uses the newest per-SERID rows from the bounded read model and does not scan historical `measurement` during normal refresh.

History/report/archive features may continue to query historical tables because those features explicitly request historical data and are not part of the 2-second monitoring hot path.

The frontend single-flight/backpressure behavior already introduced for live overview refresh remains in place.

## Archive interaction

Current archive maintenance can rebuild legacy `recent` from an active quarter. That behavior must change because the new `recent` no longer represents quarter aggregates.

After archive/purge operations, rebuilding monitoring state means only:

- clear/recreate `recent` if required;
- backfill the most recent three hours still present in central `measurement`;
- recreate/validate `vrecent`.

Archive/purge code must never expand rolling `recent` to an entire quarter.

## Failure behavior

Monitoring read-model failures must be explicit and fail safe:

- failure to clean old `recent` rows may temporarily leave slightly more than three hours of data but must not delete authoritative history;
- failure to write a new `recent` row must not prevent the authoritative `measurement` write from being preserved;
- failure to migrate `recent`/`vrecent` must not trigger destructive fallback against `measurement`, `alarm`, or `rawdata`;
- schema validation errors must identify `recent`/`vrecent` specifically;
- Grafana must never substitute dummy values when data is absent.

If a sample is stored in `measurement` but its rolling mirror fails, the system logs the condition and performs bounded reconciliation from only the last three hours of `measurement`, never an unbounded historical scan.

## Performance expectations

At a two-second sample interval, 15 detectors over three hours produce about 81,000 rolling rows. This is small enough for indexed per-SERID and per-building range queries while keeping five years of historical data out of the realtime query path.

Normal monitoring operations are bounded by:

- one current/latest query over `vrecent`;
- indexed range queries over at most the three-hour rolling dataset;
- periodic indexed cleanup by `dtom`.

The normal monitoring path must not execute a full/correlated latest-value scan over five-year `measurement` history.

## Validation and tests

Implementation uses TDD and must add regression coverage for the following invariants:

1. migration changes only `recent`/`vrecent` plus temporary/legacy names used solely to swap `recent`; historical relations are not targeted by destructive DDL/DML;
2. pre-existing `measurement`, `alarm`, `rawdata`, and other historical rows remain unchanged after migration;
3. migration backfills only the latest three-hour measurement window;
4. rolling writes are idempotent on `(serid, dtom)`;
5. cleanup deletes only expired `recent` rows;
6. cleanup never emits `DELETE`, `TRUNCATE`, or `DROP` against `measurement`, `alarm`, or `rawdata`;
7. new `vrecent` exposes every field required by current monitoring and current-status Grafana panels;
8. all Grafana continuous dose/time-series SQL reads from `vrecent` and not `measurement`;
9. the 24-hour alarm-events panel remains backed by `alarm` and keeps its existing semantics;
10. remote source `vrecent` compatibility remains unchanged;
11. archive rebuild creates only the rolling three-hour read model;
12. restart/migration is idempotent;
13. full Python tests, frontend type-check/build, browser tests, Grafana payload validation, Windows packaging, installed smoke test, and upgrade-over-running-RadMon smoke test remain green.

## Deployment

Implementation is made on `feat/rolling-recent-vrecent` using tests-first changes.

After verification, the already-established RadMon deployment rule applies:

1. fast-forward verified changes to `main` when explicitly requested/approved by the user;
2. wait for Windows build/smoke tests;
3. verify Release `latest` tag points to the exact `main` SHA;
4. verify the new installer asset is published;
5. PC `.2` receives it through `RadMon Updater` if that updater task is already installed.

The first production startup after the upgrade performs the safe rolling-read-model migration and three-hour backfill from the existing central historical data.
