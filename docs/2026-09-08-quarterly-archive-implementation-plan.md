# Quarterly Central Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved PC3 quarterly archive lifecycle so central MariaDB retains only the active calendar quarter while verified ZIP archives remain directly reportable for at least five years, without mutating production databases outside the existing guarded ACK path.

**Architecture:** Keep production sources behind the existing LAN read abstraction and make `central_server.py` the single ingestion/lifecycle owner. Add a focused archive module that exports/verifies/purges only central MariaDB data, persist lifecycle/index state in the existing SQLite security sidecar, and add a ZIP-backed archive repository plus composite report repository so Reports can span archived and active quarters without SQL restore.

**Tech Stack:** Python 3.12, MariaDB connector, SQLite, FastAPI, PySide6, standard-library `csv`/`zipfile`/`hashlib`/`zoneinfo`, pytest.

**Spec:** `docs/2026-09-08-quarterly-archive-design.md`

## Global Constraints

- PC3 central RadMon host is `192.168.1.2`.
- Three production database endpoints are deployment configuration; do not infer or commit legacy topology IPs.
- Production `device.serid` is authoritative in LAN-central mode.
- Production databases are read-only except existing guarded alarm ACK/Response keyed by remote `SERID + dtoa` with `i_op IS NULL`.
- Quarter boundaries are WIB calendar quarters and archive ranges are half-open `[start, end)`.
- Purge is forbidden before successful archive verification.
- Stored `measurement.dose` values must be preserved exactly by archive/export/report paths.
- No production schema migration is introduced.
- Archive output is outside Git and automatic destructive pruning is disabled by default.
- `central_server.py` is the only background LAN collector/lifecycle owner on PC3.
- Existing detector/dummy workflows, Grafana realtime behavior, auth/PIN/audit, and preview-first Reports must remain compatible.

---

## File Map

**New focused modules**

- `radmon/quarters.py` — WIB quarter identity/boundary helpers.
- `radmon/archive_store.py` — central MariaDB quarter reads, deterministic export rows, central purge/rebuild operations.
- `radmon/archive.py` — archive state machine, ZIP/manifest/checksum/monthly recap/SQL generation, verification, reconciliation.
- `radmon/archive_reports.py` — ZIP-backed report repository and active+archive composite repository.

**Existing modules to modify**

- `radmon/security.py` — archive index/state tables and CRUD helpers in the SQLite sidecar.
- `radmon/lan.py` — explicit read-only production source surface plus source identity conflict checks.
- `radmon/lan_runtime.py` — lifecycle check loop owned by the central service.
- `radmon/config.py` — archive settings and central-host documentation setting.
- `central_server.py` — construct/wire archive services and expose them to secure routes.
- `main.py` — LAN mode does not seed the static station catalog and does not run a local `LanRuntime` collector.
- `radmon/reports.py` — permit composite repository summaries without changing preview/PDF/CSV contracts.
- `radmon/admin/reports_page.py` — archive inventory/period selector and status text while preserving preview-first workflow.
- `radmon/secure_services.py` — expose archive catalog/lifecycle where needed.
- `radmon/secure_api.py` — authenticated archive inventory/recap endpoints and optional PIN-gated retry endpoint.
- `RUN_LAN.bat` — start/reuse central service, then open Admin without a second collector.
- `.env.example`, `.gitignore`, `README.md` — neutral source placeholders, archive settings, runtime ownership and lifecycle docs.

**Tests**

- `tests/test_quarters.py`
- `tests/test_archive.py`
- `tests/test_archive_reports.py`
- updates to `tests/test_lan.py`, `tests/test_secure_api.py`, `tests/test_bundle.py`, `tests/test_report_preview.py`.

---

### Task 1: WIB Quarter Model

**Files:**
- Create: `radmon/quarters.py`
- Create: `tests/test_quarters.py`

**Interfaces:**
- Produces: `Quarter` dataclass with `quarter_id`, `start`, `end`, `year`, `number`, `month_names`.
- Produces: `quarter_for(value: datetime, timezone_name: str = "Asia/Jakarta") -> Quarter`.
- Produces: `previous_quarter(value: datetime, timezone_name: str = "Asia/Jakarta") -> Quarter`.
- Produces: `quarters_overlapping(start: datetime, end: datetime, timezone_name: str = "Asia/Jakarta") -> list[Quarter]`.

- [ ] **Step 1: Write failing quarter-boundary tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from radmon.quarters import previous_quarter, quarter_for, quarters_overlapping

WIB = ZoneInfo("Asia/Jakarta")


def test_q3_2026_boundaries_are_calendar_wib():
    q = quarter_for(datetime(2026, 9, 8, 20, 0, tzinfo=WIB))
    assert q.quarter_id == "2026-Q3"
    assert q.start == datetime(2026, 7, 1, 0, 0, tzinfo=WIB)
    assert q.end == datetime(2026, 10, 1, 0, 0, tzinfo=WIB)
    assert q.month_names == ("July", "August", "September")


def test_q4_previous_rolls_across_year_boundary():
    q = previous_quarter(datetime(2027, 1, 1, 0, 1, tzinfo=WIB))
    assert q.quarter_id == "2026-Q4"
    assert q.start == datetime(2026, 10, 1, 0, 0, tzinfo=WIB)
    assert q.end == datetime(2027, 1, 1, 0, 0, tzinfo=WIB)


def test_overlapping_quarters_uses_half_open_ranges():
    values = quarters_overlapping(
        datetime(2026, 9, 30, 23, 59, tzinfo=WIB),
        datetime(2026, 10, 1, 0, 1, tzinfo=WIB),
    )
    assert [q.quarter_id for q in values] == ["2026-Q3", "2026-Q4"]
```

- [ ] **Step 2: Run focused test and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_quarters.py`
Expected: import/module failure because `radmon.quarters` does not exist.

- [ ] **Step 3: Implement the minimal quarter helpers**

```python
@dataclass(frozen=True, slots=True)
class Quarter:
    year: int
    number: int
    start: datetime
    end: datetime

    @property
    def quarter_id(self) -> str:
        return f"{self.year}-Q{self.number}"

    @property
    def month_names(self) -> tuple[str, str, str]:
        first = (self.number - 1) * 3 + 1
        return tuple(calendar.month_name[m] for m in range(first, first + 3))
```

Use `ZoneInfo(timezone_name)` and construct exact local midnights. For naive inputs, treat them as local deployment time rather than silently converting from UTC.

- [ ] **Step 4: Run quarter tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_quarters.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/quarters.py tests/test_quarters.py
git commit -m "feat: add WIB quarter calendar model"
```

---

### Task 2: Persist Archive Lifecycle State in the Security Sidecar

**Files:**
- Modify: `radmon/security.py`
- Create/extend: `tests/test_archive.py`

**Interfaces:**
- Produces SQLite table `archive_quarters` keyed by `quarter_id`.
- Produces `SecurityStore.get_archive(quarter_id) -> dict | None`.
- Produces `SecurityStore.list_archives(limit=100) -> list[dict]`.
- Produces `SecurityStore.upsert_archive(...) -> dict`.
- Produces `SecurityStore.update_archive_state(quarter_id, state, **fields) -> dict`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_archive_state_survives_store_reopen(tmp_path):
    path = tmp_path / "security.db"
    store = SecurityStore(path)
    store.upsert_archive(
        quarter_id="2026-Q3",
        start_at="2026-07-01T00:00:00+07:00",
        end_at="2026-10-01T00:00:00+07:00",
        state="OPEN",
    )
    store.update_archive_state("2026-Q3", "EXPORTING", last_error=None)
    reopened = SecurityStore(path)
    row = reopened.get_archive("2026-Q3")
    assert row["state"] == "EXPORTING"
    assert row["quarter_id"] == "2026-Q3"
```

- [ ] **Step 2: Run focused test and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_archive.py::test_archive_state_survives_store_reopen`
Expected: method/table missing failure.

- [ ] **Step 3: Add schema and state helpers**

Add `archive_quarters` with these durable fields:

```sql
CREATE TABLE IF NOT EXISTS archive_quarters (
  quarter_id TEXT PRIMARY KEY,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  state TEXT NOT NULL,
  archive_path TEXT,
  archive_sha256 TEXT,
  row_counts_json TEXT,
  drain_json TEXT,
  created_at TEXT,
  sealed_at TEXT,
  purged_at TEXT,
  completed_at TEXT,
  last_error TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
```

Store structured row counts/drain watermarks as JSON strings; return decoded dictionaries from helper methods.

- [ ] **Step 4: Run archive persistence tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_archive.py::test_archive_state_survives_store_reopen`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/security.py tests/test_archive.py
git commit -m "feat: persist quarterly archive lifecycle state"
```

---

### Task 3: Central Quarter Data Store and Production Safety Boundary

**Files:**
- Create: `radmon/archive_store.py`
- Modify: `radmon/lan.py`
- Modify: `tests/test_lan.py`
- Extend: `tests/test_archive.py`

**Interfaces:**
- Produces `CentralArchiveStore(settings, connection_factory=None)`.
- Produces `table_rows(table, quarter, *, chunk_size=5000) -> Iterator[dict]` for central tables only.
- Produces `row_counts(quarter) -> dict[str, int]`.
- Produces `monthly_recap_rows(quarter) -> list[dict]` using stored `measurement.dose`.
- Produces `purge_quarter(quarter) -> dict[str, int]` deleting only central time/event rows.
- Produces `rebuild_recent(active_quarter) -> None`.
- Production `RemoteMariaDBSource` retains read methods plus only the dedicated `ack_legacy` mutation method.

- [ ] **Step 1: Write failing tests for central-only purge and stored dose recap**

Use a fake cursor/connection that records SQL. Assert:

```python
assert "DELETE FROM measurement" in sql
assert "DELETE FROM alarm" in sql
assert "DELETE FROM rawdata" in sql
assert "DELETE FROM applog" in sql
assert "DELETE FROM news" in sql
assert "DELETE FROM device" not in sql
```

For recap input containing stored doses `0.0042` and `0.0007`, assert monthly `dose_sum == pytest.approx(0.0049)` and do not recompute from rate/time.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_archive.py tests/test_lan.py`
Expected: missing archive store behavior.

- [ ] **Step 3: Implement central quarter queries/purge/recent rebuild**

Time-bearing central tables and columns:

```python
TIME_TABLES = {
    "measurement": "dtom",
    "alarm": "dtom",
    "rawdata": "dtom",
    "applog": "dtom",
    "news": "dtom",
}
```

`device` is exported as a snapshot but never purged. Every quarter query uses `>= quarter.start` and `< quarter.end`.

`rebuild_recent()` clears central `recent` only, then reconstructs one latest aggregate row per retained/current detector using current-quarter `measurement` values. This method never receives or opens a production connection.

- [ ] **Step 4: Make production mutation boundary explicit in tests**

Add a source safety test that scans `RemoteMariaDBSource` SQL-bearing methods and asserts normal collection methods contain only `SELECT`; the single `UPDATE alarm` is confined to `ack_legacy`.

- [ ] **Step 5: Run focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_archive.py tests/test_lan.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/archive_store.py radmon/lan.py tests/test_archive.py tests/test_lan.py
git commit -m "feat: add central quarter data store and safety boundary"
```

---

### Task 4: Deterministic ZIP Export, SQL, Monthly Recap and Verification

**Files:**
- Create: `radmon/archive.py`
- Extend: `tests/test_archive.py`

**Interfaces:**
- Produces `ArchiveCatalog(security_store, archive_dir)` with `list_archives()`, `get(quarter_id)`, `reconcile()`.
- Produces `QuarterArchiveService(store, catalog, audit, archive_dir, timezone_name="Asia/Jakarta")`.
- Produces `export_quarter(quarter, drain_info) -> Path`.
- Produces `verify_archive(path, expected_quarter=None) -> dict`.
- Produces `run_rollover(quarter, drain_info) -> dict` with export/verify/purge gates.

- [ ] **Step 1: Write failing ZIP-content tests**

Use an in-memory/fake `CentralArchiveStore` with deterministic rows and assert the ZIP contains exactly the required payload set:

```python
required = {
    "manifest.json",
    "monthly-recap.csv",
    "device.csv",
    "measurement.csv",
    "alarm.csv",
    "rawdata.csv",
    "applog.csv",
    "news.csv",
    "radmon-2026-Q3.sql",
}
assert required <= set(zip_file.namelist())
```

Assert `measurement.csv` and SQL both contain the stored dose `0.0042`.

- [ ] **Step 2: Write failing verification-gates-purge tests**

```python
def test_verify_failure_never_purges(tmp_path):
    store = FakeArchiveStore()
    service = make_service(store, tmp_path)
    service._verify = lambda path, expected_quarter=None: (_ for _ in ()).throw(RuntimeError("checksum mismatch"))
    with pytest.raises(RuntimeError):
        service.run_rollover(Q3, drain_info={})
    assert store.purge_calls == []


def test_verified_archive_purges_once_and_rebuilds_recent(tmp_path):
    store = FakeArchiveStore()
    service = make_service(store, tmp_path)
    result = service.run_rollover(Q3, drain_info={"gd52:5201": "2026-09-30T23:59:58+07:00"})
    assert result["state"] == "COMPLETE"
    assert store.purge_calls == ["2026-Q3"]
    assert store.rebuild_calls == 1
```

- [ ] **Step 3: Implement deterministic payload generation**

Write each CSV into a temporary working directory with stable column order and `newline=""`, UTF-8 encoding. Generate SQL with explicit columns, `START TRANSACTION;`, escaped literals, and `COMMIT;`. Generate monthly recap from central store aggregates.

Manifest schema:

```json
{
  "format_version": 1,
  "quarter_id": "2026-Q3",
  "start": "2026-07-01T00:00:00+07:00",
  "end": "2026-10-01T00:00:00+07:00",
  "created_at": "...",
  "state": "SEALED",
  "row_counts": {},
  "files": {"measurement.csv": {"sha256": "...", "bytes": 123}},
  "drain": {},
  "stations": []
}
```

Manifest checksum covers payload files other than `manifest.json`; final ZIP checksum is stored in sidecar state.

- [ ] **Step 4: Implement free-space and idempotency checks**

Use `shutil.disk_usage(archive_dir).free`. Estimate required working space from exported central row data or conservative table byte estimates and refuse export before purge if free space is insufficient.

If a valid final archive for the quarter already exists, verify and reuse it instead of generating a conflicting package.

- [ ] **Step 5: Implement lifecycle state transitions and audit calls**

Persist `EXPORTING -> VERIFYING -> SEALED -> PURGING -> COMPLETE`. On failure, persist `last_error`, increment retry count, keep the last safe state, and record the matching `ARCHIVE_*` audit action with `identity=None`.

- [ ] **Step 6: Run archive tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_archive.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon/archive.py tests/test_archive.py
git commit -m "feat: export and verify quarterly archive packages"
```

---

### Task 5: Drain Completeness and Lifecycle Runtime

**Files:**
- Modify: `radmon/lan.py`
- Modify: `radmon/lan_runtime.py`
- Extend: `tests/test_lan.py`
- Extend: `tests/test_archive.py`

**Interfaces:**
- Produces `RemoteMariaDBSource.latest_measurement_at_or_before(serid, cutoff) -> datetime | None` read-only helper.
- Produces `LanAggregator.drain_source_until(source, cutoff) -> dict[int, datetime | None]`.
- `LanRuntime(..., archive_service=None, archive_check_interval=60)` owns one lifecycle thread/check inside the central process.

- [ ] **Step 1: Write failing drain test**

Given source rows ending before the Q3 cutoff, run `drain_source_until()` and assert checkpoint reaches the latest remote measurement at/before cutoff. If remote read throws `offline`, assert rollover remains `PENDING_DRAIN` and no purge occurs.

- [ ] **Step 2: Implement read-only drain watermark helper**

`latest_measurement_at_or_before` executes only:

```sql
SELECT MAX(dtom) FROM measurement WHERE serid = ? AND dtom < ?
```

Drain uses the existing persistent checkpoint and incremental `measurements_after` reads until checkpoint is at or beyond the source watermark for the old-quarter interval.

- [ ] **Step 3: Wire archive lifecycle checks into `LanRuntime`**

At most every `RADMON_ARCHIVE_CHECK_INTERVAL` seconds, determine the current quarter. For any prior non-complete quarter in the catalog, attempt drain then call the idempotent archive service. Collector threads continue importing current data while a prior quarter is pending.

- [ ] **Step 4: Run LAN/archive tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_lan.py tests/test_archive.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/lan.py radmon/lan_runtime.py tests/test_lan.py tests/test_archive.py
git commit -m "feat: drain and roll quarters from central LAN runtime"
```

---

### Task 6: Production SERID Authority and Single Collector Ownership

**Files:**
- Modify: `main.py`
- Modify: `central_server.py`
- Modify: `RUN_LAN.bat`
- Modify: `radmon/lan.py`
- Extend: `tests/test_lan.py`
- Modify: `tests/test_bundle.py`

**Interfaces:**
- LAN desktop mode opens central/Admin UI only; it does not construct/start `LanRuntime`.
- `central_server.py` constructs and starts the only `LanRuntime` when `RADMON_LAN_ENABLED=1`.
- LAN startup does not call `repository.ensure_station_catalog()`.

- [ ] **Step 1: Write failing source-of-truth/ownership tests**

Add source-structure tests asserting:

```python
main_source = Path("main.py").read_text()
assert 'if args.source != "lan":' in main_source
assert "LanRuntime(settings, secure" not in main_source
assert "ensure_station_catalog" is not executed for LAN mode

server_source = Path("central_server.py").read_text()
assert "LanRuntime(settings, services" in server_source
```

Also add an identity conflict test: two sources presenting the same SERID with conflicting name/location must raise/surface a conflict instead of silently overwriting/merging central metadata.

- [ ] **Step 2: Refactor `main.py` startup**

For `args.source == "lan"`, skip static catalog seeding and do not create a collector runtime. Keep repository/schema validation, security/login, and Admin presentation. For detector/dummy modes retain current `ApplicationRuntime` behavior.

- [ ] **Step 3: Align `RUN_LAN.bat`**

The launcher starts `central_server.py` in a background console/service process only when port 8090 is not already serving the RadMon health endpoint, then launches the desktop Admin in LAN-view mode. It must not start `main.py --source lan` as a collector owner.

- [ ] **Step 4: Run ownership tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_lan.py tests/test_bundle.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py central_server.py RUN_LAN.bat radmon/lan.py tests/test_lan.py tests/test_bundle.py
git commit -m "fix: make central server the sole LAN collector owner"
```

---

### Task 7: ZIP-Backed Archive Reports and Composite Repository

**Files:**
- Create: `radmon/archive_reports.py`
- Modify: `radmon/reports.py`
- Create: `tests/test_archive_reports.py`
- Modify: `tests/test_report_preview.py`

**Interfaces:**
- Produces `ArchiveReportRepository(catalog)` implementing `station_config`, `measurement_history`, `alarm_history`, `measurement_summary` for archived quarters.
- Produces `CompositeReportRepository(active_repository, archive_repository, timezone_name="Asia/Jakarta")` implementing the same logical report interface.
- Produces `ArchiveCorruptionError` for invalid/missing ZIPs.

- [ ] **Step 1: Write failing direct ZIP report test**

Create a tiny valid archive fixture with two Q3 measurements and one alarm. Assert:

```python
rows = repo.measurement_history(start, end, serid=5201, limit=250)
assert [row["dose"] for row in rows] == [0.0042, 0.0007]
assert repo.measurement_summary(start, end, serid=5201)["sample_count"] == 2
```

- [ ] **Step 2: Write failing spanning-range composite test**

Have archived Q3 rows plus an active Q4 fake repository. Query across 30 Sep/1 Oct and assert merged rows are sorted, deduplicated by `(serid, dtom)`, and the `limit=250` contract is honored.

- [ ] **Step 3: Implement streamed CSV readers**

Open ZIP members with `zipfile.ZipFile.open`, wrap with `io.TextIOWrapper`, stream `csv.DictReader`, parse datetimes/numbers, filter by half-open range and SERID, and stop once limit is reached. Validate the archive manifest/checksums before returning historical data.

- [ ] **Step 4: Implement summary composition**

Use archive monthly/manifest accumulators when a requested interval covers complete archived months/quarters; otherwise stream matching CSV rows. Combine summary components using exact `sum_rate`/`sample_count` accumulators so averages remain mathematically correct across partitions.

- [ ] **Step 5: Run report tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_archive_reports.py tests/test_report_preview.py tests/test_reports.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/archive_reports.py radmon/reports.py tests/test_archive_reports.py tests/test_report_preview.py
git commit -m "feat: read archived quarters directly in reports"
```

---

### Task 8: Reports UI Archive Inventory

**Files:**
- Modify: `radmon/admin/reports_page.py`
- Modify: `radmon/admin/main_window.py` only if constructor wiring is required.
- Extend: `tests/test_report_preview.py`

**Interfaces:**
- `ReportsPage(..., archive_catalog=None)` accepts optional archive inventory.
- UI adds a read-only archive selector/status surface but keeps existing From/To, Preview, Print, Export PDF and Export CSV controls.

- [ ] **Step 1: Write failing UI structure test**

Assert source contains a `QComboBox` archive selector and labels `Active`, `Complete`, `Archive`, while preserving existing preview-first elements and disabled print/PDF until preview.

- [ ] **Step 2: Implement inventory selector**

Populate choices from `archive_catalog.list_archives()` with labels such as:

```text
Active
2026 Q3 · July, August, September · Complete
2026 Q2 · April, May, June · Complete
```

Selecting an archived quarter sets From/To to its exact quarter range but does not auto-preview.

- [ ] **Step 3: Surface corruption/status errors**

If catalog marks an archive invalid/damaged, show that status and let `build_preview()` surface the repository error instead of silently falling back to active DB.

- [ ] **Step 4: Run UI/report tests**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_report_preview.py tests/test_admin_ui_v3.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/admin/reports_page.py radmon/admin/main_window.py tests/test_report_preview.py
git commit -m "feat: expose quarterly archives in Reports"
```

---

### Task 9: Secure Archive API

**Files:**
- Modify: `radmon/secure_services.py`
- Modify: `radmon/secure_api.py`
- Modify: `central_server.py`
- Extend: `tests/test_secure_api.py`

**Interfaces:**
- `GET /api/v1/control/archives` — authenticated archive inventory.
- `GET /api/v1/control/archives/{quarter_id}/recap` — authenticated recap.
- `POST /api/v1/control/archives/{quarter_id}/retry` — Administrator + PIN only, invoking the same idempotent lifecycle service.

- [ ] **Step 1: Write failing auth/role tests**

Assert anonymous archive inventory returns 401, Viewer can read inventory/recap, Operator cannot call retry, and Administrator with valid PIN can call retry.

- [ ] **Step 2: Extend route attachment signature**

Add optional `archive_catalog=None` and `archive_service=None`. Do not expose credentials, raw sidecar security rows, or filesystem contents beyond normalized archive metadata.

- [ ] **Step 3: Implement routes and audit manual retry**

Manual retry verifies `manage_sources` or a dedicated Administrator-only permission plus PIN, records `ARCHIVE_MANUAL_RETRY`, then calls the idempotent service.

- [ ] **Step 4: Run secure API tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_secure_api.py tests/test_security.py tests/test_audit.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/secure_services.py radmon/secure_api.py central_server.py tests/test_secure_api.py
git commit -m "feat: add authenticated archive control API"
```

---

### Task 10: Configuration, Archive Reconciliation and Documentation

**Files:**
- Modify: `radmon/config.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `tests/test_bundle.py`

**Interfaces:**
- New `Settings` fields: `central_host`, `archive_enabled`, `archive_dir`, `archive_timezone`, `archive_min_retention_years`, `archive_check_interval`.
- Defaults: `192.168.1.2`, enabled, `archives`, `Asia/Jakarta`, `5`, `60` respectively unless deployment explicitly overrides.

- [ ] **Step 1: Write failing config/docs tests**

Assert `.env.example` contains neutral source placeholders:

```text
RADMON_LAN_SOURCES=source-a@IP-A;source-b@IP-B;source-c@IP-C
```

and no old `.50/.52/.38` committed source example. Assert archive directory is ignored and README documents verified-before-purge, five-year direct reporting, and single collector ownership.

- [ ] **Step 2: Implement settings/env parsing**

Use existing `_as_bool`; normalize archive path to `Path`; reject `archive_min_retention_years < 5`; accept only a valid `ZoneInfo` timezone at startup.

- [ ] **Step 3: Reconcile archive catalog on central-server startup**

Before starting lifecycle checks, scan `archive_dir/*/radmon-*-Q*.zip`, validate manifests/checksums, and upsert valid catalog entries. Mark indexed-but-missing/corrupt archives damaged without deleting central/other files.

- [ ] **Step 4: Update README and `.gitignore`**

Document lifecycle states, files in a package, production read-only boundary, direct archived Reports, PC3 `192.168.1.2`, neutral production endpoints, and no automatic destructive archive prune.

- [ ] **Step 5: Run config/bundle tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_bundle.py tests/test_domain.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/config.py .env.example .gitignore README.md tests/test_bundle.py
git commit -m "docs: configure and document quarterly archives"
```

---

### Task 11: Full Regression, Compile and Grafana Validation

**Files:**
- Modify only files required by failures uncovered in this task.

**Interfaces:**
- No new public interfaces. This task proves compatibility with the existing repository contracts.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Compile Python**

Run:

```bash
python -m compileall -q main.py central_server.py radmon
```

Expected: exit status 0.

- [ ] **Step 3: Run the same Grafana payload validation used by CI**

Run the Python/yaml validation block from `.github/workflows/ci.yml` and require:

```text
Grafana TV payloads valid
```

- [ ] **Step 4: Check tracked artifacts**

Run:

```bash
git ls-files '*.pyc' 'archives/*' 'runtime/*'
```

Expected: no generated bytecode/archive/runtime artifacts tracked.

- [ ] **Step 5: Review diff against approved spec**

Confirm every spec item has a concrete implementation/test: WIB boundaries; production SERID; read-only production except ACK; CSV/SQL/recap/manifest/checksum; verification-gated purge; durable metadata/checkpoints; direct ZIP Reports; corruption handling; five-year availability; one collector; secure archive API; audit; neutral endpoint config.

- [ ] **Step 6: Commit any final fixes**

```bash
git add -A
git commit -m "test: verify quarterly archive lifecycle"
```

- [ ] **Step 7: Push directly to main and verify GitHub CI**

```bash
git push origin main
```

Fetch the workflow run/status for the resulting main SHA. Completion requires green CI; if CI fails, inspect job logs, fix, rerun local targeted/full verification, push the correction, and re-check until green.
