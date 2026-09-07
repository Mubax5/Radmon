# Windows Runbook — Radmon DPFK Python

Dokumen ini adalah panduan menjalankan demo **Gedung 52 — IS-1 Koridor — SERID 5202** di Windows tanpa mencampur data dummy dan detector asli.

## Prinsip penting

Ada dua program yang dapat menulis measurement:

- `RUN_DETECTOR.bat` → data asli dari detector melalui `main.py`.
- `RUN_DUMMY.bat` → data simulasi ke tabel `measurement` setiap 2 detik.

**Jangan menjalankan RUN_DETECTOR.bat dan RUN_DUMMY.bat bersamaan.** Keduanya adalah measurement writer untuk station demo yang sama. Kalau dua-duanya hidup, data real dan dummy akan tercampur di database.

`START_COMMON.bat` sengaja hanya menyalakan komponen yang aman hidup bersamaan dan **tidak** menyalakan detector atau dummy.

## 1. Persiapan pertama kali

Pastikan:

1. Python 3.11+ terinstall.
2. MariaDB aktif dan database `ipradmon` tersedia.
3. Source Radmon sudah diekstrak ke folder lokal.

Double-click:

```text
SETUP_WINDOWS.bat
```

Script ini:

- membuat `.venv` bila belum ada;
- upgrade `pip`;
- install semua dependency dari `requirements.txt`;
- membuat `.env` dari `.env.example` bila `.env` belum ada;
- tidak menimpa `.env` yang sudah dikustomisasi.

Konfigurasi default demo:

```text
RADMON_SERIAL_PORT=COM15
RADMON_BAUDRATE=2400
RADMON_SERID=5202
RADMON_BUILDING=52
RADMON_ROOM=IS-1 Koridor
RADMON_LOCATION=Gd.52
RADMON_WARNLEVEL=8
RADMON_ALARMLEVEL=10
RADMON_SAMPLE_INTERVAL=2
```

## 2. Siapkan schema dan station demo

Jalankan migration:

```bat
mariadb -u root -p ipradmon < database\schema_extension.sql
```

Lalu registrasikan station demo:

```bat
.venv\Scripts\python.exe scripts\register_demo_station.py
```

Registration script bersifat untuk demo station 5202 dan harus dijalankan setelah database dapat diakses sesuai `.env`.

## 3. Jalankan komponen umum

Double-click:

```text
START_COMMON.bat
```

Script ini membuka window terpisah untuk:

- `RADMON CENTRAL` → central API;
- `RADMON PUBLIC` → monitoring fullscreen/public;
- `RADMON SYNC` → local-to-central sync agent;
- `RADMON ADMIN` → desktop admin PySide6.

Alamat default:

```text
Public monitoring : http://127.0.0.1:8080
Central API       : http://127.0.0.1:8090
```

`START_COMMON.bat` tidak memasukkan measurement writer. Setelah common services aktif, pilih **satu** mode berikut.

## 4A. Mode demo / dummy

Double-click:

```text
RUN_DUMMY.bat
```

Default runner:

```text
dummy_measurement.py --mode mixed --interval 2
```

Artinya station 5202 `IS-1 Koridor` mendapatkan measurement dummy setiap 2 detik.

Untuk mode tertentu dari Command Prompt:

```bat
RUN_DUMMY.bat --mode normal --interval 2
RUN_DUMMY.bat --mode alert --interval 2
RUN_DUMMY.bat --mode alarm --interval 2
RUN_DUMMY.bat --mode mixed --interval 2 --count 30
```

Sebelum menyalakan dummy, pastikan `RUN_DETECTOR.bat` tidak sedang aktif.

## 4B. Mode detector asli

Double-click:

```text
RUN_DETECTOR.bat
```

Runner ini hanya menjalankan:

```text
main.py
```

Serial configuration diambil dari `.env`; default proyek adalah `COM15`, `2400 baud`, 8N1, timeout 3 detik.

Sebelum menyalakan detector, pastikan `RUN_DUMMY.bat` tidak sedang aktif.

## 5. Admin-only workflow

Admin desktop memiliki halaman:

```text
Recent / Tabular / Chart / Reports / Alarm / Logs
```

Bagian ini bukan tampilan TV umum. Di sini operator/admin dapat melihat histori, chart, alarm, log, dan membuat recap report berdasarkan rentang waktu.

Report mendukung export CSV/PDF. PDF dapat dipakai untuk print dan dokumentasi monitoring periode tertentu.

## 6. Public monitoring

Tampilan umum berjalan dari `public_app.py` dan default dapat diakses di:

```text
http://127.0.0.1:8080
```

Untuk monitor/TV, buka URL tersebut di browser dan gunakan fullscreen/kiosk mode.

## 7. Central server dan sync

Central API default:

```text
http://127.0.0.1:8090
```

`sync_agent.py` membaca queue lokal dan mengirimkan data ke central API. Jika central server sementara tidak tersedia, local collector/database tetap dapat berjalan dan sync akan mencoba kembali pada iterasi berikutnya.

Untuk deployment multi-gedung, setiap server lokal memiliki collector + database sendiri, kemudian meneruskan measurement ke server pusat melalui mekanisme sync ini.

## 8. Stop seluruh window Radmon

Double-click:

```text
STOP_ALL.bat
```

Script hanya menargetkan window dengan title:

```text
RADMON CENTRAL
RADMON PUBLIC
RADMON SYNC
RADMON ADMIN
RADMON DETECTOR
RADMON DUMMY
```

Program Windows lain tidak ditargetkan.

## 9. Runner individual untuk debugging

Runner granular masih tersedia di `scripts\`:

```text
scripts\run_admin.bat
scripts\run_public.bat
scripts\run_sync.bat
scripts\run_central.bat
scripts\run_collector.bat
scripts\run_dummy.bat
```

Untuk penggunaan normal, lebih aman memakai BAT top-level karena pemisahan common services dan measurement writer lebih eksplisit.

## 10. Urutan demo tercepat

```text
1. SETUP_WINDOWS.bat
2. Pastikan MariaDB + ipradmon siap
3. Jalankan schema_extension.sql
4. Register station 5202
5. START_COMMON.bat
6. RUN_DUMMY.bat
7. Buka http://127.0.0.1:8080
8. Cek admin UI untuk Chart / Reports / Alarm / Logs
9. STOP_ALL.bat setelah selesai
```

Untuk pindah ke detector asli:

```text
1. STOP_ALL.bat
2. START_COMMON.bat
3. RUN_DETECTOR.bat
```

Jangan menjalankan writer dummy dan detector asli secara bersamaan.
