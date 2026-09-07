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

Demo dummy Gedung 52 / IS-1 Koridor / SERID 5202:

```text
RUN_DUMMY.bat
```

Hanya satu mode acquisition yang boleh berjalan pada satu komputer. Aplikasi memakai single-instance lock supaya detector dan dummy tidak menulis `measurement` secara bersamaan.

Pada first run, launcher membuat `.venv`, meng-install dependency, dan membuat `.env` dari `.env.example`. Aplikasi utama dijalankan melalui `pythonw.exe`, sehingga tidak membuka console tambahan untuk tiap service.

Jika Docker Desktop tersedia dan sedang aktif, launcher juga mencoba menyalakan Grafana secara background dengan `docker compose up -d`. Jika Docker tidak tersedia, Python Admin tetap dapat dipakai dan Grafana dapat dijalankan dari instalasi terpisah.

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

Saat start, aplikasi memvalidasi tabel/kolom yang dibutuhkan. Acquisition menyimpan measurement dan memperbarui `recent` pada transaksi yang sama. Detector asli juga dapat menyimpan raw line ke `rawdata`.

Mode dummy menggunakan:

```text
SERID       5202
Name        IS-1 Koridor
Location    Gd.52
Alert       8 uSv/h
Alarm       10 uSv/h
Interval    2 detik
```

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

Preview berisi:

- header instalasi;
- Summary;
- first/last measurement;
- dose rate Average/Max;
- tabel `Dose rate and Approx. Dose` untuk range yang dipilih.

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

Dashboard menyediakan:

- Notifikasi Laju Dosis;
- current dose rate card + sparkline per station;
- Waktu pengukuran per station;
- main Dose Rate Monitoring time-series;
- station selector;
- histori alarm terakhir;
- refresh 2 detik.

Semua query dashboard memakai tabel existing `device`, `measurement`, `recent`, dan `alarm`.

Tombol **Monitoring** pada Python Admin membuka URL Grafana dari:

```env
RADMON_GRAFANA_URL=http://localhost:3000/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv
```

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

Sync membaca `measurement` berdasarkan checkpoint lokal. Jika koneksi gagal, checkpoint tidak maju dan data dicoba kembali. Database pusat memakai schema yang sama.

Server pusat:

```bash
python central_server.py --host 0.0.0.0 --port 8090
```

## Konfigurasi utama

```env
RADMON_SERIAL_PORT=COM15
RADMON_DB_HOST=localhost
RADMON_DB_PORT=3306
RADMON_DB_USER=root
RADMON_DB_PASSWORD=
RADMON_DB_NAME=ipradmon
RADMON_REFRESH_INTERVAL=2
RADMON_GRAFANA_DB_HOST=host.docker.internal
RADMON_SYNC_ENABLED=0
```

Gunakan user database dengan privilege minimum yang diperlukan dan jangan menjalankan detector/dummy bersamaan.
