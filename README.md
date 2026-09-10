# Radiation Monitoring

RadMon adalah aplikasi operator Python, central LAN PC3, alarm control, Reports, archive, dan monitoring Grafana untuk database legacy `ipradmon`.

## Menjalankan sistem

Detector asli:

```text
RADMON.bat
```

Demo seluruh station/detector:

```text
RUN_DUMMY.bat
```

Demo tetap mencakup `5202 / IS-1 Koridor` dan menulis sampel tiap **2 detik**.

Central LAN pada PC3:

```text
RUN_LAN.bat
```

PC3 central adalah `192.168.1.2`. `central_server.py` adalah satu-satunya owner background collector LAN; desktop Admin tidak menjalankan collector kedua.

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

Peran datanya:

- `measurement` = storage/history. Dipakai untuk trend, Chart, Reports, export, dan archive.
- `recent` = snapshot/aggregate operasional satu row per detector. Field seperti `doserate`, `dose`, `lastrate`, `minrate`, `maxrate`, `avgrate`, `lastdose`, `avgdose`, `lastmea`, `lastmeasec`, dan `meacount` tetap dipakai.
- `vrecent` = view `device LEFT JOIN recent` dan menjadi **sumber authoritative untuk monitoring realtime**.
- `alarm` = schema legacy production `serid + dtoa` dengan `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, dan `i_flag`.
- `applog` memakai `ts, id, msg`; `news` memakai `ts, code, content`; `rawdata` memakai `serid, dtom, val`.

Tidak ada perubahan schema yang diwajibkan pada tiga database source production.

## Central LAN PC `.2`

Tiga source production yang sudah diverifikasi dari PC `.2`:

```text
gd50 -> 192.168.1.50:3306 / ipradmon
gd52 -> 192.168.1.52:3306 / ipradmon
gd38 -> 192.168.1.38:3306 / ipradmon
```

Nama sebelum `@` adalah `source_id` internal RadMon dan harus unik/stabil; alamat setelah `@` adalah host MariaDB yang benar-benar dihubungi.

Contoh `.env` pada PC `.2`:

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

Credential production **tidak disimpan di Git**. Gunakan akun database khusus dengan privilege minimum setelah commissioning; jangan commit password/PIN/token.

### Alur pengambilan data

Pengambilan data dibagi menjadi dua worker independen per source.

Realtime worker berjalan default setiap **2 detik**:

```text
1. SELECT vrecent
   -> upsert central device + recent
2. SELECT alarm baru setelah checkpoint
   -> mirror central alarm + sidecar
```

History backfill berjalan terpisah di background:

```text
1. pilih satu detector pada source secara round-robin
2. tarik maksimal RADMON_BACKFILL_BATCH_SIZE row measurement
3. simpan ke central measurement
4. simpan checkpoint source_id + production SERID
5. giliran berikutnya pindah ke detector berikutnya
```

Dengan default `500`, tiap source hanya menarik maksimal 500 row history per giliran. Untuk tiga source berarti maksimal sekitar 1500 row per giliran, bukan 5000 row per source seperti collector lama. Setelah restart, posisi history setiap detector dilanjutkan dari checkpoint yang tersimpan; data yang sudah masuk tidak diambil ulang.

`RADMON_LAN_BATCH_SIZE` dipertahankan untuk operasi maintenance/archive drain dan bukan ukuran normal staged backfill.

Jika satu server gagal, source lain tetap berjalan dan history central yang sudah tersimpan tidak dihapus. Kegagalan backfill tidak mengubah state realtime secara palsu; konektivitas `CONNECTED/DEGRADED/OFFLINE/RECOVERED` ditentukan oleh worker realtime, sementara `last_history_import` hanya mencatat progres history.

Contoh log:

```text
[LIVE] source=gd50 host=192.168.1.50 state=CONNECTED stations=5 alarms_new=0
[BACKFILL] source=gd50 serid=3000 inserted=500 checkpoint=2026-06-22 13:02:14
```

### SERID production authoritative

Identity detector berasal dari `device.serid` production. Fallback catalog hanya dipakai ketika metadata DB tidak tersedia/dummy. Catalog fallback sudah mengikuti production, termasuk:

```text
3003  R. Sementasi
5501  PSLAT
```

Checkpoint measurement tetap per `source_id + production SERID`, dan alarm checkpoint per source memakai `(dtoa, serid)`.

### Production read-only kecuali ACK

Collector normal hanya membaca `vrecent`, `measurement`, `alarm`, dan metadata yang dibutuhkan. Source database tidak di-DELETE/TRUNCATE/DDL oleh collector.

Satu-satunya write ke source adalah ACK/Response eksplisit:

```sql
UPDATE alarm
SET ack = 1, i_op = ?, pic = ?, note = ?
WHERE serid = ? AND dtoa = ? AND i_op IS NULL
```

## Pemantauan koneksi tiga server

RadMon menyimpan status koneksi source di `runtime/radmon-security.db`, bukan menambah tabel ke production `ipradmon`.

Status:

```text
CONNECTED
DEGRADED
OFFLINE
RECOVERED
```

Metadata health mencakup host, last success/failure, last live poll, last alarm poll, last history import, error terakhir, dan consecutive failures. Default setelah 3 poll gagal berturut-turut source menjadi `OFFLINE`.

Perubahan status muncul di panel **Message** pada Recent, dicatat ke audit/applog, dan tersedia melalui:

```text
GET /api/v1/control/sources/health
```

Contoh notifikasi:

```text
[SERVER DEGRADED] gd52 / 192.168.1.52 - connection error
[SERVER OFFLINE] gd52 / 192.168.1.52 - connection error
[SERVER RECOVERED] gd52 / 192.168.1.52
```

## Alarm ACK / Response

Alarm production diidentifikasi dengan:

```text
remote SERID + dtoa
```

Polling alarm berjalan setiap cycle LAN realtime (default **2 detik**) dan incremental memakai checkpoint, bukan membaca seluruh history terus-menerus. Initial mirror alarm lama ditandai sebagai historical seed agar WhatsApp baru tidak mengirim ulang backlog lama.

Operator/Administrator dapat mengisi:

```text
Action
PIC
Note
PIN
```

ACK ditulis ke source lebih dulu. Central baru menandai acknowledged setelah source menerima update. Tidak ada perintah fisik buzzer/relay pada revisi ini.

## Admin realtime

Tab operator:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

`Recent` sekarang membaca **satu query `vrecent`** untuk seluruh station. Tidak lagi menjalankan query latest + history 10 menit per detector hanya untuk membangun current overview. `avgrate` dan stored `dose` memakai nilai aggregate dari `recent/vrecent`.

Area Message pada Recent menampilkan source-health warning dan active alarm.

## Grafana Monitoring TV

Tombol **Monitoring** membuka Playlist:

```text
Realtime -> Trends -> Operations
```

Operations memiliki 5 variant, masing-masing 3 detector. Total generator menghasilkan 7 dashboard payload, Playlist 15 item, interval **10 detik**, dan dashboard refresh **2 detik**.

Realtime/current/status membaca `vrecent`, termasuk dose rate, waktu terbaru, current highest/average, online/offline, dan kondisi Operations. Contoh waktu realtime:

```sql
SELECT UNIX_TIMESTAMP(dtom) * 1000
FROM vrecent
WHERE serid = ...
```

Grafana memformat numeric epoch sebagai datetime sehingga panel waktu tidak kembali menjadi `No data` karena string `DATE_FORMAT(...)`.

Sparkline dan trend 3 jam tetap membaca `measurement` karena membutuhkan time series historical. Alarm Terbaru membaca field legacy `dtoa/lvl/mvalue/thvalue/nhit/i_op/pic/note`.

## Reports dan archive quarterly

Active central MariaDB menyimpan data operasional aktif; quarter lama dapat dipindah menjadi archive terverifikasi agar realtime tetap ringan. Timezone default `Asia/Jakarta` (WIB).

Safe lifecycle:

```text
PENDING_DRAIN
-> EXPORTING
-> VERIFYING
-> SEALED
-> PURGING
-> COMPLETE
```

Sebelum purge central, backlog source sampai cutoff harus selesai, archive diverifikasi dengan row count/checksum SHA-256, lalu baru data quarter lama dihapus dari **central**. Production source tidak pernah dipurge oleh archive service.

Isi ZIP antara lain:

```text
manifest.json
monthly-recap.csv
device.csv
measurement.csv
alarm.csv
rawdata.csv
applog.csv
news.csv
radmon-YYYY-QN.sql
```

Retensi minimum default **5 tahun**. Reports dapat membaca archive **tanpa restore** SQL dan tetap memakai workflow **Preview -> Print / Export PDF / Export CSV**.

Konfigurasi:

```env
RADMON_ARCHIVE_ENABLED=1
RADMON_ARCHIVE_DIR=archives
RADMON_ARCHIVE_TIMEZONE=Asia/Jakarta
RADMON_ARCHIVE_MIN_RETENTION_YEARS=5
RADMON_ARCHIVE_CHECK_INTERVAL=60
```

## Authentication dan authorization

Role:

- **Administrator** — monitoring, ACK/Response, user management, edit station, archive admin.
- **Operator** — monitoring/report dan ACK/Response.
- **Viewer** — read-only.

Login memakai username + password; aksi sensitif meminta PIN user. Security store default:

```text
runtime/radmon-security.db
```

Password/PIN disimpan sebagai salted PBKDF2-SHA256 hash. Session web menggunakan token opaque server-side.

## Audit

Login/logout, ACK, perubahan Admin, source-health transition, dan archive lifecycle masuk structured audit. Ringkasan human-readable juga ditulis ke central `applog` production schema.

Secret seperti password, PIN, token, dan credential tidak dicatat ke audit.

## Secure control API

Endpoint utama:

```text
POST /auth/login
POST /auth/logout
GET  /auth/me
GET  /api/v1/control/alarms
POST /api/v1/control/alarms/{source_id}/{serid}/ack
GET  /api/v1/control/sources/health
POST /api/v1/control/stations/{serid}
GET/POST /api/v1/control/users
GET  /api/v1/control/audit
GET  /api/v1/control/archives
GET  /api/v1/control/archives/{quarter_id}/recap
POST /api/v1/control/archives/{quarter_id}/retry
```

Jika nanti diakses di luar trusted LAN, letakkan service di belakang HTTPS/TLS reverse proxy dan aktifkan secure cookie. Jangan expose MariaDB/Grafana admin port langsung ke Internet.

## WhatsApp alarm

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
