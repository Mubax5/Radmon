# Radiation Monitoring

Aplikasi operator Python, central LAN PC3, alarm control, Reports, dan monitoring Grafana untuk data `ipradmon`.

## Menjalankan sistem

Detector asli:

```text
RADMON.bat
```

Demo seluruh station/detector:

```text
RUN_DUMMY.bat
```

Demo fleet tetap mencakup station `5202 / IS-1 Koridor` bersama katalog detector canonical dan menulis sampel tiap **2 detik**.

Central LAN pada PC3:

```text
RUN_LAN.bat
```

PC3 central RadMon adalah `192.168.1.2`. `RUN_LAN.bat` menyiapkan dependency/Grafana, memastikan `central_server.py` berjalan, lalu membuka Admin dalam mode LAN. **`central_server.py` adalah satu-satunya owner background collector LAN**; desktop Admin tidak menjalankan collector kedua.

Acquisition, LAN pull, Admin, dan Grafana menargetkan refresh **2 detik**.

## Database

Database radiation memakai schema legacy `ipradmon`:

```text
device
measurement
recent
alarm
applog
news
rawdata
```

Tidak ada perubahan schema yang diwajibkan pada database production. `measurement` tetap menjadi sumber realtime/history utama dan `recent` tetap cache/aggregate legacy untuk data aktif.

`measurement.doserate` ditampilkan sebagai **µSv/h**. Nilai `measurement.dose` yang berasal dari production/import disimpan, diarsipkan, dan dilaporkan apa adanya; collector/archive tidak menghitung ulang historical dose.

## Central LAN / PC3

PC3 membaca **langsung** dari tiga primary production database yang diisi melalui `.env`. Jangan menurunkan alamat database production dari diagram/topologi lama, PC1, atau PC2.

Contoh deployment netral:

```env
RADMON_CENTRAL_HOST=192.168.1.2
RADMON_LAN_SOURCES=source-a@IP-A;source-b@IP-B;source-c@IP-C
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=isi-di-env-lokal
RADMON_LAN_DB_PASSWORD=isi-di-env-lokal
RADMON_LAN_DB_NAME=ipradmon
RADMON_LAN_BATCH_SIZE=1000
RADMON_LAN_POLL_INTERVAL=2
```

Credential production **tidak disimpan di Git**.

### SERID production adalah authoritative

Dalam LAN-central mode, identity detector berasal dari `device.serid` pada database production. Static/catalog SERID di repository tidak di-seed ke central sebelum discovery LAN dan tidak boleh mengganti **SERID production**.

Checkpoint tetap disimpan per:

```text
source_id + production SERID
```

sehingga checkpoint bertahan lintas quarter. ACK juga selalu mengetahui remote SERID production asli.

Jika SERID yang sama muncul dari source berbeda dengan metadata yang konflik, collector menolak silent merge. Shared SERID hanya boleh diizinkan eksplisit melalui `RADMON_SHARED_SERIDS` dan metadata station harus kompatibel.

### Production read-only kecuali ACK

Normal collector hanya membaca:

```text
device
measurement
alarm
INFORMATION_SCHEMA
```

Quarter archive, Reports, central purge, user management, dan maintenance archive **tidak pernah melakukan DELETE/TRUNCATE/DDL terhadap production DB**.

Satu-satunya production write adalah ACK/Response legacy yang sudah disetujui:

```sql
UPDATE alarm
SET ack = 1, i_op = ?, pic = ?, note = ?
WHERE serid = ? AND dtoa = ? AND i_op IS NULL
```

## Quarterly central archive

Active central MariaDB dirancang menyimpan **quarter kalender yang sedang berjalan**. Historical quarter dipindahkan menjadi archive terverifikasi supaya Grafana/realtime tetap ringan tetapi data regulatori tetap tersedia.

Timezone quarter default:

```text
Asia/Jakarta (WIB)
```

Boundary menggunakan interval half-open `[start, next-quarter-start)`:

```text
Q1  1 Jan 00:00 -> 1 Apr 00:00
Q2  1 Apr 00:00 -> 1 Jul 00:00
Q3  1 Jul 00:00 -> 1 Oct 00:00
Q4  1 Oct 00:00 -> 1 Jan tahun berikutnya
```

### Safe rollover

Urutan otomatis pada PC3:

```text
PENDING_DRAIN
  -> EXPORTING
  -> VERIFYING
  -> SEALED
  -> PURGING
  -> COMPLETE
```

Sebelum quarter lama dihapus dari central, PC3 terlebih dahulu memastikan backlog source lama sudah di-drain sampai cutoff. Jika satu production source offline dan completeness belum bisa dibuktikan, quarter tetap `PENDING_DRAIN`; central **tidak purge** data lama.

Setelah drain selesai, archive diekspor lalu **verified** memakai row count dan SHA-256. Purge central hanya boleh berjalan setelah verification sukses. Export/checksum failure mempertahankan data quarter lama di central agar dapat di-retry.

Purge hanya menyentuh row quarter lama pada central:

```text
measurement
alarm
rawdata
applog
news
```

`device`, LAN checkpoint, source mapping, users, password/PIN hash, session/security sidecar, dan structured audit tidak ikut dihapus. Setelah purge, `recent` dibangun ulang dari measurement quarter aktif.

### Isi paket archive

Default:

```text
archives/
  2026/
    radmon-2026-Q3.zip
```

Isi ZIP:

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

`manifest.json` menyimpan format version, quarter start/end, station/source inventory, source drain watermark, row count, checksum SHA-256 tiap payload, dan waktu pembuatan. ZIP final juga mempunyai SHA-256 pada archive index sidecar.

`monthly-recap.csv` berisi recap per bulan dan SERID: first/last measurement, sample count, min/average/max dose rate, exact `rate_sum`, sum stored `measurement.dose`, serta count ALERT/ALARM.

SQL logical restore memakai explicit column list dan tidak membawa production credential, password/PIN user, session token, atau secret lain.

### Retensi 5 tahun

RadMon mempertahankan minimal **5 tahun** quarterly archive (hingga 20 complete quarter untuk rolling five-year window). Automatic destructive prune archive yang lebih lama **OFF secara default**; rollover active DB tidak otomatis menghapus file regulatori lama.

Folder `archives/` di-ignore Git.

Konfigurasi:

```env
RADMON_ARCHIVE_ENABLED=1
RADMON_ARCHIVE_DIR=archives
RADMON_ARCHIVE_TIMEZONE=Asia/Jakarta
RADMON_ARCHIVE_MIN_RETENTION_YEARS=5
RADMON_ARCHIVE_CHECK_INTERVAL=60
```

## Reports: active + archive tanpa restore

Reports dapat membaca quarter archive **langsung dari ZIP tanpa restore SQL** ke MariaDB. Archive catalog merekonsiliasi manifest valid pada disk dengan security/operations sidecar saat central server start.

Reports tetap menggunakan workflow preview-first:

1. pilih `Active` atau quarter archive, atau isi `From` / `To`;
2. klik **Preview**;
3. cek report;
4. **Print**, **Export PDF**, atau **Export CSV**.

Archive selector menampilkan inventory seperti:

```text
2026 Q3 · July, August, September · Complete
2026 Q2 · April, May, June · Complete
```

Untuk range lintas quarter, repository report menggabungkan archived ZIP dengan active MariaDB, mengurutkan timestamp, dan deduplicate identity detector/time. Summary menggabungkan accumulator agar average tetap benar. Preview tetap dibatasi untuk responsivitas, sedangkan summary menggunakan full-range aggregate/recap.

Archive `DAMAGED` atau checksum invalid ditampilkan sebagai error; sistem tidak diam-diam mengganti missing historical data dengan active DB.

Default output report operator tetap:

```text
!REPORT!
```

## Authentication dan authorization

Admin memakai multi-user authentication.

Role:

- **Administrator** — monitoring, ACK/Response, user management, edit station/threshold/Tag, archive retry/admin.
- **Operator** — monitoring/report dan ACK/Response alarm.
- **Viewer** — read-only.

Login memakai username + password. Aksi sensitif meminta PIN user yang sedang login.

Security store default:

```text
runtime/radmon-security.db
```

Password dan PIN disimpan sebagai salted PBKDF2-SHA256 hash. Session web memakai opaque token server-side.

Bootstrap unattended opsional:

```env
RADMON_BOOTSTRAP_ADMIN_USER=
RADMON_BOOTSTRAP_ADMIN_PASSWORD=
RADMON_BOOTSTRAP_ADMIN_PIN=
```

Hapus bootstrap secret dari environment setelah akun dibuat.

## Audit

Login/logout, ACK, mutating Admin action, dan archive lifecycle dicatat ke structured audit sidecar. Ringkasan human-readable juga masuk central `applog`.

Contoh action:

```text
LOGIN_SUCCESS / LOGIN_FAILED / LOGOUT
ALARM_ACK
DEVICE_UPDATE / DEVICE_SERID_MIGRATE
USER_CREATE / USER_ENABLE / USER_DISABLE
ARCHIVE_DRAIN_PENDING
ARCHIVE_EXPORT_START / ARCHIVE_EXPORT_SUCCESS / ARCHIVE_EXPORT_FAILED
ARCHIVE_VERIFY_SUCCESS / ARCHIVE_VERIFY_FAILED
ARCHIVE_PURGE_START / ARCHIVE_PURGE_SUCCESS / ARCHIVE_PURGE_FAILED
ARCHIVE_COMPLETE / ARCHIVE_MANUAL_RETRY
```

Password, PIN, token, dan secret di-redact oleh audit layer.

## Alarm ACK / Response

Legacy alarm identity:

```text
remote SERID + dtoa
```

Field legacy mencakup `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `i_op`, `pic`, dan `note`.

Operator/Administrator dapat memilih ACK / Response, lalu mengisi Action, PIC, Note, dan PIN. ACK write-through dilakukan ke source lebih dulu; central baru menandai acknowledged setelah source menerima update.

Action awal:

```text
Confirm to Location
Checked / Condition Normal
Follow-up Required
Other
```

ACK ini tidak mengirim command fisik buzzer/relay detector. Area Active Alarm tetap menampilkan alarm aktif sampai ditangani.

## Secure control API

`central_server.py` menyediakan API session terautentikasi di atas central service. Endpoint utama:

```text
POST /auth/login
POST /auth/logout
GET  /auth/me
GET  /api/v1/control/alarms
POST /api/v1/control/alarms/{source_id}/{serid}/ack
POST /api/v1/control/stations/{serid}
GET/POST /api/v1/control/users
GET  /api/v1/control/audit
GET  /api/v1/control/archives
GET  /api/v1/control/archives/{quarter_id}/recap
POST /api/v1/control/archives/{quarter_id}/retry
```

Archive inventory/recap dapat dibaca user authenticated. Manual archive retry Administrator-only + PIN dan diaudit.

Untuk akses URL di luar trusted LAN, letakkan service di belakang HTTPS/TLS reverse proxy dan set:

```env
RADMON_WEB_COOKIE_SECURE=1
```

Jangan expose MariaDB atau Grafana admin port langsung ke Internet.

## Admin desktop

Tab operator tetap:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

Fitur termasuk login gate, identitas role, Active Alarm strip, ACK/Response + PIN, user management Administrator, edit station, logout, report archive selector, dan Silk icons.

### Chart

Visual:

- **Trend** — dose rate, optional Approx. Dose, zoom/pan/crosshair dan threshold.
- **Status Pie** — NORMAL / ALERT / ALARM.
- **Threshold Progress** — current / average / peak dibanding alarm threshold.

## Grafana Monitoring TV

Tombol **Monitoring** membuka Playlist RadMon TV:

```text
Realtime -> Trends -> Operations
```

Operations memiliki 5 variant, masing-masing 3 detector. Total generator menghasilkan 7 dashboard payload (1 Realtime + 1 Trends + 5 Operations), Playlist 15 item, interval **10 detik**, dan dashboard refresh **2 detik**.

Page 1 Realtime menampilkan 15 dose-rate card menggunakan latest `measurement`. Measurement time memakai numeric epoch milliseconds:

```sql
UNIX_TIMESTAMP(MAX(m.dtom)) * 1000
```

Grafana memformatnya sebagai `dateTimeAsLocal`, menghindari panel waktu `No data` akibat string `DATE_FORMAT(...)`.

Page 2 menampilkan trend 3 jam/small multiples. Page 3 Operations menampilkan status detector, kondisi operasional, count NORMAL/ALERT/ALARM/OFFLINE, dan alarm terbaru.

## WhatsApp alarm

Dispatcher WhatsApp membaca mirrored alarm central dan hanya menandai notification sent setelah sender berhasil.

Disabled by default:

```env
RADMON_WHATSAPP_ENABLED=0
RADMON_WHATSAPP_GROUP=Alarm_Radmon
RADMON_WHATSAPP_PROFILE=runtime/whatsapp-profile
RADMON_WHATSAPP_DRIVER=
RADMON_WHATSAPP_INTERVAL=20
```

Browser profile/credential tidak boleh di-commit.

## Existing push sync / server pusat

Mekanisme push SyncAgent lama ke **server pusat** tetap tersedia dan default OFF:

```env
RADMON_SYNC_ENABLED=1
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-token
```

Ini terpisah dari direct LAN pull PC3.

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
