# Radiation Monitoring

RadMon adalah aplikasi operator Python, central LAN PC `.2`, alarm control, Reports, quarterly archive, WhatsApp alarm, dan monitoring Grafana untuk database legacy `ipradmon`.

## Menjalankan sistem

Detector asli:

```text
RADMON.bat
```

Demo seluruh station/detector:

```text
RUN_DUMMY.bat
```

Dataset demo tetap mencakup detector contoh **5202 / IS-1 Koridor** agar workflow multi-station dapat diuji tanpa hardware production.

Central LAN pada PC `.2`:

```text
RUN_LAN.bat
```

PC central adalah `192.168.1.2`. `central_server.py` adalah owner background collector LAN; desktop Admin tidak menjalankan collector LAN kedua.

## Database production

Nama database tetap **`ipradmon`** dan runtime mengikuti schema production aktual:

```text
device
measurement
recent
vrecent
alarm
applog
news
rawdata
```

Peran utama:

- `measurement` = storage/history untuk Chart, Reports, export, dan archive.
- `recent` = snapshot/aggregate operasional satu row per detector.
- `vrecent` = view `device LEFT JOIN recent` dan sumber authoritative monitoring realtime.
- `alarm` = schema legacy production `serid + dtoa` dengan `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, dan `i_flag`.
- `applog`, `news`, dan `rawdata` tetap mengikuti schema legacy masing-masing.

**RadMon tidak mewajibkan perubahan schema pada database source production.** State policy/suppression, audit, checkpoint, dan retry metadata disimpan di central sidecar/runtime database.

## Central LAN PC `.2`

Source production:

```text
gd50 -> 192.168.1.50:3306 / ipradmon
gd52 -> 192.168.1.52:3306 / ipradmon
gd38 -> 192.168.1.38:3306 / ipradmon
```

Contoh konfigurasi:

```env
RADMON_CENTRAL_HOST=192.168.1.2
RADMON_DB_HOST=localhost
RADMON_DB_NAME=ipradmon

RADMON_LAN_ENABLED=1
RADMON_LAN_SOURCES=gd50@192.168.1.50;gd52@192.168.1.52;gd38@192.168.1.38
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=isi-di-env-lokal
RADMON_LAN_DB_PASSWORD=isi-di-env-lokal
RADMON_LAN_DB_NAME=ipradmon

RADMON_LAN_POLL_INTERVAL=2
RADMON_LAN_OFFLINE_AFTER_FAILURES=3
RADMON_BACKFILL_ENABLED=1
RADMON_BACKFILL_BATCH_SIZE=500
RADMON_BACKFILL_INTERVAL=2
RADMON_LAN_BATCH_SIZE=1000
```

Credential production **tidak disimpan di Git**. Gunakan akun database khusus dengan privilege minimum setelah commissioning.

### Realtime dan backfill

Realtime worker per source berjalan default setiap **2 detik**:

```text
1. SELECT vrecent
   -> upsert central device + recent
2. SELECT alarm baru setelah checkpoint
   -> mirror raw alarm central + sidecar
3. evaluasi current live dose melalui Alarm Policy
4. klasifikasikan raw source alarm terhadap keputusan policy
5. proses retry source-silence yang jatuh tempo (maks. 25 row/cycle)
```

History backfill berjalan terpisah:

```text
1. pilih detector round-robin
2. tarik maksimal RADMON_BACKFILL_BATCH_SIZE row measurement
3. simpan central measurement
4. simpan checkpoint source_id + production SERID
5. lanjut detector berikutnya
```

Initial/backfill alarm lama ditandai sebagai historical evidence dan tidak menjadi notifikasi baru.

Jika satu server gagal, source lain tetap berjalan dan history central yang sudah tersimpan tidak dihapus. State source `CONNECTED/DEGRADED/OFFLINE/RECOVERED` disimpan di central sidecar.

## SERID production authoritative

Identity detector berasal dari `device.serid` production. Checkpoint measurement tetap per `source_id + production SERID`, dan checkpoint alarm per source memakai `(dtoa, serid)`.

## Alarm Policy

Operator-facing alarm tidak lagi bergantung langsung pada setiap raw row source. Raw row tetap disimpan sebagai evidence; keputusan operator dibuat oleh policy restart-safe di central SQLite.

Aturan episode:

```text
HIGH #1 -> ALARM #1
HIGH berikutnya <= 5 menit dari #1 -> ALARM #2
HIGH berikutnya <= 5 menit dari #1 -> ALARM #3 -> RETRIGGER LOCKED
```

Ketentuan:

- maksimum **3 surfaced ALARMs** dalam burst lima menit;
- window lima menit selalu di-anchor ke ALARM #1;
- bila `> 5 menit` dari #1 dan #3 belum tercapai, HIGH berikutnya membuka burst baru sebagai #1;
- ALARM #3 langsung mengaktifkan `RETRIGGER_LOCKED`;
- `ALERT` tidak mereset episode;
- hanya `NORMAL`, yaitu dose `< LOW/WARN`, yang mereset trigger count dan `RETRIGGER_LOCKED`;
- duplicate/raw source alarm tidak menambah counter sendiri;
- historical/backfill seed tidak menjadi notification candidate baru;
- state, active event, suppression, dan notification marker bertahan setelah restart.

## ACK / Response dan source write-through

Administrator/Operator merespons policy event dengan:

```text
Action
PIC
Note / Reason
PIN
```

Source response memakai kontrak legacy yang aman:

```sql
UPDATE alarm
SET i_op = ?, pic = ?, note = ?, i_flag = 1
WHERE serid = ? AND dtoa = ? AND i_flag = 0
```

**Kolom `ack` dipertahankan dan tidak diubah.** Tidak ada migration/DDL yang dijalankan terhadap tiga source MariaDB tersebut.

Jika source sedang gagal ketika central harus melakukan silence/response, central state tetap konsisten. Raw row dicatat sebagai `PENDING`/`FAILED` dan diretry dengan backoff `5s, 15s, 30s, 60s` (cap 60 detik), maksimal 25 pending row per live cycle. Recovery source hanya mengubah state write-through raw row; tidak membuat operator-facing event kedua.

## Timed Alarm Suppression

Administrator dan Operator dapat menjalankan **Suppress Alarm...** per detector. Viewer hanya dapat melihat.

Rules:

- durasi wajib **60..86400 detik** (1 menit..24 jam);
- PIN + PIC + reason wajib;
- tidak ada suppression indefinite;
- hanya satu active suppression per detector;
- Auto Resume on NORMAL tersedia dan default aktif di dialog;
- Auto Resume hanya terjadi jika dose benar-benar `< LOW/WARN`, bukan ketika hanya turun ke ALERT;
- sesi yang tidak melihat HIGH menghasilkan **0** event `SUPPRESSED`;
- satu atau banyak HIGH dalam sesi yang sama menghasilkan **tepat 1** event `SUPPRESSED`;
- trigger count tidak bertambah karena HIGH yang sedang disuppress;
- measurement tidak dihentikan dan dose aktual tetap terlihat;
- underlying `NORMAL/ALERT/ALARM`, PIC, reason, dan expiry tetap tersedia untuk UI/API/Grafana;
- jika suppression expired saat dose masih HIGH, policy dapat surface fresh ALARM kecuali detector masih `RETRIGGER_LOCKED`.

PIN yang secara eksplisit salah tetap ditolak walaupun user masih mempunyai sensitive-operation lease.

## Admin realtime

Tab operator:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

`Recent` membaca `vrecent` untuk overview seluruh station. Jika `SUPPRESSED`, nilai dose rate tetap tampil dan tooltip/status menunjukkan underlying condition, PIC, reason, dan expiry.

Tab `Alarm` menampilkan policy event bersama kolom legacy-compatible seperti `Hit count`, ditambah `Policy` dan `Underlying`. Tombol **ACK / Response** menggunakan policy event ID; tombol **Suppress Alarm...** tersedia untuk Administrator/Operator.

Panel Message menampilkan source health, active operator-facing ALARM, serta status suppression/retrigger-lock tanpa memformat `SUPPRESSED` sebagai audible alarm baru.

## Central runtime projection

Current policy state diproyeksikan ke **central MariaDB saja**:

```text
radmon_runtime_status
```

Projection mencakup policy state, trigger count, retrigger lock, suppression metadata, dan underlying dose status. Tabel ini bukan bagian dari source production dan tidak dibuat pada host source.

## Secure control API

Endpoint utama:

```text
POST /auth/login
POST /auth/logout
GET  /auth/me

GET  /api/v1/control/alarms
GET  /api/v1/control/alarm-events
POST /api/v1/control/alarm-events/{event_id}/response
GET  /api/v1/control/alarm-policy/{serid}
GET  /api/v1/control/suppressions
POST /api/v1/control/suppressions/{serid}

POST /api/v1/control/alarms/{source_id}/{serid}/ack
GET  /api/v1/control/sources/health
POST /api/v1/control/stations/{serid}
GET/POST /api/v1/control/users
GET  /api/v1/control/audit
GET  /api/v1/control/archives
GET  /api/v1/control/archives/{quarter_id}/recap
POST /api/v1/control/archives/{quarter_id}/retry
```

API memakai authenticated session dan role/PIN checks. Viewer tidak dapat membuat suppression.

## Authentication dan authorization

Role:

- **Administrator** — monitoring, ACK/Response, suppression, user management, edit station, archive admin.
- **Operator** — monitoring/report, ACK/Response, dan suppression.
- **Viewer** — read-only.

Security store default:

```text
runtime/radmon-security.db
```

Password/PIN memakai salted PBKDF2-SHA256. Session web memakai opaque server-side token. Secret tidak ditulis ke audit.

## WhatsApp alarm

WhatsApp disabled by default:

```env
RADMON_WHATSAPP_ENABLED=0
RADMON_WHATSAPP_GROUP=Alarm_Radmon
RADMON_WHATSAPP_PROFILE=runtime/whatsapp-profile
RADMON_WHATSAPP_DRIVER=
RADMON_WHATSAPP_INTERVAL=20
```

Dispatcher central membaca **persisted policy events**, bukan raw alarm mirror. Hanya event `kind=ALARM`, `status=ACTIVE`, dan `notification_sent_at IS NULL` yang dapat dikirim. Setelah sukses, marker dikunci di SQLite sehingga restart dispatcher tidak mengirim event yang sama dua kali. `SUPPRESSED`, responded, retrigger-locked, dan historical seed tidak dikirim sebagai alarm baru.

Notification delivery tetap tertutup saat restore startup dan baru dibuka setelah fresh live policy cycle pertama selesai.

Browser profile/credential tidak boleh di-commit.

## Grafana Monitoring TV

Tombol **Monitoring** membuka Playlist:

```text
Realtime -> Trends -> Operations
```

Generator menghasilkan 7 dashboard payload dan playlist 15 item. Playlist interval tetap **10 detik**, dashboard refresh tetap **2 detik**.

Waktu database production adalah WIB wall-clock dan query tetap menggunakan `CONVERT_TZ`. Page realtime/status membaca `vrecent`; history trend membaca `measurement`.

Operations melakukan `LEFT JOIN radmon_runtime_status` sehingga status memiliki urutan:

```text
OFFLINE
SUPPRESSED
ALARM
ALERT
NORMAL
```

`SUPPRESSED` tidak menggantikan dose rate; kolom `Underlying` dan detail suppression tetap terlihat.

## Reports dan quarterly archive

Quarter lama dapat dipindah menjadi archive terverifikasi agar realtime tetap ringan. Lifecycle:

```text
PENDING_DRAIN
-> EXPORTING
-> VERIFYING
-> SEALED
-> PURGING
-> COMPLETE
```

Sebelum purge central, backlog source sampai cutoff harus selesai dan archive **diverifikasi**. **Production source tidak pernah dipurge oleh archive service.**

Bundle archive mencakup data CSV/SQL dan metadata verifikasi, termasuk `manifest.json` serta `monthly-recap.csv`. Retensi minimum default **5 tahun**. Reports dapat membaca archive **tanpa restore** SQL.

Workflow report operator tetap memakai **Preview -> Print / Export PDF / Export CSV**.

## Audit

Login/logout, response policy, suppression, source-silence failure/retry, perubahan Admin, source-health transition, dan archive lifecycle masuk structured audit. Ringkasan human-readable juga ditulis ke central `applog`.

## Existing push sync / server pusat

Mekanisme push SyncAgent lama tetap tersedia dan default OFF:

```env
RADMON_SYNC_ENABLED=1
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-token
```

Ini terpisah dari direct LAN pull PC `.2`.

## Struktur utama repo

```text
RADMON.bat
RUN_DUMMY.bat
RUN_LAN.bat
main.py
central_server.py
radmon/
grafana/
tests/
docs/
```

Output runtime (`!REPORT!`, logs, runtime, archives, venv, cache, security DB, WhatsApp profile) tidak ditrack Git.

## Verification vs commissioning

GitHub Actions memverifikasi unit/integration tests, Python compile, dan kontrak payload Grafana. Hal itu **bukan** pengganti commissioning LAN/hardware nyata di PC `.2`; koneksi source, device, alarm write-through, Grafana service, dan perangkat lapangan tetap harus divalidasi pada environment production sebelum release operasional penuh.
