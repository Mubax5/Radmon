# Rolling Recent/VRecent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace central `recent`/`vrecent` with a safe three-hour rolling monitoring read model so Grafana and live overview never scan five-year `measurement` history while authoritative historical data remains unchanged.

**Architecture:** Add a focused `RollingRecentManager` that owns only central `recent`/`vrecent` migration, reconciliation, cleanup, and view creation. Historical writes continue to `measurement` first; rolling writes mirror the same real samples into `recent`. Current-state consumers explicitly select the newest rolling row per SERID, while Grafana time-series reads directly from bounded `vrecent`.

**Tech Stack:** Python 3.12, MariaDB, FastAPI, Grafana SQL payload generation, pytest, React/Vite CI, Windows PyInstaller/Inno Setup packaging.

**Spec:** `docs/ROLLING-RECENT-VRECENT-DESIGN.md`

## Global Constraints

- Never delete, truncate, drop, or shorten retention for `measurement`, `alarm`, or `rawdata`.
- Never modify LAN/source database schemas on `.38`, `.50`, `.52`, or other detector sources.
- Only central `recent`, `vrecent`, and temporary/legacy names used to migrate `recent` may be destructively changed.
- Default rolling retention is exactly three hours; cleanup cadence is approximately once per minute, not once per sample.
- Grafana layout/panel placement/playlist structure must remain unchanged.
- Continuous dose/time-series Grafana SQL must not query `measurement`; the 24-hour alarm event panel may continue to query `alarm`.
- No dummy detector values, timestamps, statuses, or online states.
- Historical `measurement`, `alarm`, `rawdata`, reports, and archives remain authoritative for five-year reporting.

---

### Task 1: Lock the rolling-schema safety contract with RED tests

**Files:**
- Create: `tests/test_rolling_recent_read_model.py`
- Modify: `tests/test_grafana_tv.py`
- Modify: `tests/test_grafana_monitoring.py`
- Modify: `tests/test_hot_path_performance.py`

**Interfaces:**
- Consumes: existing `Settings`, Grafana payload builders, central repository classes.
- Produces: regression contract for `RollingRecentManager`, rolling writes, latest-row reads, Grafana SQL, and historical-table safety.

- [ ] **Step 1: Write failing migration/cleanup tests**

Add tests that import `RollingRecentManager` and assert its recorded SQL:

```python
manager.ensure_schema()
manager.cleanup()
sql = "\n".join(recorded_sql).lower()
assert "recent_radmon_next" in sql
assert "date_sub" in sql and "interval 3 hour" in sql
assert "delete from recent" in sql
for protected in ("measurement", "alarm", "rawdata"):
    assert f"delete from {protected}" not in sql
    assert f"truncate table {protected}" not in sql
    assert f"drop table {protected}" not in sql
```

Use a fake MariaDB connection that returns legacy `recent` columns from `INFORMATION_SCHEMA`, accepts DDL, and returns bounded measurement rows. Assert migration backfill SQL contains `FROM measurement` with a three-hour cutoff but never destructive DML against historical tables.

- [ ] **Step 2: Write failing write-path tests**

Assert central live and batch ingestion mirror each inserted real sample with:

```sql
INSERT IGNORE INTO recent (serid, dtom, doserate, dose, previnterval, stat)
```

and no longer writes legacy aggregate fields (`minrate`, `maxrate`, `avgrate`, `meacount`, `lastmea`).

- [ ] **Step 3: Write failing latest-read tests**

Update the central hot-path test so `overview_rows()` must select one newest rolling row per detector from `vrecent`/`recent`, never direct `measurement`, while remote source tests continue expecting the legacy source `vrecent` contract unchanged.

- [ ] **Step 4: Write failing Grafana tests**

Change page-one sparkline and page-two trend assertions from `FROM measurement` to `FROM vrecent`, and add a payload-wide assertion:

```python
for dashboard in build_dashboard_payloads():
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            sql = target.get("rawSql", "")
            if panel.get("title") != "Alarm Terbaru · 24 Jam":
                assert "FROM measurement" not in sql
```

Keep the existing alarm-panel assertion that reads `alarm`.

- [ ] **Step 5: Push RED tests and verify CI fails for the intended missing behavior**

Expected failures: missing `RollingRecentManager`, legacy recent write SQL, current Grafana `measurement` trend queries, and current one-row `recent` overview assumptions. Existing unrelated tests should remain green.

---

### Task 2: Implement central rolling read-model migration and lifecycle

**Files:**
- Create: `radmon/recent_read_model.py`
- Modify: `radmon/repository.py`
- Modify: `radmon/central_service.py`
- Test: `tests/test_rolling_recent_read_model.py`

**Interfaces:**
- Produces: `RollingRecentManager(settings, connection_factory=None, retention_hours=3, cleanup_interval_seconds=60)`.
- Produces methods: `ensure_schema() -> None`, `cleanup(force: bool = False) -> int`, `rebuild() -> None`, `mirror_sample(cursor, *, serid, dtom, doserate, dose, previnterval, stat) -> None`.
- `central_service.build_central_runtime()` calls migration only on the central DB after `radmon_runtime_status` exists.

- [ ] **Step 1: Implement constants and schema detection**

Use exact rolling columns:

```python
ROLLING_COLUMNS = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
RETENTION_HOURS = 3
```

Inspect `INFORMATION_SCHEMA.COLUMNS` and `INFORMATION_SCHEMA.STATISTICS` for central `recent`; do not inspect or alter remote source databases.

- [ ] **Step 2: Implement restart-safe migration**

When legacy shape is detected:

```sql
DROP TABLE IF EXISTS recent_radmon_next;
CREATE TABLE recent_radmon_next LIKE measurement;
DELETE FROM recent_radmon_next;
ALTER TABLE recent_radmon_next ADD INDEX idx_recent_dtom (dtom);
INSERT IGNORE INTO recent_radmon_next (serid, dtom, doserate, dose, previnterval, stat)
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE dtom >= DATE_SUB(CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00'), INTERVAL 3 HOUR);
DROP VIEW IF EXISTS vrecent;
DROP TABLE IF EXISTS recent_radmon_legacy;
RENAME TABLE recent TO recent_radmon_legacy, recent_radmon_next TO recent;
```

If `measurement` already carries the desired composite primary key, `CREATE TABLE ... LIKE measurement` preserves it. Otherwise add `PRIMARY KEY (serid, dtom)` only after checking `SHOW INDEX`/`INFORMATION_SCHEMA.STATISTICS` so duplicate-index errors are impossible.

- [ ] **Step 3: Create the new `vrecent` view**

Create a central-only view joining `recent` to `device` and `radmon_runtime_status`. Expose the exact fields in the spec and derive `underlying_status`/`status` from real sample time, thresholds, suppression, and runtime state. `status` must mark a sample offline when `dtom` exceeds `maxidlemin`; no dummy values.

- [ ] **Step 4: Validate then remove legacy rolling table**

After swap, compare bounded sample counts/latest timestamps between `recent` and the three-hour slice of `measurement`. Only after successful validation execute:

```sql
DROP TABLE IF EXISTS recent_radmon_legacy;
```

Failure before/after swap must raise visibly and must never target protected historical relations destructively.

- [ ] **Step 5: Split schema validation into base and full checks**

Update `repository.py` so base historical schema can be validated before rolling migration, while the final `REQUIRED_SCHEMA` expects the new six-column `recent` and new `vrecent` fields. Keep all historical relation requirements unchanged.

- [ ] **Step 6: Wire startup order**

In `build_central_runtime()`:

1. validate protected/base schema;
2. build services and `ensure_schema()` for `radmon_runtime_status`;
3. run `RollingRecentManager.ensure_schema()`;
4. run full `MariaDBRepository.require_schema()`;
5. continue policy restore/archive/runtime startup.

- [ ] **Step 7: Run focused tests**

Expected: rolling migration/safety tests green; no test permits historical destructive SQL.

---

### Task 3: Mirror real samples into rolling `recent` without changing historical retention

**Files:**
- Modify: `radmon/repository.py`
- Modify: `radmon/central_api.py`
- Modify: `radmon/lan_store.py`
- Modify: `radmon/lan_runtime.py`
- Test: `tests/test_rolling_recent_read_model.py`
- Test: existing ingestion/LAN tests

**Interfaces:**
- Consumes: `RollingRecentManager.mirror_sample(...)`, `cleanup(force=False)`.
- Historical writes to `measurement` remain authoritative and unchanged.

- [ ] **Step 1: Replace legacy `upsert_recent` aggregate logic**

Make `upsert_recent` (or a renamed compatibility helper) perform only an idempotent rolling insert:

```sql
INSERT IGNORE INTO recent
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, ?)
```

Remove aggregate-update SQL from central paths.

- [ ] **Step 2: Preserve write ordering**

For direct repository and batch ingest, write `measurement` first. Mirror only real successfully accepted samples into `recent`. Do not make a rolling mirror failure delete or replace an already stored historical measurement.

- [ ] **Step 3: Update LAN batched live writes**

`BatchedMariaCentralStore.upsert_live_rows()` must continue `INSERT IGNORE INTO measurement`, and mirror the same sample into rolling `recent` with real `dtom`, `doserate`, `dose`, derived `previnterval`, and `stat=0`.

- [ ] **Step 4: Add low-frequency cleanup**

Use one central `RollingRecentManager`/guard so cleanup executes no more often than about once per minute even though live loops run every two seconds. Cleanup SQL deletes only expired `recent` rows.

- [ ] **Step 5: Add bounded reconciliation**

When startup or an explicit rebuild is needed, repopulate only the latest three hours from central `measurement`. Never scan/copy the full five-year history into `recent`.

- [ ] **Step 6: Run focused ingestion/LAN tests**

Expected: authoritative history tests remain unchanged, rolling insert tests green, remote source schema remains untouched.

---

### Task 4: Make live/current consumers explicitly select latest rolling rows

**Files:**
- Modify: `radmon/hot_path.py`
- Modify: `radmon/repository.py`
- Modify: `radmon/central_api.py`
- Test: `tests/test_hot_path_performance.py`
- Test: relevant web/API tests

**Interfaces:**
- Central `vrecent` contains multiple samples per SERID.
- Current-state queries must return exactly one newest row per configured device.

- [ ] **Step 1: Update overview SQL**

Use a bounded latest-row derived relation such as:

```sql
LEFT JOIN (
  SELECT v.*
  FROM vrecent v
  JOIN (
    SELECT serid, MAX(dtom) AS dtom
    FROM vrecent
    GROUP BY serid
  ) newest ON newest.serid = v.serid AND newest.dtom = v.dtom
) v ON v.serid = d.serid
```

This scans only the rolling three-hour relation, never `measurement`.

- [ ] **Step 2: Update single-station latest reads**

For central `vrecent` consumers use `ORDER BY dtom DESC LIMIT 1`. Historical `/history` endpoints continue reading `measurement` because they are explicitly historical and not monitoring hot paths.

- [ ] **Step 3: Preserve remote-source logic**

Do not change `RealtimeRemoteMariaDBSource` legacy field selection. Its targeted `measurement ORDER BY dtom DESC LIMIT 1` fallback remains read-only against remote source DBs.

- [ ] **Step 4: Run hot-path/API tests**

Expected: current monitoring reads only bounded central `vrecent`; explicit history reads still use historical tables.

---

### Task 5: Move Grafana dose monitoring entirely to `vrecent`

**Files:**
- Modify: `radmon/grafana_tv.py`
- Modify: `tests/test_grafana_tv.py`
- Modify: `tests/test_grafana_monitoring.py`
- Modify: `tests/test_grafana_revision.py` if its old-column assertions require updating

**Interfaces:**
- `vrecent` supplies rolling time series plus metadata/status.
- `alarm` remains the source for the 24-hour alarm event table.

- [ ] **Step 1: Update realtime sparkline SQL**

Replace `measurement m` with `vrecent v`, use `v.dtom`/`v.doserate`, preserve epoch conversion and Grafana `$__unixEpochFrom()` / `$__unixEpochTo()` bounds.

- [ ] **Step 2: Update three-hour building trend SQL**

Query `vrecent v` directly and use its `name` metadata instead of joining `device` again. Preserve panel titles, dimensions, units, styling, time window, and playlist behavior.

- [ ] **Step 3: Make current summaries/latest relations select newest per SERID**

Because `vrecent` now contains multiple samples per detector, `_latest_relation()` and `_status_relation()` must reduce to the newest `dtom` per SERID before calculating current max/average/online/offline counts.

- [ ] **Step 4: Keep alarm query unchanged**

`Alarm Terbaru · 24 Jam` stays on `alarm` and keeps its existing fields/time semantics.

- [ ] **Step 5: Run Grafana tests/payload validation**

Expected: no continuous dose/time-series target contains `FROM measurement`; dashboard geometry is byte-for-byte/semantically unchanged apart from SQL field mapping.

---

### Task 6: Make archive maintenance rebuild only the rolling window

**Files:**
- Modify: `radmon/archive_store.py`
- Modify: `radmon/archive.py` only if call signature needs to change
- Modify: `tests/test_archive.py`

**Interfaces:**
- `CentralArchiveStore.rebuild_recent(...)` becomes a bounded rolling rebuild; it does not compute quarter aggregates.

- [ ] **Step 1: Replace quarter aggregate rebuild SQL**

After verified archive purge, rebuild `recent` using only:

```sql
DELETE FROM recent;
INSERT IGNORE INTO recent (serid, dtom, doserate, dose, previnterval, stat)
SELECT serid, dtom, doserate, dose, previnterval, stat
FROM measurement
WHERE dtom >= DATE_SUB(CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00'), INTERVAL 3 HOUR);
```

Then recreate/validate `vrecent` through the rolling manager or shared helper.

- [ ] **Step 2: Update archive tests**

Assert the rebuild no longer queries a full active quarter, never inserts aggregate legacy columns, and does not alter archive/report retention behavior.

- [ ] **Step 3: Run archive tests**

Expected: archive export/verify/purge semantics remain green; only post-purge monitoring rebuild behavior changes.

---

### Task 7: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if optional rolling retention/cleanup settings are exposed; otherwise keep fixed defaults in code and do not add configuration.

**Interfaces:**
- Documentation describes `measurement` as five-year historical source and `recent`/`vrecent` as three-hour monitoring read model.

- [ ] **Step 1: Update README database section**

Replace “`recent` is one-row snapshot” with rolling three-hour semantics, state that Grafana dose/time-series reads only `vrecent`, and state that source DB schemas are never migrated.

- [ ] **Step 2: Run full Linux CI-equivalent suite**

Required checks:

```text
web: npm run check
web: npm run build
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
python -m compileall -q radmon packaging
Grafana TV payload validation
```

Expected: all tests pass with no skipped safety regression caused by this change.

- [ ] **Step 3: Verify Windows workflow exact head**

Require successful: EXE build, updater self-test, packaged EXE smoke test, installer build, installed smoke test, upgrade-over-running-RadMon smoke test.

- [ ] **Step 4: Integrate and publish**

After branch verification, fast-forward to `main` per the established project rule, then wait until Windows `main` workflow publishes Release `latest`. Verify `refs/tags/latest` equals exact `main` SHA and installer asset was created by that run.
