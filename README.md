# Radiation Monitoring

Sistem monitoring radiasi lokal memakai Python untuk akuisisi detector, database MariaDB, admin desktop, monitoring fullscreen, report, alarm, dan sinkronisasi opsional ke server pusat.

## Jalankan

Untuk detector asli, double-click:

```text
RADMON.bat
```

Untuk demo dummy Gedung 52 / IS-1 Koridor / SERID 5202, double-click:

```text
RUN_DUMMY.bat
```

Hanya satu mode yang bisa berjalan pada satu komputer. Kalau mode detector sedang aktif, mode dummy akan ditolak, dan sebaliknya. Tidak ada `STOP_ALL.bat`; tutup aplikasi admin untuk menghentikan seluruh proses lokal milik aplikasi secara bersih.

Pada first run, launcher membuat `.venv`, meng-install dependency, dan membuat `.env` dari `.env.example` bila belum ada. Setelah itu launcher memakai `pythonw.exe`, sehingga tidak ada kumpulan jendela console untuk admin, public monitor, dan sync.

## Database

Aplikasi memakai schema `ipradmon` yang sudah ada. Tidak ada tabel tambahan `radmon_*` dan tidak ada migration schema aplikasi.

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

Saat start, aplikasi memvalidasi tabel dan kolom tersebut. Jika schema tidak sesuai, aplikasi berhenti dengan satu pesan yang jelas dan tidak melakukan perubahan schema otomatis.

Detector asli default mengikuti data lokal:

```text
SERID       5201
Name        R. Lab Iradiasi
Location    Gedung 52
Alert       8 uSv/h
Alarm       10 uSv/h
Serial      COM15
Baudrate    2400
```

Mode dummy membuat/memperbarui row `device` untuk:

```text
SERID       5202
Name        IS-1 Koridor
Location    Gd.52
Alert       8 uSv/h
Alarm       10 uSv/h
Interval    2 detik
```

## Alur data lokal

```text
Detector / Dummy
       ↓
Python acquisition
       ↓
measurement + recent
       ├── Admin desktop
       ├── Fullscreen monitoring
       ├── Alarm → alarm
       ├── Report
       └── optional sync → server pusat
```

`rawdata` dipakai untuk raw line dari detector asli. `applog` tetap tersedia sesuai schema existing untuk application log/audit yang membutuhkan penyimpanan database.

Setiap measurement menyimpan `dose` aproksimasi dengan integrasi trapezoid dari dua pembacaan berurutan. Row `recent` diperbarui pada transaksi yang sama dengan measurement.

## Refresh

Semua data live menggunakan interval **2 detik**:

- Recent
- Tabular ketika tab aktif
- Chart ketika tab aktif
- Reports preview ketika tab aktif
- Alarm ketika tab aktif
- Logs ketika tab aktif
- Fullscreen monitoring browser
- Dummy acquisition
- Sync loop bila diaktifkan

Admin hanya me-refresh tab yang sedang terlihat agar database tidak dihantam banyak query bersamaan.

## Admin

Satu window admin menyediakan:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

Background refresh tidak membuka popup error berulang. Error polling ditampilkan di status bar. Popup hanya dipakai untuk aksi operator seperti export yang gagal atau error startup fatal.

## Monitoring fullscreen

Secara default tersedia di:

```text
http://127.0.0.1:8080
```

Untuk layar lain pada jaringan lokal, gunakan IP komputer server:

```text
http://IP-SERVER:8080
```

Halaman monitoring hanya menampilkan data publik station dan mengambil data terbaru setiap 2 detik.

## Report

Tab Reports dapat memilih From/To dan menampilkan:

- first measurement
- last measurement
- minimum dose rate
- average dose rate
- maximum dose rate
- jumlah sample
- approximate dose
- measurement preview
- alarm history

Gunakan **Export PDF** untuk membuat file report yang dapat dibuka dan diprint. Tab Tabular juga dapat export CSV.

## Alarm

Alarm memakai tabel existing:

```text
alarm(alarmid, serid, dtom, type, msg)
```

Event yang disimpan adalah transisi `ALERT`, `ALARM`, dan `RECOVERY`, sehingga polling 2 detik tidak menghasilkan baris alarm duplikat setiap sample.

## Server pusat

Sync lokal default **OFF**. Sistem lokal tetap normal meskipun server pusat belum tersedia.

Aktifkan di `.env` hanya ketika endpoint pusat sudah siap:

```env
RADMON_SYNC_ENABLED=1
RADMON_CENTRAL_URL=http://IP-SERVER-PUSAT:8090
RADMON_CENTRAL_TOKEN=ganti-token-kuat
```

Sync membaca `measurement` berdasarkan checkpoint file lokal di folder `runtime/`. Tidak ada queue table tambahan. Jika koneksi pusat gagal, checkpoint tidak maju sehingga data dicoba lagi setelah koneksi pulih.

Server pusat dijalankan hanya pada mesin pusat:

```bash
python central_server.py --host 0.0.0.0 --port 8090
```

Database pusat menggunakan schema yang sama. Ingest memakai primary key `measurement (serid, dtom)` untuk idempotensi.

## Konfigurasi

Edit `.env` bila perlu:

```env
RADMON_SERIAL_PORT=COM15
RADMON_DB_HOST=localhost
RADMON_DB_PORT=3306
RADMON_DB_USER=root
RADMON_DB_PASSWORD=
RADMON_DB_NAME=ipradmon
RADMON_REFRESH_INTERVAL=2
RADMON_PUBLIC_PORT=8080
RADMON_SYNC_ENABLED=0
```

Jangan menjalankan detector dan dummy bersamaan. Aplikasi sudah mengunci satu instance untuk mencegah collision writer.
