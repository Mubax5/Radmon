# Installation Guide

## Production Windows

Production RadMon didistribusikan sebagai artifact portable **`RadMon-Windows`**. PC production tidak perlu memasang Python untuk menjalankan aplikasi; runtime Python sudah dibundle oleh PyInstaller.

Struktur paket:

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
```

### Persiapan central PC `.2`

1. Extract artifact ke folder tetap, misalnya `C:\RadMon`.
2. Install/aktifkan Docker Desktop bila Grafana lokal dipakai.
3. Copy `config\.env.example` menjadi `config\.env`.
4. Isi koneksi central MariaDB dan tiga source production:

```env
RADMON_CENTRAL_HOST=192.168.1.2
RADMON_DB_HOST=localhost
RADMON_DB_NAME=ipradmon
RADMON_LAN_ENABLED=1
RADMON_LAN_SOURCES=gd50@192.168.1.50;gd52@192.168.1.52;gd38@192.168.1.38
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=ISI_USER_PRODUCTION
RADMON_LAN_DB_PASSWORD=ISI_PASSWORD_PRODUCTION
RADMON_LAN_DB_NAME=ipradmon
RADMON_LAN_POLL_INTERVAL=2
RADMON_BACKFILL_ENABLED=1
RADMON_BACKFILL_BATCH_SIZE=500
RADMON_BACKFILL_INTERVAL=2
```

5. Double-click `app\RadMon.exe`.

`RadMon.exe` menjalankan central LAN collector/API, desktop Admin, archive lifecycle, alarm policy, dan bootstrap Grafana di bawah satu lifecycle owner. Ketika desktop Admin ditutup, central service milik proses itu ikut dihentikan.

## Migrasi dari instalasi lama

Jika folder instalasi lama masih mempunyai `.env` di root dan `config\.env` belum ada, first run menyalin `.env` lama ke `config\.env`. File lama tetap dibiarkan di tempatnya. Jika `config\.env` sudah ada, RadMon tidak pernah menimpanya.

Jangan hapus data berikut ketika upgrade:

```text
config\.env
runtime\
archives\
reports\
```

Security DB default berada di `runtime\radmon-security.db`. Arsip, log, report, checkpoint, audit, dan WhatsApp profile adalah data runtime lokal dan bukan bagian dari artifact aplikasi baru.

## Upgrade

1. Tutup RadMon.
2. Backup folder instalasi.
3. Pertahankan `config\.env`, `runtime`, `archives`, dan `reports`.
4. Ganti isi `app\` dan file paket non-runtime dengan versi artifact baru.
5. Jalankan `app\RadMon.exe`.
6. Verifikasi source health, Grafana, alarm response/suppression, dan report.

Jangan mengganti label `gd50`, `gd52`, atau `gd38`; checkpoint dan policy state menggunakan `source_id` tersebut.

## Mode developer

Detector serial dan dummy hanya untuk development/source checkout:

```text
python -m radmon.dev_app --source detector
python -m radmon.dev_app --source dummy
```

Mode developer membutuhkan Python/dependency dari `requirements.txt`; ini bukan jalur startup production.

## Commissioning wajib

CI dan smoke-test EXE memastikan bundle dapat dibuild/start tanpa menyentuh database production. Sebelum release operasional, lakukan commissioning di central PC `.2` untuk memastikan:

- konektivitas ke `192.168.1.50`, `.52`, dan `.38`;
- central MariaDB `ipradmon`;
- Grafana/Docker Desktop;
- response/silence source `i_flag=1` tanpa mengubah `ack`;
- source health/recovery;
- archive/report path dan permission.

RadMon tidak melakukan DDL pada source MariaDB production.
