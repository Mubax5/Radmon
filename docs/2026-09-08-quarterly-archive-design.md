# RadMon Central Quarterly Archive Design

Date: 2026-09-08
Status: Approved design baseline, pending implementation plan
Target branch: `main`

## 1. Purpose

This design changes the RadMon central data lifecycle so the production-facing monitoring database on PC3 stays small and fast while regulatory history remains directly available for reporting for at least five years.

The change is limited to the RadMon central system. Production detector databases are never rotated, purged, or otherwise modified by archive operations.

## 2. Authoritative deployment facts

The physical topology image previously supplied is explicitly not authoritative for this design.

Current deployment facts supplied by the operator are:

- PC3 central RadMon host: `192.168.1.2`.
- PC2: `192.168.1.52`.
- PC1: `192.168.1.51`.
- PC3 reads directly from three primary production database servers configured in the local deployment environment. It does not obtain production data indirectly through PC1.
- The concrete IP addresses of the three production database servers are deployment configuration and must not be inferred from the old topology image or committed legacy examples.
- Production `device.serid` values are authoritative. Static/catalog SERIDs in the repository must not override, pre-create, rename, or replace production detector identity in LAN-central mode.

## 3. Production database safety boundary

The three production MariaDB databases are read-only to RadMon for normal operation.

Allowed production queries:

- `SELECT device`
- `SELECT measurement`
- `SELECT alarm`
- required schema/introspection reads

The only production write allowed is the already-approved alarm ACK/Response operation. It remains a guarded legacy write-through keyed by remote `SERID + dtoa`, with `i_op IS NULL`, and may update only the legacy ACK/response fields required by the existing workflow.

Archive, retention, reporting, central cleanup, station presentation, and quarter rollover must never run `DELETE`, `TRUNCATE`, archive DDL, or other mutations against a production source.

## 4. Runtime ownership on PC3

PC3 has one authoritative background owner for central LAN ingestion: `central_server.py`.

`central_server.py` owns:

- the three-source LAN collector;
- central measurement/alarm import;
- optional WhatsApp dispatch;
- quarter lifecycle checks;
- archive creation and verification;
- central-quarter purge after successful archive sealing;
- secure control API.

The desktop Admin must not start a second LAN collector. `RUN_LAN.bat` will be aligned to start or reuse the central service and then open the Admin/control presentation without creating another ingestion runtime.

This removes concurrent collectors competing for checkpoints, repeatedly polling production, or mirroring the same alarm simultaneously.

## 5. Production SERID identity contract

LAN-central mode discovers detector identity from each source's `device` table.

On first observation, the central identity is the production SERID itself. No static station catalog is seeded before LAN discovery.

The existing source mapping/checkpoint sidecar remains useful because ACK and checkpoints must always retain the original source identity. However, the default and expected mapping is:

```text
(source_id, production SERID) -> same central SERID
```

If the same SERID appears on two different production sources:

- identical/compatible station metadata may refer to the same detector only when explicitly expected by configuration;
- conflicting metadata must be surfaced as a source identity conflict and must not be silently merged.

LAN checkpoints remain keyed by `source_id + production SERID` and survive quarter rollover.

Detector/dummy modes outside central LAN may continue using the canonical catalog for their existing behavior; the restriction applies specifically to LAN-central operation.

## 6. Calendar-quarter model

Quarter boundaries use local WIB calendar time.

- Q1: 1 January 00:00 through 1 April 00:00
- Q2: 1 April 00:00 through 1 July 00:00
- Q3: 1 July 00:00 through 1 October 00:00
- Q4: 1 October 00:00 through 1 January of the following year

Archive intervals are half-open: `[quarter_start, next_quarter_start)`.

The active central `ipradmon` database is intended to contain the current quarter's operational/history rows plus durable station metadata needed by Grafana/Admin.

## 7. Quarter rollover state machine

A rollover is transactional in intent even though export files and MariaDB operations span multiple steps. The lifecycle is idempotent and resumable.

States are maintained in the local security/operations sidecar rather than by changing the production `ipradmon` schema:

```text
OPEN
  -> PENDING_DRAIN
  -> EXPORTING
  -> VERIFYING
  -> SEALED
  -> PURGING
  -> COMPLETE
```

A failure leaves the quarter at the last safe pre-destructive state and records the reason. Retrying does not duplicate a finalized archive.

### Boundary behavior

At the first check after a quarter boundary:

1. Determine the previous quarter interval.
2. Continue normal ingestion for the current quarter.
3. For each configured production source/station, drain all rows belonging to the previous quarter up to the quarter cutoff using persistent checkpoints/watermarks.
4. Do not declare the old quarter complete while a configured source cannot establish that its old-quarter backlog has been drained.
5. Export the previous-quarter central rows.
6. Verify archive completeness and checksums.
7. Only after successful verification, purge previous-quarter operational rows from the central MariaDB.
8. Rebuild `recent` from current-quarter latest data.
9. Mark the archive complete.

If a production source is offline at the boundary, the previous quarter remains pending instead of being deleted prematurely. Current-quarter ingestion for available sources continues.

## 8. Central rows affected by rollover

Quarter archive/export includes snapshots or rows for:

- `device` (station metadata snapshot for reproducibility)
- `measurement`
- `alarm`
- `rawdata`
- `applog`
- `news`

`recent` is a derived/cache table and is not a regulatory source of truth. Its relevant snapshot may be included for convenience, but after purge it is rebuilt for the active quarter from retained/current measurements.

Central cleanup may remove only old-quarter rows from time-series/event tables after successful archive verification.

Never purge:

- `device` station metadata required by current monitoring;
- LAN checkpoints;
- source-to-SERID mapping;
- users/password hashes/PIN hashes;
- web sessions solely because of quarter rollover;
- structured security audit records solely because of quarter rollover.

## 9. Archive package format

Default archive root is configurable and stored outside Git, for example:

```text
archives/
  2026/
    radmon-2026-Q3.zip
```

The ZIP contains deterministic UTF-8 exports:

```text
manifest.json
monthly-recap.csv
device.csv
measurement.csv
alarm.csv
rawdata.csv
applog.csv
news.csv
radmon-2026-Q3.sql
```

The implementation uses Python standard-library CSV/ZIP/hash support and does not require `mysqldump` to exist on the Windows deployment.

### CSV

CSV preserves the stored source values. In particular, archived `measurement.dose` is exported as stored and is not re-integrated during archival.

### SQL

The SQL artifact is a portable logical restore file for the archived central data. It contains explicit column lists and escaped values, transaction boundaries, and inserts for the quarter data plus the station metadata snapshot required to interpret it.

It does not contain production credentials, user passwords/PIN hashes, browser sessions, or other security-store secrets.

### Manifest and checksums

`manifest.json` includes at minimum:

- format version;
- quarter ID, start, and end timestamps;
- created timestamp;
- station/source inventory;
- row count per exported table;
- SHA-256 for every payload file;
- archive status/version metadata;
- source drain/watermark information used to seal the quarter.

Verification recalculates file hashes and confirms exported row counts before central purge is allowed.

## 10. Monthly recap for BAPETEN-oriented reporting

Each quarterly package contains a `monthly-recap.csv` with three calendar months for that quarter.

For each month and production SERID, recap includes at least:

- year;
- month;
- SERID;
- station name/location snapshot;
- first measurement time;
- last measurement time;
- sample count;
- minimum dose rate;
- average dose rate;
- maximum dose rate;
- sum of stored `measurement.dose`;
- ALERT event count;
- ALARM event count.

The manifest may additionally retain exact accumulator fields such as dose-rate sum/count so quarter/year summary aggregation can remain mathematically exact without loading every archived row.

An OFFLINE count is not invented unless a deterministic outage/gap rule based on deployed `maxidlemin` is explicitly implemented and tested. Missing-data periods remain distinguishable from alarm counts.

Admin Reports shows archive inventory and month coverage such as:

```text
2026 Q3 · July, August, September · Complete
2026 Q2 · April, May, June · Complete
```

## 11. Five-year retention

RadMon must make at least the most recent five years of quarterly archives directly available, corresponding to up to 20 complete quarters for a rolling five-year window.

Because these compressed archives are not the live database and regulatory retention is more important than saving a small amount of disk, automatic destructive deletion of archives older than five years is disabled by default.

A deployment may later enable an explicit retention/prune policy, but no archive is deleted merely because the active database rolled over. This guarantees that at least five years remain available and avoids unreviewed destruction of regulatory records.

## 12. Archive index

Archive lifecycle metadata is stored in the existing local SQLite security/operations sidecar, not in the legacy production schema.

New sidecar metadata records include, conceptually:

- quarter ID;
- start/end;
- state;
- archive path;
- archive SHA-256;
- row counts;
- created/sealed/purged timestamps;
- last error/retry metadata.

The filesystem manifest remains independently readable so archive recovery does not depend exclusively on the sidecar index.

On startup, the archive catalog reconciles the sidecar index with valid manifests found on disk.

## 13. Direct archived report reading

Archived quarters must be reportable without importing/restoring SQL into MariaDB.

A new archive repository/read layer presents the same logical interface used by `ReportService`:

- station metadata;
- measurement history;
- alarm history;
- summary information.

For an archived range, it streams CSV rows from the ZIP and filters by SERID/time. It does not load an entire five-year dataset into memory.

For the active quarter, queries continue to use MariaDB.

For a date range spanning active and archived quarters, a composite report repository:

1. partitions the requested range by quarter;
2. reads archived portions from the relevant ZIPs;
3. reads the active portion from MariaDB;
4. merges rows in timestamp order;
5. deduplicates by detector/time identity where necessary;
6. preserves the existing 250-row preview limit;
7. computes the full-range summary accurately across all partitions.

Existing PDF and CSV report export remain available for both active and archived ranges.

## 14. Admin Reports UX

The existing preview-first workflow remains intact.

Reports gains:

- a data-source/period indicator (`Active` or archived quarter coverage);
- an archive/quarter selector with month recap labels;
- an archive status/health display;
- direct Preview/Print/PDF/CSV for archived ranges;
- an `Export Quarter Package`/archive management action available only to Administrator where manual recovery/export is appropriate.

Normal automatic quarter rollover does not depend on an operator keeping the Admin UI open.

Sensitive manual archive/purge actions, if exposed, require Administrator role + PIN and are audited.

## 15. API surface

The secure server adds authenticated read-only endpoints sufficient for URL-based administration/reporting, for example:

```text
GET /api/v1/control/archives
GET /api/v1/control/archives/{quarter_id}/recap
```

Any manual archive/seal action is Administrator-only, PIN-gated, and calls the same idempotent lifecycle service as automatic rollover.

No endpoint exposes production database credentials or raw security-store secrets.

## 16. Audit and operational logging

Quarter lifecycle actions are visible in structured audit and human-readable `applog`, with system-triggered operations represented by a system/anonymous actor rather than a fake user identity.

Expected actions include:

```text
ARCHIVE_DRAIN_PENDING
ARCHIVE_EXPORT_START
ARCHIVE_EXPORT_SUCCESS
ARCHIVE_EXPORT_FAILED
ARCHIVE_VERIFY_SUCCESS
ARCHIVE_VERIFY_FAILED
ARCHIVE_PURGE_START
ARCHIVE_PURGE_SUCCESS
ARCHIVE_PURGE_FAILED
ARCHIVE_COMPLETE
ARCHIVE_MANUAL_RETRY
```

Before/after metadata includes quarter ID, paths, row counts, state, and failure reason where applicable. Credentials and secrets remain redacted by existing audit rules.

## 17. Failure safety and recovery

Required failure behavior:

- export failure: keep old-quarter data in central DB; no purge;
- checksum/count mismatch: keep old-quarter data; mark verification failed;
- purge failure: archive remains sealed; retry purge without recreating a different archive;
- missing/corrupt ZIP: Reports identifies archive as damaged and does not silently substitute data;
- source outage at boundary: keep quarter pending until drain completeness can be established;
- PC3 restart mid-export: resume/retry safely from lifecycle state;
- duplicate lifecycle invocation: do not produce conflicting final archives;
- disk-space failure: fail before purge and surface a visible/logged error.

Before export, available disk space should be checked against a conservative estimate of the archive working set.

## 18. LAN query/write contract enforcement

The LAN source abstraction should make the read/write boundary explicit:

- normal collector path exposes read methods only;
- ACK uses the dedicated `ack_legacy` write method;
- quarter/archive service receives no production write-capable repository and only operates on central MariaDB/filesystem.

Tests must assert that archive/rollover logic never invokes production mutation paths.

## 19. Configuration

New local configuration is expected along these lines:

```env
# PC3 identity/documentation only
RADMON_CENTRAL_HOST=192.168.1.2

# Three actual production DB endpoints, filled at deployment.
RADMON_LAN_SOURCES=source-a@IP-A;source-b@IP-B;source-c@IP-C

RADMON_ARCHIVE_ENABLED=1
RADMON_ARCHIVE_DIR=archives
RADMON_ARCHIVE_TIMEZONE=Asia/Jakarta
RADMON_ARCHIVE_MIN_RETENTION_YEARS=5
RADMON_ARCHIVE_CHECK_INTERVAL=60
```

No production host is inferred from PC1/PC2 addressing. The old `.50/.52/.38` example is removed/replaced with neutral deployment placeholders unless verified as actual production DB endpoints.

Archive output directories are ignored by Git.

## 20. Launcher/process behavior

PC3 service operation becomes:

```text
central_server.py
  -> secure API
  -> one LAN collector owner
  -> one WhatsApp dispatcher
  -> one quarter lifecycle manager
```

`RUN_LAN.bat` is adjusted to avoid launching a second collector. The desktop Admin can remain a local operator UI over central data/control, but collection ownership is central-service-only.

Detector and dummy launchers retain their existing standalone behavior and tests.

## 21. Compatibility

This design deliberately preserves:

- the legacy `ipradmon` table contract;
- `measurement` as realtime/history source of truth;
- stored `measurement.dose` values;
- Grafana realtime view against active central MariaDB;
- existing alarm transition/history presentation;
- existing ACK write-through semantics;
- existing authentication, PIN, and audit model;
- existing preview-first Reports and PDF/CSV export;
- LAN checkpoints across quarter boundaries;
- no production schema migration requirement.

## 22. Implementation boundaries

Expected new/changed units include:

- new quarter/calendar and archive lifecycle module;
- new central archive data/export repository;
- new archive reader/composite report repository;
- security sidecar archive index/state extensions;
- `LanRuntime` lifecycle integration and single-owner guard/process behavior;
- `main.py` LAN behavior to stop static-catalog seeding and duplicate collection;
- `central_server.py` lifecycle owner wiring;
- `RUN_LAN.bat` ownership alignment;
- Reports UI archive selector/recap;
- secure archive read/admin routes;
- `.env.example`, `.gitignore`, README;
- focused tests plus existing full CI/Grafana validation.

## 23. Test contract

Implementation is not complete until automated tests cover at minimum:

1. correct Q1/Q2/Q3/Q4 WIB boundaries, including year rollover;
2. production SERID discovery with no canonical seeding in LAN mode;
3. checkpoint persistence across quarter rollover;
4. production sources remain read-only except explicit ACK;
5. archive contains required CSV/SQL/recap/manifest entries;
6. SQL and CSV preserve stored measurement dose;
7. row-count and SHA-256 verification gates purge;
8. failed export/verify never purges central rows;
9. successful verified archive purges only old-quarter central operational rows;
10. `device`, security data, source mapping, and checkpoints survive rollover;
11. `recent` is rebuilt for active-quarter data;
12. monthly recap gives exact sample/min/avg/max/dose/alarm counts;
13. archived report ranges are readable directly from ZIP;
14. report ranges spanning multiple archived quarters and active MariaDB merge correctly;
15. archive corruption is surfaced;
16. automatic retry/idempotency after restart;
17. only one PC3 LAN collector owns ingestion;
18. archive API requires authentication and manual mutation requires Administrator + PIN;
19. existing report preview/PDF/CSV behavior stays green;
20. full existing CI and Grafana payload validation remain green.

## 24. Completion criteria

The feature is considered complete when:

- PC3 can ingest directly from three configured production DBs using production SERIDs;
- no production mutation occurs outside ACK;
- quarter rollover follows the calendar and cannot purge before verified export;
- CSV, SQL, monthly recap, manifest, and checksums are generated automatically;
- old quarter data is removed only from central active tables after safe sealing;
- at least five years of archives can remain available without burdening active MariaDB;
- Reports can directly preview/export historical archived data without SQL restore;
- month/quarter archive inventory is visible;
- lifecycle operations are auditable;
- one and only one central LAN collector owns source polling;
- tests, compile checks, Grafana validation, and GitHub CI succeed on `main`.
