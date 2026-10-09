# Panduan operator: menjalankan dan memulihkan RadMon

## Tujuan

Gunakan panduan ini untuk membuka RadMon atau memulihkan komponen yang belum
sehat tanpa membuat instance server kedua, menghapus data, atau mengubah
database.

## Jalur normal

1. Gunakan shortcut **RadMon** di Desktop atau Start Menu.
2. Launcher menjalankan `RadMon.exe --start`, memeriksa MariaDB, API RadMon,
   dan Grafana, lalu memakai komponen yang sudah sehat.
3. Gunakan shortcut **RadMon Monitoring** untuk membuka landing Grafana setelah
   recovery check yang sama.

Launcher memeriksa MariaDB pada host/port konfigurasi (bawaan `3306`), health
API di `127.0.0.1:8090`, dan Grafana `/api/health` pada port configured (bawaan
`3300`). MariaDB hanya diperiksa; launcher tidak memasang, mereset, atau
merestart MariaDB.

## Arti hasil

| Status | Arti dan tindakan |
| --- | --- |
| **sudah berjalan** | Health check berhasil; tidak ada proses tambahan. Buka halaman yang diminta. |
| **dimulai / siap** | Komponen berhasil dipulihkan dan siap dipakai; login lalu verifikasi source health. |
| **tidak tersedia / timeout / gagal memulai** | Komponen dan detail masalah disebutkan. Jangan menganggap komponen lain ikut gagal; lanjutkan diagnosis komponen tersebut. |

Jika semua komponen yang diperlukan sehat, **hasil yang diharapkan** adalah
Control Plane terbuka tanpa proses server kedua. Jika API belum aktif, launcher
lebih dahulu mencoba Scheduled Task **RadMon Server**, kemudian fallback proses
yang dikelola bila task tidak tersedia.

## Pemulihan manual

1. Baca status launcher. Jalankan shortcut **RadMon** satu kali lagi hanya
   setelah status menunjukkan komponen yang perlu dipulihkan.
2. Administrator dapat memulai task secara manual dari PowerShell elevated:

   ```powershell
   Start-ScheduledTask -TaskName "RadMon Server"
   ```

   Jika task belum terdaftar, gunakan launcher yang dipaketkan:

   ```powershell
   & "$env:LOCALAPPDATA\RadMon\app\RadMon.exe" --start
   ```

3. Baca health API:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8090/health
   Invoke-RestMethod http://127.0.0.1:3300/api/health
   ```

4. Periksa log di `%LOCALAPPDATA%\RadMon\runtime\logs`, termasuk log Grafana
   bila digunakan.
5. Jika MariaDB atau source LAN tidak sehat, eskalasikan kepada administrator
   layanan/database/jaringan. Setelah perbaikan, ulangi shortcut RadMon satu
   kali dan verifikasi hasilnya.

## Larangan pemulihan

Jangan:

- menjalankan beberapa `--server` atau shortcut berulang tanpa membaca status;
- membunuh semua proses Python atau menghapus `runtime`;
- menghapus `config`, security DB, checkpoint, `archives`, `reports`,
  `grafana.db`, atau history;
- membuka port `3300`, `3306`, atau `47652` ke LAN sebagai jalan pintas.

Untuk datasource error, query kosong, data offline, source LAN, checksum
update, dan log yang aman dibagikan, lanjutkan ke
[Troubleshooting operator](TROUBLESHOOTING-ID.md).
