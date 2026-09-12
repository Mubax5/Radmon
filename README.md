# Radiation Monitoring

RadMon adalah sistem monitoring radiasi untuk central PC `192.168.1.2`. Build production Windows dijalankan dari **`app\RadMon.exe`**; satu executable tersebut menjadi lifecycle owner untuk collector LAN, secure API, desktop Admin, alarm policy, archive lifecycle, dan bootstrap Grafana. Saat desktop Admin ditutup, central service yang dimiliki proses yang sama ikut dihentikan.

## Paket production Windows

Artifact `RadMon-Windows` mempunyai layout portable:

```text
RadMon\
  app\
    RadMon.exe
    docs\manual\
    grafana\
  config\
    .env.example
    .env
  runtime\
  archives\
  reports\
  README.md
  SHA256SUMS.txt
```

`runtime`, `archives`, `reports`, dan `config\.env` adalah data instalasi lokal dan **tidak boleh dihapus saat upgrade**. Paket build tidak pernah membawa credential production.

### First run

1. Extract artifact ke folder tetap, misalnya `C:\RadMon`.
2. Pastikan Docker Desktop tersedia bila Grafana lokal akan dipakai.
3. Copy `config\.env.example` menjadi `config\.env`, lalu isi credential database lokal/LAN.
4. Double-click `app\RadMon.exe`.
5. Pada first run, buat Administrator awal bila security store belum memiliki user.

Deployment lama yang masih mempunyai `.env` di root instalasi dimigrasikan aman: RadMon hanya **menyalin** root `.env` ke `config\.env` bila target belum ada. File lama tidak dihapus dan `config\.env` yang sudah ada tidak pernah ditimpa.

### Upgrade

Tutup RadMon, backup folder instalasi, lalu ganti file aplikasi dari artifact baru. Pertahankan:

```text
config\.env
runtime\
archives\
reports\
```

Sesudah update, jalankan lagi `app\RadMon.exe`. Jangan mengganti `source_id` production karena checkpoint dan state menggunakan identity tersebut.

## Mode developer

Detector serial dan dummy tidak menjadi launcher production. Untuk pengembangan dari source checkout:

```text
python -m radmon.dev_app --source detector
python -m radmon.dev_app --source dummy
```

Dataset demo tetap mencakup detector contoh **5202 / IS-1 Koridor** agar workflow multi-station bisa diuji tanpa hardware production.

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

`measurement` menyimpan history untuk Chart, Reports, export, dan archive. `recent` adalah snapshot operasional satu row per detector. `vrecent` adalah sumber authoritative monitoring realtime. `alarm` mengikuti schema legacy production `serid + dtoa` dengan `lvl`, `mvalue`, `thvalue`, `nhit`, `ack`, `pic`, `note`, `i_op`, dan `i_flag`.

**RadMon tidak melakukan DDL pada database source production.** State policy/suppression, audit, checkpoint, retry metadata, dan security disimpan di central/runtime storage.

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
RADMON_LAN_BATCH_SIZE=1000
RADMON_REFRESH_INTERVAL=2
```

Credential production tidak disimpan di Git. Realtime worker per source berjalan default setiap **2 detik**. History backfill berjalan terpisah dengan checkpoint `source_id + production SERID`, sehingga kegagalan satu source tidak menghentikan source lain dan history central yang sudah tersimpan tidak dihapus.

## Alarm Policy dan control

Operator-facing alarm dikendalikan policy restart-safe di central storage; raw source alarm tetap menjadi evidence. Burst HIGH dapat surface maksimum tiga ALARM dalam window lima menit yang di-anchor ke ALARM #1. ALARM #3 mengaktifkan `RETRIGGER_LOCKED`, dan hanya kondisi `NORMAL` (`dose < LOW/WARN`) yang mereset counter/lock. `ALERT` tidak mereset episode.

Administrator/Operator dapat melakukan Response/Silence dan timed suppression 1 menit sampai 24 jam. Source write-through memakai kontrak legacy:

```sql
UPDATE alarm
SET i_op = ?, pic = ?, note = ?, i_flag = 1
WHERE serid = ? AND dtoa = ? AND i_flag = 0
```

Kolom `ack` dipertahankan. Jika source sedang gagal, silence/response diretry dengan backoff `5s, 15s, 30s, 60s` dan maksimum 25 pending row per live cycle.

## Admin realtime

Desktop Admin mempunyai tab:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

`Recent` membaca `vrecent`. `Alarm` menampilkan policy event beserta underlying dose condition. Panel Message menampilkan source health, active operator-facing ALARM, serta suppression/retrigger-lock tanpa mengubah `SUPPRESSED` menjadi audible alarm baru.

Role utama:

- **Administrator** — monitoring, response/suppression, user management, edit station, archive admin.
- **Operator** — monitoring/report, response, dan suppression.
- **Viewer** — read-only.

Security store default berada di `runtime/radmon-security.db`.

## Grafana Monitoring TV

Tombol **Monitoring** membuka Grafana Playlist `Realtime -> Trends -> Operations`. Generator menghasilkan dashboard TV dengan refresh **2 detik** dan perpindahan Playlist **10 detik**. Page realtime/status membaca `vrecent`; history trend membaca `measurement`. Status operasional membedakan `OFFLINE`, `SUPPRESSED`, `ALARM`, `ALERT`, dan `NORMAL`, sementara dose aktual tetap terlihat saat suppression aktif.

## Reports dan quarterly archive

Reports mendukung workflow **Preview -> Print / Export PDF / Export CSV**. Quarter lama dapat dipindah ke archive terverifikasi melalui lifecycle `PENDING_DRAIN -> EXPORTING -> VERIFYING -> SEALED -> PURGING -> COMPLETE`. Source production tidak pernah dipurge oleh archive service. Retensi minimum default 5 tahun dan report archive dapat dibaca tanpa restore SQL.

## WhatsApp alarm

WhatsApp disabled by default. Dispatcher hanya mengirim persisted policy event `kind=ALARM`, `status=ACTIVE`, dan belum mempunyai `notification_sent_at`. `SUPPRESSED`, responded event, retrigger-locked state, dan historical seed tidak dikirim sebagai alarm baru.

## Existing push sync / server pusat

Mekanisme push SyncAgent ke server pusat tetap tersedia dan default OFF melalui `RADMON_SYNC_ENABLED`. Mekanisme ini terpisah dari direct LAN pull PC `.2`.

## Struktur source utama

```text
RadMon.spec
packaging/
radmon/
grafana/
docs/
tests/
.github/workflows/
```

Tidak ada batch launcher atau root Python launcher untuk production. Build production dibuat oleh GitHub Actions Windows dan menghasilkan artifact `RadMon-Windows`.

## Verification vs commissioning

GitHub Actions memverifikasi unit/integration tests, Python compile, kontrak payload Grafana, build Windows `RadMon.exe`, dan packaged smoke test. Itu **bukan** pengganti commissioning LAN/hardware nyata di PC `.2`; koneksi ke `.50/.52/.38`, device lapangan, alarm write-through, dan service Grafana tetap harus divalidasi di environment production sebelum release operasional penuh.
