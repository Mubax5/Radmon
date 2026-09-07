# Radiation Monitoring

Sistem terdiri dari dua bagian utama:

- **Python Admin** untuk operator: Recent, Tabular, Chart, Reports, Alarm, Logs, acquisition detector/dummy, dan optional sync ke server pusat.
- **Grafana Monitoring** untuk layar monitoring umum/TV/kiosk.

Semua pembacaan dan refresh live memakai interval **2 detik**.

## Jalankan

Detector asli:

```text
RADMON.bat
```

Demo dummy seluruh station/detector room:

```text
RUN_DUMMY.bat
```

Hanya satu mode acquisition yang boleh berjalan pada satu komputer. Aplikasi memakai single-instance lock supaya detector dan dummy tidak menulis `measurement` secara bersamaan.

Pada first run, launcher membuat `.venv`, meng-install dependency, membuat `.env` dari `.env.example`, dan mencoba menyalakan Grafana RadMon melalui Docker Desktop. Aplikasi utama dijalankan melalui `pythonw.exe`, sehingga tidak membuka console tambahan untuk tiap service.

Bundled Grafana memakai port **3300** agar tidak bertabrakan dengan instalasi Grafana lain yang sudah memakai port 3000. Tombol **Monitoring** di Admin tidak sekadar membuka URL: aplikasi memverifikasi dashboard UID RadMon terlebih dahulu dan mencoba auto-setup Docker bila dashboard belum tersedia.

## Database

Aplikasi memakai schema `ipradmon` yang sudah ada. Tidak ada tabel aplikasi tambahan dan tidak ada migration schema otomatis.

Tabel yang dipakai:

```text
device
measurement
recent
alarm
applog
news
rawdata
```

Saat start, aplikasi memvalidasi tabel/kolom yang dibutuhkan lalu menambahkan metadata station yang belum ada dengan `INSERT IGNORE`. Row `device` yang sudah ada tidak ditimpa. Acquisition menyimpan measurement dan memperbarui `recent` pada transaksi yang sama. Detector asli juga dapat menyimpan raw line ke `rawdata`.

## Station dan detector room

Python Admin menampilkan struktur tree:

```text
Station
├─ Resin Penukar Ion
├─ R. Evaporasi
├─ R. Kompaksi
├─ R. Insenerasi
├─ R. Sementasi
├─ R. Kolam
├─ R. Purifikasi
├─ R. Pintu Masuk Kanal
├─ R. Kanal Masuk
├─ R. Kanal Utama
├─ IS-1
├─ IS-1 Koridor
├─ PSLAT
├─ IS-2
└─ IS-2 LBN
```

Catalog detector yang dipakai sebagai fallback/seed:

| SERID | Name | Location | Alert | Alarm |
| ---: | --- | --- | ---: | ---: |
| 3000 | Resin Penukar Ion | Gd.50 | 100 µSv/h | 150 µSv/h |
| 3001 | R. Evaporasi | Gd.50 | 8 µSv/h | 10 µSv/h |
| 3002 | R. Kompaksi | Gd.50 | 8 µSv/h | 10 µSv/h |
| 3004 | R. Insenerasi | Gd.50 | 8 µSv/h | 10 µSv/h |
| 3009 | R. Sementasi | Gd.50 | 8 µSv/h | 10 µSv/h |
| 3801 | R. Kolam | Gd.38 | 8 µSv/h | 10 µSv/h |
| 3802 | R. Purifikasi | Gd.38 | 8 µSv/h | 10 µSv/h |
| 3803 | R. Pintu Masuk Kanal | Gd.38 | 8 µSv/h | 10 µSv/h |
| 3804 | R. Kanal Masuk | Gd.38 | 8 µSv/h | 10 µSv/h |
| 3805 | R. Kanal Utama | Gd.38 | 8 µSv/h | 10 µSv/h |
| 5201 | IS-1 | Gd.52 | 23 µSv/h | 25 µSv/h |
| 5202 | IS-1 Koridor | Gd.52 | 8 µSv/h | 10 µSv/h |
| 5601 | PSLAT | Gd.55 | 23 µSv/h | 25 µSv/h |
| 5701 | IS-2 | Gd.57 | 8 µSv/h | 10 µSv/h |
| 5702 | IS-2 LBN | Gd.57 | 8 µSv/h | 10 µSv/h |

Jika database memiliki station tambahan, Admin dan Grafana tetap membacanya dari tabel `device`.

## Dummy fleet

`RUN_DUMMY.bat` bukan lagi hanya mensimulasikan satu detector. Runtime membuat generator independen untuk **seluruh station** dan menulis satu sample per detector setiap 2 detik. Setiap station mempunyai generator dan evaluasi alarm sendiri, sehingga Admin/Grafana dapat diuji sebagai sistem multi-detector.

Station yang dipilih pertama kali di Admin pada mode dummy tetap `5202 / IS-1 Koridor`, tetapi seluruh 15 detector tetap menghasilkan data.

## Detector asli dan multi-COM

Konfigurasi lama satu detector tetap didukung:

```env
RADMON_SERID=5201
RADMON_SERIAL_PORT=COM15
RADMON_DETECTORS=
```

Untuk beberapa detector serial pada satu komputer, isi `RADMON_DETECTORS` dengan format `SERID@PORT` dipisahkan titik koma:

```env
RADMON_DETECTORS=5201@COM15;5202@COM16;5701@COM18
```

Runtime membuat collector dan AlarmService terpisah untuk setiap binding. Jika `RADMON_DETECTORS` kosong, aplikasi otomatis kembali ke `RADMON_SERID` + `RADMON_SERIAL_PORT` seperti sebelumnya.

## Python Admin

Tampilan admin mengikuti workflow aplikasi operator:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

Menu utama:

```text
File | View | Tools | Help
```

Toolbar dan tab memakai icon **FamFamFam Silk** 16x16, bukan emoji. Icon yang dibundel berada di `radmon/admin/icons/silk/`; attribution/lisensi ada pada folder yang sama.

Background refresh hanya me-refresh tab yang sedang aktif setiap 2 detik. Error polling tampil di status bar, bukan popup berulang.

### Chart

Chart memakai PyQtGraph dan mendukung:

- wheel zoom;
- drag/pan;
- crosshair;
- tooltip waktu, dose rate, dan Approx. Dose;
- left axis Dose rate `[µSv/h]`;
- right axis Approx. Dose `[µSv]`;
- garis Alert dan Alarm;
- range From/To;
- Live follow;
- Apply range dan Reset view.

Saat operator melakukan zoom/pan dengan Live OFF, refresh 2 detik tidak mengembalikan viewport ke posisi awal.

### Reports

Workflow report adalah **preview-first**:

1. pilih `From` dan `To`;
2. klik **Preview**;
3. aplikasi menampilkan report langsung di tab Reports;
4. setelah preview berhasil, **Print** dan **Export PDF** baru aktif.

Perbaikan performa dan layout:

- global refresh 2 detik **tidak lagi membangun ulang report**;
- opsi `Live` hanya memperbarui nilai `To`, sehingga tidak melakukan query + relayout HTML terus-menerus;
- preview detail dibatasi **250 row** supaya UI tetap responsif;
- Summary tetap dihitung dari **seluruh range** melalui SQL aggregate, bukan dari 250 row preview;
- tabel Summary dan `Dose rate and Approx. Dose` memakai lebar **100%**, center, dan margin dokumen minimum;
- satuan operator menggunakan `µSv/h` dan `µSv`.

Print dan Export PDF memakai `QTextDocument` yang sama dengan preview sehingga layout yang dilihat operator menjadi sumber dokumen cetak. CSV tetap tersedia untuk data mentah.

## Grafana Monitoring

Monitoring umum tidak dijalankan oleh FastAPI/Python. Grafana membaca schema `ipradmon` langsung.

Dashboard tersedia di:

```text
grafana/dashboards/radiation-monitoring.json
```

Provisioning:

```text
grafana/provisioning/datasources/ipradmon.yaml
grafana/provisioning/dashboards/radmon.yaml
```

Bundled Grafana default:

```text
http://localhost:3300
```

Dashboard menyediakan:

- header `REAL TIME DOSE RATE MONITORING SYSTEM`;
- current status + histori alarm terakhir;
- repeated Laju dosis card + sparkline per station;
- Waktu pengukuran per station;
- main `Dose Rate Monitoring` time-series;
- station selector dengan pilihan All;
- satuan `µSv/h`;
- refresh 2 detik.

Semua query dashboard memakai tabel existing `device`, `measurement`, `recent`, dan `alarm`.

Tombol **Monitoring** pada Python Admin menggunakan bootstrap/verifikasi dashboard. URL default:

```env
RADMON_GRAFANA_URL=http://localhost:3300/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv
RADMON_GRAFANA_PORT=3300
```

Jika endpoint yang dikonfigurasi tidak memiliki dashboard UID `radmon-radiation-monitoring`, Admin mencoba menyalakan bundled Grafana melalui Docker Compose lalu menunggu dashboard provisioning terverifikasi sebelum membukanya.

### Menjalankan Grafana manual

Dari root project:

```bash
docker compose --env-file .env -f grafana/docker-compose.yml up -d
```

Untuk database MariaDB yang berada pada host Windows, default datasource container menggunakan:

```env
RADMON_GRAFANA_DB_HOST=host.docker.internal
```

Jika database berada di server lain, ubah ke IP/hostname database tersebut. MariaDB harus menerima koneksi dari host Grafana dan user datasource sebaiknya hanya memiliki privilege `SELECT`.

Jika sudah memiliki instalasi Grafana sendiri, import dashboard JSON dan buat datasource MySQL dengan UID:

```text
ipradmon-mysql
```

## Alarm

Alarm memakai tabel existing:

```text
alarm(alarmid, serid, dtom, type, msg)
```

Python menyimpan transisi `ALERT`, `ALARM`, dan `RECOVERY`. Tab Alarm dan Grafana membaca histori dari tabel yang sama.

## Server pusat

Sync lokal default OFF. Sistem lokal tetap berjalan tanpa server pusat.

Aktifkan saat endpoint pusat sudah siap:

```env
RADMON_SYNC_ENABLED=1
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-token-kuat
```

Sync membaca `measurement` berdasarkan checkpoint lokal. Jika koneksi gagal, checkpoint tidak maju dan data dicoba kembali. Untuk runtime multi-detector/dummy fleet, sync worker dibuat per station aktif. Database pusat memakai schema yang sama.

Server pusat:

```bash
python central_server.py --host 0.0.0.0 --port 8090
```

## Konfigurasi utama

```env
RADMON_SERIAL_PORT=COM15
RADMON_DETECTORS=
RADMON_DB_HOST=localhost
RADMON_DB_PORT=3306
RADMON_DB_USER=root
RADMON_DB_PASSWORD=
RADMON_DB_NAME=ipradmon
RADMON_REFRESH_INTERVAL=2
RADMON_GRAFANA_PORT=3300
RADMON_GRAFANA_DB_HOST=host.docker.internal
RADMON_SYNC_ENABLED=0
```

Gunakan user database dengan privilege minimum yang diperlukan dan jangan menjalankan detector/dummy bersamaan.
