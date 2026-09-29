# Panduan operator: menjalankan dan memulihkan RadMon

## Sekali klik

Gunakan shortcut **RadMon** di Desktop atau Start Menu. Shortcut menjalankan
`RadMon.exe --start` dari instalasi, biasanya:

`%LOCALAPPDATA%\RadMon\app\RadMon.exe`

Launcher memeriksa koneksi MariaDB (port konfigurasi, bawaan 3306), API RadMon
(health endpoint di `127.0.0.1:8090`), dan Grafana (`/api/health`, biasanya port
3300 atau 3000). Komponen yang sudah sehat dipakai kembali. Jika API belum aktif,
launcher menjalankan Scheduled Task **RadMon Server**; jika task tidak ada atau
tidak dapat dipakai, launcher memulai proses `RadMon.exe --server` yang dikelola.
Server mengelola bootstrap Grafana. Launcher menunggu terbatas lalu menampilkan
status tiap komponen beserta kegagalan yang terdeteksi.

Untuk monitoring, gunakan shortcut **RadMon Monitoring**. Shortcut itu juga
melakukan pemeriksaan/pemulihan sebelum membuka halaman monitoring.

## Arti hasil status

- **sudah berjalan**: health check berhasil; tidak ada proses tambahan dibuat.
- **dimulai / siap**: komponen berhasil aktif setelah pemulihan.
- **tidak tersedia / timeout / gagal memulai**: launcher menyebut komponen dan
  detail yang perlu diperiksa. Kegagalan satu komponen tidak menghentikan
  komponen lain yang masih bisa digunakan.
- MariaDB hanya diperiksa, tidak dipasang ulang atau dimulai ulang oleh launcher.
  Jika tidak tersedia, pastikan layanan MariaDB yang sudah digunakan instalasi
  berjalan dan menerima koneksi pada host/port konfigurasi.

## Pemulihan manual

1. Jalankan shortcut **RadMon** sekali lagi setelah membaca status; start aman
   diulang dan tidak membuka server kedua jika API sudah sehat.
2. Untuk menjalankan task layanan secara manual, buka PowerShell sebagai
   administrator dan jalankan:

   ```powershell
   Start-ScheduledTask -TaskName "RadMon Server"
   ```

   Bila task belum terdaftar, gunakan launcher EXE:

   ```powershell
   & "$env:LOCALAPPDATA\RadMon\app\RadMon.exe" --start
   ```

3. Periksa `http://127.0.0.1:8090/health` untuk API. Log aplikasi berada di
   `%LOCALAPPDATA%\RadMon\runtime\logs`; log Grafana dikelola di folder runtime
   Grafana.
4. Jika MariaDB tidak sehat, eskalasikan ke administrator layanan/database
   untuk memeriksa layanan dan koneksi. Setelah pulih, jalankan shortcut RadMon
   lagi.

Jangan menghapus folder `config`, `runtime`, `archives`, database, atau data
Grafana untuk pemulihan. Jangan menghentikan/mengakhiri proses secara paksa;
launcher menggunakan health check dan reuse untuk menghindari duplikasi.
