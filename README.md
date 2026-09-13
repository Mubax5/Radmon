# Radiation Monitoring

RadMon adalah platform monitoring radiasi untuk central PC **`192.168.1.2`**. Production Windows dipasang melalui **`RadMon-Setup.exe`** dan dijalankan 24/7 oleh Scheduled Task `RadMon Server` menggunakan **`app\RadMon.exe --server`**. Operator tidak perlu login Windows atau membiarkan desktop PySide terbuka agar collector/API/web tetap hidup.

## Surface production

Di network BRIN/LAN yang diizinkan:

```text
http://192.168.1.2:8090/       -> Grafana monitoring fullscreen/kiosk, tanpa login RadMon
http://192.168.1.2:8090/app    -> RadMon Control Plane, wajib login
http://localhost:3300          -> Grafana admin/editor di PC server
```

Anonymous hanya mendapat monitoring Grafana read-only. **Viewer tetap wajib login RadMon**. Role aplikasi:

- **Viewer** — Overview, Stations, History, Archives/Reports read-only.
- **Operator** — Viewer + Alarm, Response/Silence, dan timed Suppression.
- **Administrator** — Operator + user/station/system administration dan akses editor Grafana.

Frontend `/app` dibuild dari React + TypeScript + **Cloudflare Kumo UI** + Phosphor Icons. Node.js hanya dipakai saat build; production menyajikan static assets dari FastAPI sehingga tidak ada Node server 24/7.

## Paket production Windows

Installer mempunyai layout persistent berikut:

```text
RadMon\
  app\
    RadMon.exe
    web\
    docs\manual\
    grafana\
  config\
    .env.example
    .env
  runtime\
  archives\
  reports\
```

`config\.env`, `runtime`, `archives`, dan `reports` adalah data lokal dan **tidak ditimpa saat upgrade**. Installer mendaftarkan Scheduled Task `RadMon Server` saat boot Windows sebagai SYSTEM dengan restart otomatis bila proses berhenti. Firewall hanya membuka port `8090` dan `3300` untuk `LocalSubnet`.

### First installation

1. Jalankan `RadMon-Setup.exe` sebagai Administrator.
2. Edit `config\.env` dan isi credential database central + source LAN.
3. Untuk security store yang belum mempunyai user, isi sekali:

```env
RADMON_BOOTSTRAP_ADMIN_USER=admin-radmon
RADMON_BOOTSTRAP_ADMIN_PASSWORD=GANTI_PASSWORD_KUAT
RADMON_BOOTSTRAP_ADMIN_PIN=GANTI_PIN
```

4. Pastikan Grafana native tersedia; bila lokasinya non-standar isi `RADMON_GRAFANA_BIN`.
5. Restart task `RadMon Server` atau reboot Windows setelah konfigurasi lengkap.
6. Login RadMon di `/app`; setelah Administrator berhasil terbentuk, bootstrap password/PIN dapat dihapus dari `.env`.

Production normal **tidak memerlukan Docker Desktop**. `RADMON_GRAFANA_DOCKER_FALLBACK=0` adalah default untuk menjaga penggunaan RAM rendah pada host 6 GB.

## Grafana editable dan persistent

Grafana production menggunakan port stabil **3300**. Dashboard/playlist default hanya menjadi **initial seed**. Startup berikutnya tidak mengembalikan dashboard ke template Python.

Alur editing:

```text
localhost:3300 -> login Grafana (default admin/admin) -> Edit -> Save
                                                |
                                                v
                                  state tersimpan di runtime/grafana
                                                |
                                                v
                        monitoring anonymous menampilkan dashboard yang sama
```

Jika dashboard hasil versi RadMon lama masih `editable=false`, bootstrap baru melakukan migrasi satu kali dengan mempertahankan JSON dashboard yang tersimpan (layout/panel/query) dan hanya membuka flag edit. Sesudah itu dashboard Grafana menjadi authoritative. Restart RadMon, Grafana, atau Windows **tidak rollback hasil Save**.

Anonymous Grafana tetap role Viewer; form login Grafana tetap tersedia di `localhost:3300` untuk Administrator. Landing monitoring `/` langsung redirect ke Playlist kiosk sehingga tidak mempunyai tombol Sign in RadMon, sidebar RadMon, atau wrapper aplikasi.

## Database production

Database tetap **`ipradmon`** dengan schema production aktual:

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

`measurement` menyimpan history untuk History/Chart, Reports, export, dan archive. `recent` adalah snapshot operasional satu row per detector. `vrecent` adalah sumber authoritative monitoring realtime. `alarm` mengikuti schema legacy production `serid + dtoa` dengan `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, dan `i_flag`.

**RadMon tidak melakukan DDL pada database source production.** State policy/suppression, audit, checkpoint, retry metadata, session, dan security disimpan di central/runtime storage.

## Central LAN PC `.2`

Source production:

```text
gd50 -> 192.168.1.50:3306 / ipradmon
gd52 -> 192.168.1.52:3306 / ipradmon
gd38 -> 192.168.1.38:3306 / ipradmon
```

Contoh `config\.env`:

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
RADMON_GRAFANA_PORT=3300
RADMON_GRAFANA_USER=admin
RADMON_GRAFANA_PASSWORD=admin
RADMON_GRAFANA_DOCKER_FALLBACK=0
```

Realtime worker per source berjalan default setiap **2 detik**. History backfill mempunyai checkpoint `source_id + SERID production`; kegagalan satu source tidak menghentikan source lain dan history central yang sudah tersimpan tidak dihapus.

Dataset developer tetap mencakup detector contoh **5202 / IS-1 Koridor** untuk regression multi-station.

## Alarm Policy dan control

Operator-facing alarm dikendalikan policy restart-safe di central storage; raw source alarm tetap menjadi evidence. Burst HIGH dapat surface maksimum tiga ALARM dalam window lima menit yang di-anchor ke ALARM #1. ALARM #3 mengaktifkan `RETRIGGER_LOCKED`, dan hanya kondisi `NORMAL` (`dose < LOW/WARN`) yang mereset counter/lock. `ALERT` tidak mereset episode.

Administrator/Operator dapat melakukan Response/Silence dan timed suppression 1 menit sampai 24 jam. Source write-through memakai kontrak legacy:

```sql
UPDATE alarm
SET i_op = ?, pic = ?, note = ?, i_flag = 1
WHERE serid = ? AND dtoa = ? AND i_flag = 0
```

Kolom `ack` dipertahankan. Jika source sedang gagal, silence/response diretry dengan backoff `5s, 15s, 30s, 60s` dan maksimum 25 pending row per live cycle.

## Reports dan quarterly archive

Workflow report tetap **Preview -> Print / Export PDF / Export CSV**. Quarter lama dapat dipindah ke archive **terverifikasi** melalui lifecycle `PENDING_DRAIN -> EXPORTING -> VERIFYING -> SEALED -> PURGING -> COMPLETE`. Sebelum **purge** central, backlog source sampai cutoff harus selesai dan bundle archive harus terverifikasi; source production tidak pernah dipurge oleh archive service.

Bundle archive mencakup `manifest.json` dan `monthly-recap.csv`. Checkpoint/drain tetap diikat ke `source_id + SERID production`. Retensi minimum default **5 tahun** dan report archive dapat dibaca **tanpa restore** SQL.

## Grafana Monitoring TV

Generator factory tetap menyediakan dashboard `Realtime -> Trends -> Operations`, refresh **2 detik**, dan **Playlist** interval **10 detik** untuk first seed/reset terkontrol. Sesudah resource ada di Grafana, saved dashboard/playlist tidak ditimpa oleh startup RadMon.

## WhatsApp alarm

WhatsApp default OFF. Dispatcher hanya mengirim persisted policy event `kind=ALARM`, `status=ACTIVE`, dan belum mempunyai `notification_sent_at`. `SUPPRESSED`, responded event, retrigger-locked state, dan historical seed tidak dikirim sebagai alarm baru.

## Mode developer

Detector serial dan dummy hanya untuk development/source checkout:

```text
python -m radmon.dev_app --source detector
python -m radmon.dev_app --source dummy
```

## Verification vs commissioning

GitHub Actions memverifikasi Python tests, frontend TypeScript/Kumo build, compile validation, kontrak payload Grafana, Windows `RadMon.exe`, installer, dan packaged smoke test. Itu **bukan** pengganti commissioning nyata di PC `.2`; koneksi `.50/.52/.38`, Grafana native, alarm write-through, firewall/network BRIN, dan source hardware harus divalidasi sebelum penggunaan operasional penuh.
