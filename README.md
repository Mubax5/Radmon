# Radmon DPFK — Python Backend, Admin Desktop, Public Monitoring

Project ini adalah versi Python-first untuk demo satu detector **Gedung 52 / IS-1 Koridor / SERID 5202**. Backend, collector, admin desktop, public monitoring, report, alarm, dummy generator, sinkronisasi lokal-ke-pusat, dan central API semuanya Python.

Source `reference/original_user_main.py` menyimpan script awal buatan user sebagai referensi. `main.py` baru tetap mempertahankan protokol detector yang sama tetapi memecah logic ke module yang bisa diuji, dan default station sudah diperbaiki ke **5202** untuk IS-1 Koridor.

## 1. Alur sistem

```text
DETECTOR (COM15, 2400 baud)
        │
        ▼
main.py / Python SerialCollector
        │
        ├────────► rawdata
        ├────────► measurement
        ├────────► radmon_alarm_event
        └────────► radmon_sync_queue
                     │
                     ▼
                  MariaDB lokal ipradmon
                     │
          ┌──────────┼────────────┐
          ▼          ▼            ▼
      Admin UI   Public Web   sync_agent.py
      PySide6    FastAPI          │ HTTPS
                                 ▼
                         central_server.py
                                 │
                                 ▼
                           DB server pusat
```

Setiap gedung/ruangan nantinya boleh mempunyai server lokal sendiri. Acquisition dan monitoring lokal tetap jalan saat link ke **server pusat** putus; queue dikirim lagi setelah koneksi kembali.

## 2. Demo yang sudah dikunci

```text
SERID       5202
Gedung      52
Room        IS-1 Koridor
Location    Gd.52
Alert       8 µSv/h
Alarm       10 µSv/h
Max idle    5 menit
Dummy       setiap 2 detik
Serial      COM15 / 2400 / 8N1 / timeout 3 detik
Database    ipradmon
```

## 3. Setup Windows

Dari PowerShell/CMD di folder project:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` sesuai MariaDB lokal. Default-nya sengaja cocok dengan mesin demo, tapi password database jangan ditaruh di source code.

## Windows launcher cepat

Untuk Windows, runner utama sekarang dipisahkan supaya **measurement dummy tidak pernah otomatis hidup bersamaan dengan detector asli**.

```text
SETUP_WINDOWS.bat   setup .venv + requirements + .env
START_COMMON.bat    central + public monitoring + sync + admin
RUN_DUMMY.bat       writer dummy 5202 setiap 2 detik
RUN_DETECTOR.bat    writer detector asli melalui main.py
STOP_ALL.bat        stop window Radmon yang dibuka launcher
```

Urutan demo:

```text
1. SETUP_WINDOWS.bat
2. Siapkan MariaDB / schema / station 5202
3. START_COMMON.bat
4. RUN_DUMMY.bat
```

Untuk mode detector asli, ganti langkah 4 dengan `RUN_DETECTOR.bat`.

> **Penting:** jangan menjalankan `RUN_DETECTOR.bat` dan `RUN_DUMMY.bat` bersamaan. Keduanya menulis measurement dan dapat mencampur data real dengan data simulasi.

Dokumentasi Windows lengkap: [`docs/WINDOWS_RUNBOOK.md`](docs/WINDOWS_RUNBOOK.md).

## 4. Siapkan database

Tabel lama `device`, `rawdata`, dan `measurement` diasumsikan sudah ada di database `ipradmon` seperti sistem lama.

Jalankan file additive berikut lewat MariaDB CLI / HeidiSQL:

```text
database/schema_extension.sql
```

File tersebut menambah:

```text
radmon_alarm_event
radmon_sync_queue
radmon_sync_receipt
```

Tidak ada `DROP TABLE` dan tidak menghapus data lama.

Daftarkan demo detector 5202:

```bat
python scripts/register_demo_station.py
```

Script ini meng-upsert `device` menjadi `IS-1 Koridor`, `Gd.52`, warnlevel 8, alarmlevel 10, maxidlemin 5.

## 5. Dummy generator — insert ke `measurement` tiap 2 detik

Mode normal:

```bat
python dummy_measurement.py --mode normal --interval 2
```

Mode alert:

```bat
python dummy_measurement.py --mode alert --interval 2
```

Mode alarm:

```bat
python dummy_measurement.py --mode alarm --interval 2
```

Mode campuran untuk demo:

```bat
python dummy_measurement.py --mode mixed --interval 2
```

Generate 20 row lalu berhenti:

```bat
python dummy_measurement.py --mode mixed --interval 2 --count 20 --seed 123
```

Tambahkan simulated raw line ke `rawdata`:

```bat
python dummy_measurement.py --mode normal --interval 2 --write-raw
```

Launcher Windows: `scripts\run_dummy.bat`.

## 6. Detector asli — `main.py`

Hubungkan detector ke COM15 lalu:

```bat
python main.py
```

Default serial sesuai source user:

```text
COM15
2400 baud
8 data bits
No parity
1 stop bit
3 s read timeout
```

Setiap line ASCII diparse dari tujuh karakter pertama, disimpan ke `rawdata` + `measurement`, `previnterval=2`, `stat=0`, dievaluasi alarm, dan dimasukkan ke sync queue.

Launcher: `scripts\run_collector.bat`.

## 7. Admin desktop Python

```bat
python admin_app.py
```

Workflow admin mengikuti konsep aplikasi Python lama:

**Recent / Tabular / Chart / Reports / Alarm / Logs**

- **Recent** — live dose, status, trend, last update, threshold, recent rows.
- **Tabular** — pilih From/To, limit, lihat measurement, export CSV.
- **Chart** — grafik Dose rate dan Approx. Dose serta garis Alert/Alarm.
- **Reports** — recap jangka waktu tertentu, first/last, min/average/max, samples, approximate dose, preview, **Export PDF**, buka PDF untuk print.
- **Alarm** — active/history event, value/threshold, acknowledgement operator + note.
- **Logs** — tail `logs/radmon.log`.

Launcher: `scripts\run_admin.bat`.

## 8. Public fullscreen monitoring

Ini yang ditampilkan di TV/browser/hosting, bukan admin UI:

```bat
python public_app.py --host 0.0.0.0 --port 8080
```

Buka:

```text
http://127.0.0.1:8080/
```

Untuk komputer lain pada LAN gunakan IP server lokal, misalnya:

```text
http://192.168.1.52:8080/
```

API polling:

```text
GET /api/latest
GET /health
```

Browser refresh data otomatis tiap 2 detik dan menampilkan `[5202] IS-1 Koridor (Gd. 52)`, current dose, trend, status, timestamp, Alert 8 µSv/h, Alarm 10 µSv/h. Halaman public tidak punya Reports, Alarm acknowledgement, database setting, atau fungsi admin.

Launcher: `scripts\run_public.bat`.

## 9. Report jangka waktu tertentu

Di Admin → Reports pilih From/To → Preview recap → **Export PDF**. PDF memuat:

- station/gedung/ID;
- periode;
- threshold;
- first dan last measurement;
- min / average / max;
- jumlah sample;
- approximate cumulative dose (integrasi trapezoid);
- measurement table;
- alarm history dan acknowledgement.

Tabular juga dapat export CSV.

## 10. Alarm

Logic status shared untuk UI public/admin:

```text
OFFLINE  tidak ada data / lebih tua dari maxidlemin
ALARM    dose >= alarmlevel
ALERT    warnlevel <= dose < alarmlevel
NORMAL   dose < warnlevel
```

`AlarmService` menyimpan transition, bukan row alarm baru tiap 2 detik. Continuous alert/alarm hanya meng-update event. Recovery menutup event aktif. Admin dapat acknowledgement dengan nama operator dan note.

## 11. Sinkronisasi server lokal → server pusat

Pada server pusat siapkan Python environment + database, jalankan `database/schema_extension.sql`. Untuk demo station 5202, jalankan juga `python scripts/register_demo_station.py` pada database pusat, lalu:

```bat
python central_server.py --host 0.0.0.0 --port 8090
```

Pada `.env` server lokal:

```dotenv
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-dengan-token-rahasia
```

Token yang sama dipakai di `.env` central server. Jalankan lokal:

```bat
python sync_agent.py --interval 2
```

Atau kirim satu batch lalu exit:

```bat
python sync_agent.py --once
```

`radmon_sync_queue` menyimpan measurement yang belum terkirim. Kalau internet/LAN pusat mati, acquisition lokal tetap jalan. Sync memakai `sample_key` + `radmon_sync_receipt` sehingga retry tidak menduplikasi measurement pusat.

Central API:

```text
POST /api/v1/measurements/batch
GET  /api/v1/stations
GET  /api/v1/latest/{serid}
GET  /health
```

Launcher: `scripts\run_sync.bat` dan `scripts\run_central.bat`.

## 12. Struktur project

```text
main.py                       collector detector asli
dummy_measurement.py          dummy measurement 2 detik
admin_app.py                  PySide6 admin desktop
public_app.py                 FastAPI fullscreen public monitoring
sync_agent.py                 uploader local → pusat
central_server.py             FastAPI central ingest
radmon/                       domain/backend/service modules
radmon/admin/                 Recent/Tabular/Chart/Reports/Alarm/Logs
database/schema_extension.sql alarm + queue + receipt
monitoring/                   template/CSS/JS public fullscreen
scripts/                      registration, launchers, smoke
reference/original_user_main.py
```

## 13. Offline smoke test

Tanpa detector, MariaDB, dan GUI display:

```bat
python scripts/smoke_demo.py
python -m pytest -q
```

Smoke test memeriksa dummy generator, public API, HTML public, CSV, dan PDF.

## 14. Urutan demo yang paling gampang

Terminal 1:

```bat
python dummy_measurement.py --mode mixed --interval 2
```

Terminal 2:

```bat
python public_app.py
```

Terminal 3:

```bat
python admin_app.py
```

Buka `http://127.0.0.1:8080` untuk public monitoring. Gunakan admin desktop untuk chart/recap/report/alarm/log.

## 15. Catatan production

- Jangan jalankan collector asli dan dummy untuk SERID 5202 secara bersamaan pada database production.
- Password MariaDB dan central token wajib diganti.
- Gunakan TLS/reverse proxy/VPN untuk central API lintas gedung.
- Batasi public monitor ke endpoint read-only.
- Backup database sebelum schema extension.
- Alarm software/network monitoring bukan pengganti interlock proteksi radiasi hardware yang fail-safe.
