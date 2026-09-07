# Radiation Monitoring

Aplikasi operator Python dan monitoring Grafana untuk data `ipradmon`.

## Menjalankan sistem

Detector asli:

```text
RADMON.bat
```

Demo seluruh station/detector:

```text
RUN_DUMMY.bat
```

Acquisition, Admin, dan Grafana membaca data live setiap **2 detik**. Mode detector dan dummy tidak boleh dijalankan bersamaan pada komputer yang sama.

## Database

Aplikasi memakai schema yang sudah ada tanpa migration/tabel aplikasi tambahan:

```text
device
measurement
recent
alarm
applog
news
rawdata
```

Monitoring TV menggunakan **latest `measurement` sebagai sumber realtime tunggal** untuk nilai, waktu pengukuran, dan status. Ini mencegah kondisi ketika dose rate sudah tersedia tetapi panel lain menampilkan `No data` karena tabel cache berbeda.

`measurement.doserate` ditampilkan sebagai **µSv/h**. Admin Chart menggunakan `measurement.doserate` dan `measurement.dose` langsung dari database, tanpa integrasi ulang yang mengubah angka sumber.

Demo mencakup station/ruangan DPFK, termasuk `5202 / IS-1 Koridor`, dan stream dummy tiap 2 detik untuk seluruh katalog detector.

## Admin

Tab operator:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

Error polling ditampilkan melalui status UI dan log, bukan popup berulang.

### Chart

Visual yang tersedia:

- **Trend** — dose rate, optional Approx. Dose, zoom/pan/crosshair dan threshold.
- **Status Pie** — komposisi NORMAL / ALERT / ALARM.
- **Threshold Progress** — current / average / peak dibanding alarm threshold.

### Reports

1. pilih `From` dan `To`;
2. klik **Preview**;
3. cek report di aplikasi;
4. gunakan **Print**, **Export PDF**, atau **Export CSV**.

Hasil export disimpan otomatis pada:

```text
!REPORT!
```

## Grafana Monitoring TV

Tombol **Monitoring** pada Admin membuka playlist **RadMon TV** dengan tiga logical page:

```text
Page 1 Realtime -> 10 detik -> Page 2 Trends -> 10 detik -> Page 3 Operations -> 10 detik -> ulang
```

Yang berubah pada setiap putaran hanya panel **Kondisi Operasional Detector** di Page 3. Panel tersebut mempunyai 8 subpage detector. Urutannya:

```text
Putaran 1 -> Kondisi Operasional Detector 1/8
Putaran 2 -> Kondisi Operasional Detector 2/8
...
Putaran 8 -> Kondisi Operasional Detector 8/8
Putaran 9 -> kembali 1/8
```

Secara internal Grafana memprovision dua dashboard bersama (Realtime dan Trends) dan delapan varian Operations. Playlist menyusun ketiganya sebagai satu siklus tiga logical page sehingga operator tetap melihat urutan Page 1 -> Page 2 -> Page 3, sementara hanya isi tabel kondisi operasional yang berganti pada siklus berikutnya.

Semua logical page:

- refresh datasource setiap **2 detik**;
- memakai header template yang sama;
- dirancang untuk layar sekitar 1920x1080;
- dibuka dalam mode kiosk + auto-fit sehingga tidak perlu scroll atau menyentuh time picker/variable.

### Page 1 — Realtime

Menampilkan 15 station dalam grid satu layar. Setiap station mempunyai:

- kartu laju dosis **µSv/h**;
- mini trend terpisah di bawah angka agar tidak menutupi nilai utama;
- warna threshold per detector;
- waktu pengukuran kecil di bawah mini trend tanpa title tambahan.

Nilai dan waktu sama-sama diambil dari latest row tabel `measurement`.

### Page 2 — Trends

Menampilkan Dose Rate Monitoring tiga jam terakhir sebagai small-multiple per gedung supaya banyak seri tetap terbaca, plus summary:

- dose rate tertinggi saat ini;
- rata-rata saat ini;
- jumlah detector online;
- jumlah detector offline.

### Page 3 — Operations

Bagian yang tetap pada setiap putaran:

- Status Detector dalam donut/pie;
- jumlah NORMAL / ALERT / ALARM / OFFLINE;
- alarm terbaru 24 jam.

Bagian yang berubah setiap putaran playlist:

- **Kondisi Operasional Detector**, dibagi menjadi 8 subpage yang bersama-sama mencakup seluruh detector satu kali sebelum kembali ke subpage pertama.

Status dihitung dari latest `measurement`, threshold pada `device`, dan freshness `maxidlemin`; tidak bergantung pada tabel `recent`.

## Auto setup Grafana

Saat Monitoring dibuka, aplikasi:

1. mencari Grafana lokal yang sudah hidup;
2. membuat/update datasource `ipradmon-mysql`;
3. meng-import dashboard TV yang dibutuhkan oleh tiga logical page;
4. membuat/update playlist `RadMon TV` dengan interval 10 detik;
5. memverifikasi dashboard + playlist;
6. baru membuka URL playlist kiosk.

Jika Grafana lokal tidak tersedia, aplikasi mencoba executable Grafana native, lalu Docker sebagai fallback terakhir.

Konfigurasi penting:

```env
RADMON_GRAFANA_URL=http://localhost:3000
RADMON_GRAFANA_PORT=3300
RADMON_GRAFANA_USER=admin
RADMON_GRAFANA_PASSWORD=admin
RADMON_REPORT_DIR=!REPORT!
```

## Multi-detector

Satu detector:

```env
RADMON_SERID=5201
RADMON_SERIAL_PORT=COM15
```

Beberapa detector serial pada satu komputer:

```env
RADMON_DETECTORS=5201@COM15;5202@COM16;5701@COM18
```

## Server pusat

Sync ke server pusat default OFF. Sistem lokal tetap dapat melakukan acquisition, Admin, report, alarm, dan monitoring tanpa koneksi pusat.

```env
RADMON_SYNC_ENABLED=1
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-token
```

## Struktur repo

```text
RADMON.bat
RUN_DUMMY.bat
main.py
central_server.py
radmon/       source Python
grafana/      provisioning datasource + Docker fallback
tests/        regression tests
```

Output runtime (`!REPORT!`, logs, runtime, venv, cache) tidak ditrack Git.
