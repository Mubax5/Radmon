# Radiation Monitoring

Aplikasi operator Python + monitoring Grafana untuk data `ipradmon`.

## Jalankan

Detector asli:

```text
RADMON.bat
```

Demo seluruh station/detector:

```text
RUN_DUMMY.bat
```

Kedua mode memakai interval acquisition dan refresh **2 detik**. Jangan menjalankan detector dan dummy pada komputer yang sama secara bersamaan.

## Database

Aplikasi memakai schema yang sudah ada, tanpa tabel aplikasi tambahan:

```text
device
measurement
recent
alarm
applog
news
rawdata
```

`measurement.doserate` ditampilkan sebagai laju dosis `µSv/h`. Nilai `measurement.dose` ditampilkan sebagai Approx. Dose `µSv` apa adanya; chart tidak menghitung ulang nilai dose dari histori sehingga skala yang terlihat tetap sesuai data database.

Station yang belum ada di tabel `device` dapat di-seed dari katalog internal tanpa menimpa row existing. Demo mencakup station/ruangan DPFK, termasuk `5202 / IS-1 Koridor`.

## Admin

Tab utama:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

Semua tab live membaca data setiap 2 detik. Error polling ditampilkan melalui status UI, bukan popup berulang.

### Chart

Pada tab Chart pilih visual melalui dropdown **View**:

- **Trend** — dose rate + Approx. Dose, zoom, pan, crosshair, threshold Alert/Alarm, From/To, Live, Reset View.
- **Dose Rate Distribution** — histogram distribusi pembacaan `doserate` pada range aktif.
- **Status Distribution** — jumlah sample NORMAL / ALERT / ALARM berdasarkan threshold station yang dipilih.

Trend memakai nilai `measurement.doserate` dan `measurement.dose` langsung dari database. Tidak ada normalisasi atau integrasi ulang yang mengubah angka sumber.

### Reports

Workflow report:

1. pilih `From` dan `To`;
2. klik **Preview**;
3. cek isi report di aplikasi;
4. gunakan **Print**, **Export PDF**, atau Export CSV.

Preview tidak dibangun ulang setiap refresh 2 detik. Summary tetap menghitung seluruh range, sedangkan detail preview dibatasi agar UI responsif.

Semua file hasil export otomatis disimpan di:

```text
!REPORT!
```

Folder dibuat otomatis saat export. Lokasi dapat diganti dengan `RADMON_REPORT_DIR`.

## Grafana Monitoring

Tombol **Monitoring** di Admin menyiapkan dan membuka dashboard Grafana RadMon secara otomatis.

Urutan setup:

1. cek Grafana yang sudah berjalan pada URL `RADMON_GRAFANA_URL` (default `http://localhost:3000`);
2. jika Grafana hidup tetapi dashboard RadMon belum ada, aplikasi mencoba membuat datasource MySQL `ipradmon-mysql` dan meng-import dashboard melalui Grafana HTTP API;
3. jika Grafana lokal tidak tersedia/tidak dapat diprovision, aplikasi mencoba bundled Grafana melalui Docker pada port fallback `3300`;
4. browser hanya dibuka setelah dashboard UID `radmon-radiation-monitoring` terverifikasi.

Dashboard membaca `device`, `measurement`, `recent`, dan `alarm`, refresh **2 detik**, dan menampilkan satuan **µSv/h**.

Konfigurasi penting:

```env
RADMON_GRAFANA_URL=http://localhost:3000/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv
RADMON_GRAFANA_PORT=3300
RADMON_GRAFANA_USER=admin
RADMON_GRAFANA_PASSWORD=admin
RADMON_REPORT_DIR=!REPORT!
```

Jika Grafana lokal memakai user/password berbeda, sesuaikan `RADMON_GRAFANA_USER` dan `RADMON_GRAFANA_PASSWORD` di `.env` agar auto-import dapat dilakukan.

## Multi-detector

Satu detector tetap dapat memakai:

```env
RADMON_SERID=5201
RADMON_SERIAL_PORT=COM15
```

Untuk beberapa detector serial pada satu komputer:

```env
RADMON_DETECTORS=5201@COM15;5202@COM16;5701@COM18
```

Mode dummy membuat stream independen untuk seluruh station aktif setiap 2 detik sehingga chart, alarm, report, dan Grafana dapat diuji sebagai sistem multi-detector.

## Server pusat

Sync ke server pusat default OFF. Sistem lokal tetap dapat melakukan acquisition, Admin, report, alarm, dan monitoring tanpa koneksi pusat.

Aktifkan hanya saat endpoint pusat tersedia:

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
grafana/      dashboard + provisioning
tests/        regression tests
```

Asset icon UI yang memang digunakan aplikasi berada di `radmon/admin/icons/silk/` bersama lisensinya. Output runtime (`!REPORT!`, logs, runtime, venv, cache) tidak ditrack Git.
