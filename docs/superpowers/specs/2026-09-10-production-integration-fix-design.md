# RadMon Production Integration Fix Design

Date: 2026-09-10
Status: Approved by user
Target integration branch: `main`

## Goal

Make the PC3 central system at `192.168.1.2` behave as an integrated production RadMon system rather than a partially connected UI. The production `ipradmon` databases at `.50`, `.52`, and `.38` remain authoritative for detector identity, live values, station configuration, and alarm state. Central PC3 remains the monitoring, history aggregation, alarm-response, health, Grafana, and Admin host.

## Approved behavior

1. Station hierarchy is grouped into exactly three collapsible server parents derived from configured LAN sources. Detector rows are children of their authoritative source mapping.
2. Station Properties in LAN mode are write-through: update the authoritative source `device` row first, then central `device`. If source write fails, central must not claim success.
3. Sensitive operations use a 10-minute in-memory PIN elevation lease per authenticated user. A valid PIN grants the lease; during the lease subsequent permitted sensitive operations do not prompt again. Logout/restart clears the lease.
4. Live monitoring remains based on source `vrecent` every 2 seconds. Each successful live poll also inserts the latest source sample into central `measurement` with `INSERT IGNORE`, so current charts have data immediately while historical backfill proceeds independently.
5. Historical backfill remains incremental, checkpointed, and separate from the live worker.
6. Alarm handling follows production `i_flag` semantics. Active alarm means `i_flag=0`. One-step response fills Action/PIC/Note and on submit/Enter writes source `i_op=now`, `pic`, `note`, `i_flag=1`; `ack` is preserved. Central mirror is updated after source success. Action is retained in central audit/mirror and embedded in the source note because production has no separate `action` column.
7. Active alarm state is refreshed every live cycle, not only via new-alarm checkpoint, so flag changes performed elsewhere are reflected centrally.
8. Detector ONLINE/OFFLINE status is recalculated from the newest `vrecent.dtom` every refresh; recovery from stale/offline to current data must immediately return to the correct NORMAL/ALERT/ALARM state. Server health and detector health remain separate concepts.
9. Grafana current values/status/thresholds/names/locations read the central database at query time. Historical sparkline/trend panels read `measurement`. Dashboard generation must not freeze edited station thresholds into generated JSON where a DB query can supply them.
10. F5/Refresh reloads station hierarchy, source health, selected-station detail, current tab, alarm/message state, and monitoring data. Auto-refresh remains lightweight.
11. Installation and User manuals are real HTML files and Desktop Help opens them in the system browser. Controls without working implementations must be disabled or omitted instead of presented as functional.

## Station tree

The desktop tree is logically:

```text
Station
├─ Server Gd.50 · 192.168.1.50 [STATE]
│  ├─ [3000] R. Resin Penukar Ion
│  ├─ [3001] R. Evaporasi
│  ├─ [3002] R. Kompaksi
│  ├─ [3003] R. Sementasi
│  └─ [3004] R. Insenerasi
├─ Server Gd.38 · 192.168.1.38 [STATE]
│  ├─ [3801] Kolam
│  ├─ [3802] Purifikasi
│  ├─ [3803] Pintu Kanal
│  ├─ [3804] Kanal Masuk
│  └─ [3805] Kanal Utama
└─ Server Gd.52 · 192.168.1.52 [STATE]
   ├─ [5201] IS-1
   ├─ [5202] IS-1 Koridor
   ├─ [5501] PSLAT
   ├─ [5701] IS-2
   └─ [5702] IS-2 LBN
```

The actual child membership is taken from `source_station_map`; the labels above reflect the observed production deployment and are not implemented as fragile SERID-range rules.

## Station configuration write-through

LAN station edit flow:

```text
Admin Save
 -> role/PIN lease check
 -> resolve central SERID -> source_id + remote_serid
 -> UPDATE source.device permitted logical fields
 -> read source row back
 -> UPDATE central.device from source-confirmed values
 -> audit success
 -> refresh station UI/Grafana DB reads
```

Editable logical fields in LAN mode: `name`, `location`, `description`, `warnlevel`, `alarmlevel`, `maxidlemin`, `unit`, `audiopath`. `serid`, `hwaddress`, and `hwtype` remain source/integration identity fields and are read-only in LAN mode.

## PIN lease

A valid PIN grants a 600-second in-memory lease on the active `SecurityStore` instance. `require_sensitive()` still checks role on every call. If a lease is active, an empty PIN is accepted for permitted actions. A non-empty PIN can create/renew a lease. Invalid PIN never creates a lease. User disable, logout, and explicit session revocation clear the lease for that user.

## Live sample and history

Every successful `vrecent` poll performs, for each detector:

- upsert full source snapshot into central `recent`;
- `INSERT IGNORE` the current `(serid, dtom, doserate, dose, previnterval/stat when available)` sample into central `measurement`;
- do not mutate aggregate `recent` from historical backfill.

This gives charts current points immediately. Backfill remains dedicated to older `measurement` rows and must never replace a newer `recent` snapshot.

## Alarm flow

For source rows with `i_flag=0`, central mirror marks them active. For rows with `i_flag=1`, central mirror marks them inactive/handled. New rows continue to be checkpointed for efficient history ingestion, while a lightweight active-state query runs every live cycle so existing alarm flags remain synchronized.

One-step response:

```sql
UPDATE alarm
SET i_op = ?, pic = ?, note = ?, i_flag = 1
WHERE serid = ? AND dtoa = ? AND i_flag = 0;
```

`ack` is intentionally not modified. Central mirror is changed only after the source update succeeds.

## Grafana

- Realtime/current stats and operational status query `vrecent`.
- Threshold evaluation uses `warnlevel`/`alarmlevel` from `vrecent`/`device` in SQL at render time.
- Current measurement timestamps use `vrecent.dtom`.
- Sparklines and trend pages query central `measurement` with `$__timeFilter`.
- Dynamic station metadata comes from central `device`/`vrecent`; static catalog values are only fallback/build-time station inventory where unavoidable.

## Error and recovery behavior

A failed source write or poll must be visible and must not corrupt central authoritative state. When a later live poll succeeds, source health transitions RECOVERED/CONNECTED and detector status is recalculated from the new `dtom`; stale OFFLINE state must not be sticky.
