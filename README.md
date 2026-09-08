# Radiation Monitoring

Aplikasi operator Python, agregasi LAN, dan monitoring Grafana untuk data `ipradmon`.

## Menjalankan sistem

Detector asli:

```text
RADMON.bat
```

Demo seluruh station/detector:

```text
RUN_DUMMY.bat
```

Demo fleet tetap mencakup station `5202 / IS-1 Koridor` bersama seluruh katalog detector canonical dan menulis sampel tiap 2 detik.

Central LAN pada PC3:

```text
RUN_LAN.bat
```

Acquisition, LAN pull, Admin, dan Grafana menargetkan refresh **2 detik**. `SingleInstanceLock` mencegah mode acquisition/Admin lokal yang saling bertabrakan.

## Database

Database radiation tetap memakai schema `ipradmon` yang sudah ada:

```text
device
measurement
recent
alarm
applog
news
rawdata
```

Tidak ada perubahan schema yang diwajibkan pada database production Gd.50/Gd.52/Gd.38. `measurement` tetap menjadi sumber realtime/history utama. `recent` dipertahankan sebagai aggregate/cache legacy.

`measurement.doserate` ditampilkan sebagai **µSv/h**. Nilai `measurement.dose` hasil production/import disimpan dan dipakai langsung; proses LAN tidak menghitung ulang historical dose.

## Central LAN / PC3

Mode LAN menggabungkan history dari beberapa database production dalam satu `ipradmon` lokal PC3.

Contoh konfigurasi:

```env
RADMON_LAN_ENABLED=1
RADMON_LAN_SOURCES=gd50@192.168.1.50;gd52@192.168.1.52;gd38@192.168.1.38
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=isi-di-env-lokal
RADMON_LAN_DB_PASSWORD=isi-di-env-lokal
RADMON_LAN_DB_NAME=ipradmon
RADMON_LAN_BATCH_SIZE=1000
RADMON_LAN_POLL_INTERVAL=2
```

Credential production **tidak disimpan di Git**. Letakkan credential hanya pada `.env` deployment.

Per source, RadMon:

1. membaca katalog `device`;
2. menarik `measurement` incremental per station;
3. menyimpan checkpoint per `source + remote SERID`;
4. memasukkan history ke central dengan duplicate suppression;
5. mempertahankan `dtom`, `doserate`, `dose`, `previnterval`, dan `stat` dari source;
6. membaca/mirror alarm source;
7. tetap menjalankan source lain jika satu server LAN gagal.

Central menyimpan **full history**, bukan hanya latest value. Jika source offline, history yang sudah terkumpul tetap tersedia dan freshness akan membuat station menjadi `OFFLINE`.

### Remote SERID dan Tag central

Remote detector identity dan Tag central dipisahkan melalui mapping lokal. Administrator dapat mengganti Tag/SERID untuk presentasi central tanpa mengubah SERID di database production. Pull berikutnya tetap membaca remote SERID asli, tetapi menulis ke central SERID yang sudah dipetakan. ACK alarm juga tetap diarahkan ke remote SERID asli.

## Authentication dan authorization

Admin sekarang restricted dan memakai multi-user authentication.

Role:

- **Administrator** — monitoring, ACK/Response, user management, edit station/threshold/Tag.
- **Operator** — monitoring/report dan ACK/Response alarm.
- **Viewer** — read-only.

Login memakai **username + password**. Aksi sensitif meminta **PIN user yang sedang login** lagi.

Security store default:

```text
runtime/radmon-security.db
```

Store ini SQLite terpisah dari `ipradmon`. Password dan PIN disimpan sebagai salted PBKDF2-SHA256 hash, bukan plaintext. Session web memakai token opaque yang disimpan server-side.

Jika security store masih kosong, aplikasi desktop menampilkan wizard pembuatan Administrator pertama. Alternatif bootstrap unattended dapat memakai environment variable berikut dan harus dihapus dari environment deployment setelah akun dibuat:

```env
RADMON_BOOTSTRAP_ADMIN_USER=
RADMON_BOOTSTRAP_ADMIN_PASSWORD=
RADMON_BOOTSTRAP_ADMIN_PIN=
```

## Audit

Setiap login/logout dan aksi mutating/sensitif mempunyai structured audit pada security store. Contoh:

```text
LOGIN_SUCCESS / LOGIN_FAILED / LOGOUT
ALARM_ACK
DEVICE_UPDATE / DEVICE_SERID_MIGRATE
USER_CREATE / USER_ENABLE / USER_DISABLE
PASSWORD_RESET / PIN_RESET
```

Perubahan menyimpan actor, role, target, source, status sukses/gagal, serta nilai **before -> after** bila relevan. Field rahasia seperti password, PIN, token, dan secret di-redact.

Ringkasan human-readable aksi juga ditulis ke central `ipradmon.applog` sehingga tetap terlihat dalam workflow log existing.

## Alarm ACK / Response

Source legacy didukung dengan identity alarm:

```text
remote SERID + dtoa
```

Field legacy yang digunakan mencakup `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `i_op`, `pic`, dan `note`.

Admin menampilkan alarm dalam gaya legacy dengan Event Time, Level, Dose Rate, Threshold, Hit Count, Action Time, PIC, Action, dan Note. Operator/Administrator dapat memilih **ACK / Response**, lalu mengisi:

- Action;
- PIC;
- Note;
- PIN user.

Action awal:

```text
Confirm to Location
Checked / Condition Normal
Follow-up Required
Other
```

ACK adalah **write-through** ke database source dengan guard `i_op IS NULL`. Central baru menandai alarm acknowledged setelah write source berhasil. Revisi ini **tidak mengirim perintah fisik** untuk mematikan buzzer/relay Raspberry Pi/detector.

Admin juga mempunyai area **Active Alarm** di bagian bawah agar pesan alarm aktif tetap terlihat sampai ditangani.

## Edit station

Administrator + PIN dapat mengubah:

- Tag / SERID central;
- Name;
- Location;
- Description;
- Alert threshold;
- Alarm threshold;
- max idle;
- unit.

Perubahan dicatat dengan nilai sebelum dan sesudah. Penggantian Tag central memigrasikan referensi central dan mapping source; remote production SERID tidak otomatis diubah.

## Secure control API / persiapan akses via URL

`central_server.py` sekarang memasang secure control routes di atas central API existing. Ingestion SyncAgent tetap memakai Bearer Token seperti sebelumnya; browser/operator memakai session terpisah.

Route utama:

```text
POST /auth/login
POST /auth/logout
GET  /auth/me
GET  /api/v1/control/alarms
POST /api/v1/control/alarms/{source_id}/{serid}/ack
POST /api/v1/control/stations/{serid}
GET/POST /api/v1/control/users
GET  /api/v1/control/audit
```

Authorization dilakukan **server-side** pada setiap endpoint. Tombol yang disembunyikan di UI bukan security boundary.

Saat sistem benar-benar diterbitkan melalui URL di luar trusted LAN, pasang service di belakang **HTTPS/TLS reverse proxy**, set:

```env
RADMON_WEB_COOKIE_SECURE=1
```

dan jangan expose MariaDB/Grafana admin port langsung ke Internet. Grafana TV tetap presentation layer read-only dan bukan interface kontrol Admin.

## Admin

Tab operator tetap:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

Tambahan UI:

- Login gate;
- identitas user + role;
- Active Alarm strip;
- ACK / Response + PIN;
- User Management untuk Administrator;
- Edit Station untuk Administrator;
- Logout;
- Silk icons pada action baru menggunakan icon bundle yang sudah ada.

### Chart

Visual:

- **Trend** — dose rate, optional Approx. Dose, zoom/pan/crosshair dan threshold.
- **Status Pie** — NORMAL / ALERT / ALARM.
- **Threshold Progress** — current / average / peak dibanding alarm threshold.

### Reports

1. pilih `From` dan `To`;
2. klik **Preview**;
3. cek report;
4. **Print**, **Export PDF**, atau **Export CSV**.

Default output:

```text
!REPORT!
```

## Grafana Monitoring TV

Tombol **Monitoring** membuka playlist RadMon TV dengan tiga logical page:

```text
Realtime -> Trends -> Operations
```

Operations mempunyai **5 variant**, masing-masing 3 detector:

```text
Cycle 1 -> Realtime -> Trends -> Operations 1/5
Cycle 2 -> Realtime -> Trends -> Operations 2/5
Cycle 3 -> Realtime -> Trends -> Operations 3/5
Cycle 4 -> Realtime -> Trends -> Operations 4/5
Cycle 5 -> Realtime -> Trends -> Operations 5/5
```

Total generator menghasilkan **7 dashboard payload** (1 Realtime + 1 Trends + 5 Operations), playlist **15 item**, interval **10 detik**, dan tiap dashboard refresh **2 detik**.

Semua dashboard memakai header:

- kiri: hari + tanggal WIB dengan font kecil;
- tengah: `Instalasi Pengelolaan Limbah Radioaktif` / `Direktorat Pengelolaan Fasilitas Ketenaganukliran` dengan ukuran font existing;
- kanan: waktu update WIB dengan font kecil.

### Page 1 — Realtime

15 dose-rate card menggunakan latest `measurement`. Waktu measurement menggunakan nilai numeric epoch milliseconds:

```sql
UNIX_TIMESTAMP(MAX(m.dtom)) * 1000
```

dan diformat Grafana sebagai `dateTimeAsLocal`. Ini menggantikan string `DATE_FORMAT(...)` yang menyebabkan panel waktu menjadi `No data` pada Grafana.

### Page 2 — Trends

Small-multiple 3 jam per gedung plus summary current highest/average/online/offline.

> Catatan: trend saat ini masih mempertahankan contract Y-axis `0..1 µSv/h` dari versi sebelumnya. Ini perlu keputusan terpisah bila ingin adaptive/threshold scaling.

### Page 3 — Operations

Menampilkan Status Detector, satu tabel kondisi operasional 3 station per variant, count NORMAL/ALERT/ALARM/OFFLINE, dan Alarm Terbaru 24 Jam.

## WhatsApp alarm

WhatsApp dispatcher sekarang membaca **central mirrored alarm**, bukan polling tiga DB secara terpisah. Notifikasi hanya ditandai sent setelah sender berhasil sehingga kegagalan dapat di-retry tanpa menandai alarm palsu sebagai terkirim.

Disabled by default:

```env
RADMON_WHATSAPP_ENABLED=0
RADMON_WHATSAPP_GROUP=Alarm_Radmon
RADMON_WHATSAPP_PROFILE=runtime/whatsapp-profile
RADMON_WHATSAPP_DRIVER=
RADMON_WHATSAPP_INTERVAL=20
```

Browser profile dan credential tidak boleh di-commit.

## Existing push sync

Mekanisme SyncAgent lama tetap tersedia dan default OFF:

```env
RADMON_SYNC_ENABLED=1
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-token
```

Ini terpisah dari mode LAN pull baru.

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
```

Output runtime (`!REPORT!`, logs, runtime, venv, cache, security DB, WhatsApp profile) tidak ditrack Git.
