# Troubleshooting RadMon untuk operator

## Tujuan dan aturan aman

Panduan ini memisahkan gangguan browser, Central/API, Grafana, datasource
MariaDB, source LAN, dan data detector. Periksa status dan log sebelum
perubahan. Jangan menghapus database, `grafana.db`, konfigurasi, archive,
report, checkpoint, atau history sebagai langkah coba-coba.

## Port dan pemeriksaan awal

| Port | Fungsi | Pemeriksaan |
| --- | --- | --- |
| `8090` | Gateway RadMon, `/health`, `/app`, dan Grafana proxy | `http://127.0.0.1:8090/health` |
| `47652` | Listener lokal single-instance; bukan halaman web | Tetap lokal, jangan dibuka ke LAN |
| `3300` | Grafana native/editor pada PC server | `http://127.0.0.1:3300/api/health` |
| `3306` | MariaDB central atau source LAN | Uji dari PC central ke host terkait |

Pemeriksaan awal yang hanya membaca status:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 8090,47652,3300,3306 } |
  Select-Object LocalAddress,LocalPort,OwningProcess
Invoke-RestMethod http://127.0.0.1:8090/health
Invoke-RestMethod http://127.0.0.1:3300/api/health
Test-NetConnection 127.0.0.1 -Port 3306
```

`/health` dengan HTTP 200 dan `status: ok` membuktikan Central/API merespons;
itu belum membuktikan setiap source LAN atau datasource Grafana sehat.
`database: ok` pada Grafana `/api/health` adalah database internal Grafana,
bukan koneksi datasource `ipradmon`.

## Bedakan gejala

### Browser tidak tersambung atau meminta login

- **`ERR_CONNECTION_REFUSED`**: tidak ada listener, service belum aktif, atau
  alamat/port salah. Periksa `8090`, lalu jalankan shortcut **RadMon** satu kali.
- **HTTP `401 Unauthorized`**: server terjangkau, tetapi session belum login
  atau credential tidak diterima. `GET /auth/me` yang 401 sebelum login normal;
  itu bukan bukti MariaDB mati.
- **HTTP `426` saat login remote**: periksa TLS termination, cookie secure,
  `RADMON_TRUSTED_PROXY_NETS`, dan `X-Forwarded-Proto: https`. Jangan mengubah
  gateway menjadi HTTP remote untuk melewati error.

### Grafana hidup tetapi datasource gagal

Jika Grafana `/api/health` sehat namun **Save & test** datasource `ipradmon`
gagal, masalah berada pada endpoint, database, user/password, network,
transport encryption, certificate verification, atau authentication plugin.
RadMon melaporkan kondisi degraded; jangan menyebutnya sehat hanya karena
halaman Grafana terbuka.

Administrator dapat memeriksa **Grafana → Connections → Data sources →
ipradmon → Save & test** atau datasource health endpoint lokal yang sesuai.
Jangan menghapus datasource, database Grafana, atau mengubah UID
`ipradmon-mysql` untuk percobaan.

### Panel Grafana `No data`

**No data bukan satu diagnosis.** Jangan langsung restart RadMon.

1. **Datasource error:** buka **Inspect → Query/Response** atau **Save & test**
   dan cari error koneksi/SQL. Perbaiki datasource atau eskalasikan kepada
   Administrator.
2. **Query berhasil tetapi hasil kosong:** periksa panel, SERID, datasource UID,
   dan current time window. Page **Trends** menggunakan **Last 1 hour** dan
   hanya menggambar sampel asli pada window itu. Hasil kosong pada window saat
   ini tidak membuktikan history hilang.

Gunakan batas data berikut untuk menentukan query yang tepat:

- `recent`: rolling monitoring window maksimal tiga jam;
- `recent_last`: maksimum 30 pembacaan asli terbaru per detector untuk fallback
  offline;
- `vrecent`: current status dan latest rolling/last-known context;
- `measurement`: history authoritative untuk History, Reports, dan Archive.

Jika detector offline, last reading boleh ditampilkan hanya bila pembacaan asli
tersedia. Tampilkan nilai, timestamp asli, dan umur data; jangan membuat nilai
atau timestamp pengganti. Current status harus tetap `OFFLINE` bila sudah
melewati batas idle.

### Alarm dan tombol response

Pada halaman Alarm, policy central dan source alarm adalah evidence berbeda.
Tombol response source hanya muncul/berlaku untuk row source dengan `i_flag=0`.
Response yang berhasil harus membaca kembali row `(serid, dtoa)` dengan
`i_flag=1`; `ack` legacy tetap tidak diubah.

Jika source timeout, row berubah, commit gagal, atau read-back gagal, jangan
mengulang response berkali-kali dan jangan menganggap buzzer fisik sudah diam.
Periksa retry state dan lakukan acceptance hardware terpisah saat commissioning.

## Pemulihan aman

1. Gunakan shortcut **RadMon**. Launcher memeriksa service, memakai instance
   yang sehat, dan membuka Control Plane.
2. Jika shortcut tidak tersedia, jalankan satu kali:

   ```powershell
   & "$env:LOCALAPPDATA\RadMon\app\RadMon.exe" --start
   ```

3. Tunggu status, ulangi `/health`, Grafana, dan port di atas.
4. Jika Scheduled Task terpasang tetapi berhenti, Administrator dapat memulai
   sekali:

   ```powershell
   Get-ScheduledTask -TaskName "RadMon Server"
   Start-ScheduledTask -TaskName "RadMon Server"
   ```

5. Jika MariaDB central `3306` tidak tersedia, eskalasikan ke administrator
   layanan/database. Jika hanya satu source gagal, periksa source itu tanpa
   menghentikan source lain.

Jangan menjalankan banyak `--server`, membunuh semua proses Python, menjalankan
`TRUNCATE`/`DELETE` manual, membuat ulang user database, atau mereset dashboard
sebagai langkah coba-coba.

## Source LAN dan jaringan BRIN-NET

Jalankan dari PC central:

```powershell
Test-NetConnection 192.168.1.50 -Port 3306
Test-NetConnection 192.168.1.52 -Port 3306
Test-NetConnection 192.168.1.38 -Port 3306
```

`TcpTestSucceeded: False` dapat berarti service MariaDB source, kabel/routing,
VLAN, firewall source, atau ACL jaringan. TCP sukses belum membuktikan
authentication atau schema. Dari client BRIN-NET, uji hanya gateway:

```powershell
Test-NetConnection 192.168.1.2 -Port 8090
```

Jangan membuka port database, Grafana, atau single-instance ke seluruh LAN.

## Report dan archive

- Rentang report harus lebih dari nol dan maksimal **24 jam**; tepat 24 jam
  diperbolehkan.
- Preview maksimal **250 baris** dan bersifat partial.
- PDF penuh berisi seluruh measurement sampai batas **50.000 row** dan alarm
  sampai batas **10.000 row**; report gagal bila batas terlampaui atau data yang
  diterima tidak lengkap.
- Timestamp report adalah WIB dan nilai dose rate menggunakan dua desimal.

Jika report gagal, simpan pesan error, SERID, rentang, dan status job. Jangan
mengedit artifact, archive ZIP, atau SQL dump manual. Untuk archive retry,
eskalasikan kepada Administrator.

## Update dan checksum

Updater memeriksa release ancestry, checksum SHA-256 installer yang sama,
marker release, lalu tiga health check stabil. Jika checksum, marker, atau
readiness tidak cocok, hentikan proses dan eskalasikan; jangan melewati
verifikasi. Detail rollback ada di [UPDATER-ID.md](UPDATER-ID.md).

Upgrade normal mempertahankan `config`, `runtime`, `archives`, `reports`,
database, dan history. Tidak ada pernyataan bahwa artifact tertentu sudah
terpasang di production hanya karena release tersedia.

## Log yang aman dibagikan

Log aplikasi berada di `%LOCALAPPDATA%\RadMon\runtime\logs`, terutama
`radmon.log`, `managed-server.stderr.log`, dan log updater. Contoh masking
dasar:

```powershell
$log = "$env:LOCALAPPDATA\RadMon\runtime\logs\radmon.log"
Get-Content -LiteralPath $log -Tail 120 |
  ForEach-Object { $_ -replace '(?i)(password|secret|token|authorization)(\s*[:=]\s*)\S+', '$1$2[REDACTED]' }
```

Tinjau hasil masking secara manual dan hapus alamat internal, token, session,
cookie, serta data personal yang tersisa. Jangan membagikan `.env`, credential,
header `Authorization`, security DB, file database, atau dump tabel.

Saat eskalasi, sertakan waktu kejadian, port/URL yang diuji, status HTTP/TCP,
release yang terpasang, hasil datasource health tanpa credential, status source,
dan potongan log yang sudah dimasker.
