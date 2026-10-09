# RadMon architecture

## Purpose and status

RadMon collects radiation measurements from LAN detector databases, keeps an
authoritative central history, and exposes an authenticated operator control
plane plus a Grafana monitoring surface. This document is a technical
architecture reference; it is not a deployment certificate.

The source behavior described here is based on the audited workspace baseline
`403efbce` (8 October 2026). Production commissioning, TLS, firewall rules,
NTFS ACLs, database privileges, and physical alarm acceptance remain separate
work.

## Runtime components

```text
LAN detector MariaDBs (.50, .52, .38)
             │ read / controlled legacy alarm write-through
             ▼
Central RadMon service :8090 ── authenticated web API and Grafana gateway
       │          │
       │          ├── React Control Plane (/app)
       │          └── Grafana native :3300 (loopback only)
       │
        ├── central MariaDB: measurement, alarm, device, recent, recent_last, vrecent
       └── runtime SQLite: users, sessions, audit, policy, checkpoints, jobs
```

The Windows Scheduled Task `RadMon Server` owns the headless service. The
desktop and browser are clients; closing them does not stop collection or the
API. Node.js is a build-time dependency, not a production server dependency.

## Network boundaries

- TCP `8090` is the BRIN-facing RadMon gateway. The actual routing and ACL
  boundary remains the BRIN network.
- Grafana native listens on `127.0.0.1:3300`; it is not a remote client port.
- Remote monitoring is session-gated and should be reached through an HTTPS
  reverse proxy. The proxy network must be explicitly configured as trusted.
- MariaDB ports and the single-instance listener `47652` are not browser
  interfaces and must not be opened to the client LAN as a shortcut.

## Data ownership

`measurement` is the long-term source of truth for measurements. `alarm` is
the source event relation, and `device` contains station metadata. RadMon does
not perform DDL on detector/source databases.

The central rolling read model is deliberately separate:

- `recent` contains real samples from the latest three hours and is the indexed
  monitoring hot path.
- `vrecent` joins the rolling sample with station metadata and current runtime
  status. Current consumers select the newest row per SERID.
- `recent_last` keeps at most 30 latest genuine samples per detector for an
  offline last-reading view. It does not extend the three-hour hot window and
  is not historical source of truth.
- Grafana current/latest and status panels read `vrecent`; continuous sparkline
  and trend targets read the bounded `recent` table; the offline table reads
  `recent_last`.
- When no rolling sample exists, current status may show the last genuine
  `measurement`, but it remains `OFFLINE` and displays the original timestamp
  and age. RadMon does not invent a fresh value or timestamp.

History, reports, and archive workflows intentionally use historical relations.
They are not the two-second monitoring hot path.

## Alarm truth model

The central policy layer determines which events are surfaced to operators. A
source response is a separate operation against one exact source row
`(serid, dtoa)`:

1. the displayed source row must still have `i_flag=0`;
2. the backend writes `i_op`, `pic`, `note`, and `i_flag=1`;
3. it commits and reads the same row back;
4. only confirmed `i_flag=1` is reported as source-handled.

The legacy `ack` field is not changed by this workflow. A central policy event,
SQL read-back, or browser sound state does not certify that a physical detector
buzzer has stopped. Hardware acceptance belongs to commissioning.

## Jobs and durability

Reports and archive exports are asynchronous jobs. They publish complete files
through a temporary-file-and-rename flow, retain job status, and recover queued
work after a clean restart. A report preview is intentionally partial; a full
report must pass the range and row limits before it is generated.

Quarter archives are exported only from verified `COMPLETE` bundles. Archive
purge is gated by source drain and bundle verification. The source production
database is not purged by the archive service.

## Verification boundary

CI validates source tests, frontend checks/build, package smoke tests, and
updater behavior. It does not validate a particular installation. Before
production use, the owner must commission connectivity, HTTPS/trusted origins,
least-privilege database access and transport, NTFS permissions, backups with a
real restore, Grafana persistence, alarm write-through, and detector buzzer
acceptance.
