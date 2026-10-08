# Troubleshooting RadMon untuk Operator

Panduan ini membedakan gangguan browser, layanan RadMon, Grafana, MariaDB, dan koneksi detector. Periksa status/log terlebih dahulu; jangan menghapus atau mereset database, `grafana.db`, konfigurasi, archive, atau riwayat.

## Jalur akses dan port

| Port | Fungsi | Pemeriksaan |
| --- | --- | --- |
| `8090` | Gateway web RadMon, `/health`, aplikasi `/app`, dan Grafana melalui proxy | `http://127.0.0.1:8090/health` |
| `47652` | Listener lokal untuk mencegah dua instance RadMon berjalan bersamaan; bukan halaman web | Periksa listener lokal, jangan dibuka ke LAN |
| `3300` | Grafana native/editor pada PC server (loopback) | `http://127.0.0.1:3300/api/health` |
| `3306` | MariaDB central; juga port MariaDB pada setiap PC sumber LAN | Uji TCP ke `127.0.0.1` atau IP sumber dari PC server |

Di PowerShell, pemeriksaan awal yang hanya membaca status:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 8090,47652,3300,3306 } |
  Select-Object LocalAddress,LocalPort,OwningProcess
Invoke-RestMethod http://127.0.0.1:8090/health
Invoke-RestMethod http://127.0.0.1:3300/api/health
Test-NetConnection 127.0.0.1 -Port 3306
```

`/health` dengan HTTP 200 dan `status: ok` membuktikan Central/API merespons; itu sendiri belum membuktikan datasource Grafana atau setiap sumber LAN sehat. `database: ok` pada `/api/health` adalah kesehatan database internal Grafana, bukan pemeriksaan datasource MariaDB `ipradmon`.

## Bedakan gejala

- **`ERR_CONNECTION_REFUSED`**: browser tidak mendapat jawaban HTTP karena tidak ada listener di alamat/port itu, layanan belum aktif, atau alamat/port salah. Periksa listener dan uji `8090`; jalankan shortcut RadMon satu kali bila Central/API belum sehat.
- **HTTP `401 Unauthorized`**: server dapat dijangkau, tetapi halaman/API meminta login atau kredensial tidak diterima. `/app` dan data RadMon memerlukan login aplikasi; `GET /auth/me` yang menjawab 401 sebelum login adalah normal. Ini bukan bukti MariaDB mati.
- **Grafana `/api/health` sehat, datasource tidak sehat**: Grafana hidup tetapi koneksi datasource MySQL gagal. Bootstrap RadMon memeriksa datasource `ipradmon-mysql` pada setiap startup. Jika password secure field hilang atau autentikasi ditolak, bootstrap membaca konfigurasi datasource yang tersimpan dan melakukan PUT password-only dengan UID, endpoint, database, user, serta pengaturan plugin tetap; ia tidak menghapus database Grafana, membuat ulang datasource, atau mengubah plugin autentikasi MariaDB. Kegagalan setelah repair dilaporkan sebagai degraded, bukan dianggap sukses. Administrator juga dapat memeriksa melalui **Grafana → Connections → Data sources → ipradmon → Save & test** atau endpoint `POST http://127.0.0.1:3300/api/datasources/uid/ipradmon-mysql/health`.
- **Datasource sehat, panel menampilkan `No data`**: query berhasil tetapi tidak menemukan baris untuk detector/rentang waktu itu, atau query dashboard tidak menunjuk datasource/UID yang benar. Buka **Inspect → Query/Response** untuk membedakan hasil kosong dari error SQL. Periksa rentang waktu, `recent` (tren rolling), `recent_last` (maksimum 30 pembacaan asli per detector untuk fallback offline), `vrecent` (status/last-known), dan `measurement` (riwayat).
- **Panel menampilkan SQL error**: catat teks error yang sudah dimasker. Periksa nama tabel/kolom, hak baca, collation, timeout/lock, lalu eskalasikan. Jangan mengubah schema sumber detector.

Contoh query baca-saja di Grafana Explore dengan datasource `ipradmon-mysql`; jalankan satu query per waktu:

```sql
SELECT COUNT(*) AS recent_rows, MAX(dtom) AS latest_sample FROM recent;
SELECT serid, name, status, dtom, doserate FROM vrecent ORDER BY serid;
SELECT serid, MAX(dtom) AS latest_history FROM measurement GROUP BY serid;
```

Page 2 **Trends** mempertahankan rentang satu jam (`now-1h`) dan hanya menggambar sampel aktual pada rentang itu. Detector offline tidak diberi garis datar palsu. Tabel **Pembacaan Terakhir · Offline** menampilkan sampai 30 pembacaan asli dari `recent_last`, dengan timestamp asli, umur data, status `OFFLINE · LAST READING`, dan nilai dua desimal. Page 1 tetap menyajikan status/waktu/nilai terakhir yang diketahui; History dan Recent juga menampilkan beberapa pembacaan terakhir saat station offline. Selalu cocokkan nilai dengan waktu sampelnya.

## Pemulihan satu klik dan langkah aman

1. Gunakan shortcut **RadMon** di Desktop/Start Menu. Shortcut menjalankan `%LOCALAPPDATA%\RadMon\app\RadMon.exe --start`, memeriksa layanan lebih dahulu, memakai instance yang sehat, lalu membuka Control Plane. Shortcut **RadMon Monitoring** membuka monitoring melalui gateway.
2. Jika shortcut tidak tersedia, jalankan satu kali dari PowerShell biasa:

   ```powershell
   & "$env:LOCALAPPDATA\RadMon\app\RadMon.exe" --start
   ```

   Tunggu laporan status. Jangan menjalankannya berulang-ulang dan jangan menghentikan proses dengan paksa.
3. Ulangi pemeriksaan `/health`, Grafana, dan port di atas. Bila API belum sehat, periksa log sebelum mencoba langkah berikutnya.
4. Jika Scheduled Task **RadMon Server** terpasang tetapi tidak berjalan, Administrator dapat memeriksa task dan memulai **sekali**:

   ```powershell
   Get-ScheduledTask -TaskName "RadMon Server"
   Start-ScheduledTask -TaskName "RadMon Server"
   ```

   `Access denied`, mendaftarkan/memperbaiki task, memasang atau memperbarui installer, serta mengubah Windows Firewall memerlukan akun Administrator/elevated PowerShell. Operator biasa dapat menjalankan shortcut dan membaca health/log yang diizinkan.
5. Jika port MariaDB central `3306` tidak tersedia, eskalasikan ke administrator layanan/database. RadMon launcher tidak memasang ulang atau mereset MariaDB. Jika masalah hanya satu sumber, periksa jaringan/kredensial sumber itu tanpa menghentikan sumber lain.
6. Setelah perbaikan, uji kembali query langsung di Grafana `127.0.0.1:3300` dan tampilan melalui proxy `127.0.0.1:8090`.

Jangan menghapus tabel, menjalankan `TRUNCATE`/`DELETE` manual, menghapus `grafana.db`, membuat ulang user MariaDB, atau mereset datasource/dashboard sebagai langkah coba-coba. `measurement` dan tabel histori adalah rekam data; `recent` adalah read model dengan kebijakan rolling/last-known. Minta administrator meninjau log dan query sebelum perubahan database.

## Grafana dan dashboard

- Dari PC server, buka `http://127.0.0.1:3300` untuk pemeriksaan/editor Grafana. Tampilan monitoring melalui gateway tersedia di `http://127.0.0.1:8090/`; client LAN tidak perlu dan tidak seharusnya mengakses port 3300 secara langsung.
- Dashboard RadMon memakai datasource MySQL UID **`ipradmon-mysql`**, database **`ipradmon`**. Jangan menghapus lalu membuat ulang datasource; perbaikan Administrator harus mempertahankan UID, endpoint, database, user, serta pengaturan non-rahasia. Simpan password hanya melalui konfigurasi lokal/penyimpanan rahasia Grafana; jangan menyalinnya ke tiket atau log.
- Untuk Page 2, pastikan rentang waktunya **Last 1 hour**. Untuk panel kosong, gunakan **Inspect → Query** untuk memeriksa SQL, UID datasource, time range, dan error/result. Jangan menyimpan perubahan query/dashboard sebelum perubahan ditinjau Administrator.
- Status datasource yang sehat berarti Grafana berhasil tersambung ke database dengan kredensial datasource. Itu berbeda dari `/api/health` Grafana dan dari koneksi aplikasi RadMon ke MariaDB.

## Koneksi PC sumber LAN

Pada PC central, uji jalur TCP ke setiap sumber yang dikonfigurasi (contoh produksi):

```powershell
Test-NetConnection 192.168.1.50 -Port 3306
Test-NetConnection 192.168.1.52 -Port 3306
Test-NetConnection 192.168.1.38 -Port 3306
```

Uji dari PC central, bukan hanya dari laptop operator. `TcpTestSucceeded: False` mengarah ke layanan MariaDB sumber, kabel/routing/VLAN, firewall sumber, atau ACL jaringan; TCP sukses belum membuktikan autentikasi/schema database. Administrator dapat melihat status sumber dan waktu poll terakhir di Control Plane setelah login. `/health` menunjukkan status layanan pusat, bukan rincian kesehatan seluruh detector.

Untuk akses dari client BRIN-NET, uji `Test-NetConnection 192.168.1.2 -Port 8090` dari client. Gateway `8090` adalah jalur web yang dibuka untuk client; `3300`, `3306`, dan `47652` tetap lokal/antar-server sesuai arsitektur. Jika TCP `8090` gagal dari LAN tetapi berhasil di PC server, eskalasikan routing/ACL/firewall kepada administrator jaringan. Jangan membuka port database/Grafana ke seluruh LAN sebagai jalan pintas. Endpoint `8090` internal tidak menggantikan reverse proxy HTTPS untuk login remote; `426` berarti TLS termination, `RADMON_TRUSTED_PROXY_NETS`, dan `X-Forwarded-Proto: https` perlu diperiksa.

## Update dan checksum

Updater memeriksa commit release yang dituju dan checksum SHA-256 installer (`RadMon-Setup.exe.sha256`) sebelum menjalankan installer, lalu memverifikasi marker release setelah upgrade. Bila checksum tidak cocok, file hilang, atau marker hasil upgrade tidak sama dengan commit release yang diharapkan, hentikan proses update dan eskalasikan; jangan melewati verifikasi atau menjalankan installer yang tidak terverifikasi. Untuk pemeriksaan manual, cocokkan hasil `Get-FileHash -Algorithm SHA256` dengan file checksum resmi dari release yang sama. Upgrade normal mempertahankan `config`, `runtime`, `archives`, `reports`, database, dan histori.

## Log yang aman dibagikan

Log aplikasi berada di `%LOCALAPPDATA%\RadMon\runtime\logs` (terutama `radmon.log`, `managed-server.stderr.log`, dan log updater). Log Grafana berada di `%LOCALAPPDATA%\RadMon\runtime\grafana\logs` bila Grafana memakai runtime tersebut. Contoh melihat baris terbaru sambil memasker nilai rahasia umum:

```powershell
$log = "$env:LOCALAPPDATA\RadMon\runtime\logs\radmon.log"
Get-Content -LiteralPath $log -Tail 120 |
  ForEach-Object { $_ -replace '(?i)(password|secret|token|authorization)(\s*[:=]\s*)\S+', '$1$2[REDACTED]' }
```

Periksa timestamp, nama komponen/source, status, dan pesan error. Sebelum mengirim log, periksa hasil masking secara manual dan hapus alamat/token/session/cookie atau data personal yang masih tersisa. Jangan pernah membagikan `.env`, kredensial, header `Authorization`, file database, atau dump tabel.

Jika setelah langkah aman layanan tetap gagal, sertakan waktu kejadian, port/URL yang diuji, status HTTP/TCP, versi release, hasil datasource health (tanpa kredensial), status detector, dan potongan log yang sudah dimasker kepada Administrator RadMon atau administrator database/jaringan sesuai batas gangguan.
