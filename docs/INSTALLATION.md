# Panduan instalasi RadMon

## Tujuan dan prasyarat

Panduan ini untuk Administrator yang memasang RadMon Windows pada central PC
production (contoh topologi: `192.168.1.2`). Siapkan sebelum menjalankan
installer:

- hak Windows Administrator;
- account MariaDB central dan source dengan least privilege;
- Grafana native yang dapat dijalankan pada loopback;
- keputusan owner untuk URL HTTPS, reverse proxy, trusted proxy network,
  allowed origin, firewall, dan ACL NTFS;
- backup yang dapat direstore sebelum upgrade atau migrasi.

Gunakan placeholder pada template. Jangan menyalin password, PIN, token, atau
credential datasource ke repository, screenshot, issue, atau log.

## Instalasi awal

1. Jalankan `RadMon-Setup.exe` sebagai Administrator.
2. Installer memasang application tree, membuat `config\.env` dari template
   bila belum ada, mendaftarkan task **RadMon Server**, dan menyiapkan task
   **RadMon Updater**.
3. Edit `config\.env` menggunakan credential lokal yang disetujui:

```env
RADMON_CENTRAL_HOST=192.168.1.2
RADMON_DB_HOST=localhost
RADMON_DB_NAME=ipradmon
RADMON_DB_USER=<CENTRAL_DB_USER>
RADMON_DB_PASSWORD=<CENTRAL_DB_PASSWORD>

RADMON_LAN_ENABLED=1
RADMON_LAN_SOURCES=gd50@192.168.1.50;gd52@192.168.1.52;gd38@192.168.1.38
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=<SOURCE_DB_USER>
RADMON_LAN_DB_PASSWORD=<SOURCE_DB_PASSWORD>
RADMON_LAN_DB_NAME=ipradmon

RADMON_BOOTSTRAP_ADMIN_USER=<ADMIN_USERNAME>
RADMON_BOOTSTRAP_ADMIN_PASSWORD=<BOOTSTRAP_PASSWORD>
RADMON_BOOTSTRAP_ADMIN_PIN=<BOOTSTRAP_PIN>

RADMON_GRAFANA_PORT=3300
RADMON_GRAFANA_USER=admin
RADMON_GRAFANA_PASSWORD=GENERATE_ON_FIRST_START
RADMON_GRAFANA_BIN=
RADMON_GRAFANA_DOCKER_FALLBACK=0

RADMON_WEB_COOKIE_SECURE=1
RADMON_TRUSTED_PROXY_NETS=<TRUSTED_PROXY_CIDR>
RADMON_WEB_ALLOWED_ORIGINS=https://monitoring.example
```

4. Jika Grafana tidak ditemukan otomatis, isi `RADMON_GRAFANA_BIN` dengan path
   lokal ke `grafana-server.exe`.
5. Pastikan reverse proxy HTTPS meneruskan origin dan forwarded protocol yang
   benar sebelum mengizinkan login remote.
6. Restart task **RadMon Server** atau reboot Windows.
7. Login ke `/app` sebagai bootstrap Administrator. Setelah user terbentuk,
   hapus credential bootstrap dari `.env` dan simpan file dengan ACL NTFS
   least-privilege.

**Hasil yang diharapkan:** task berjalan sebagai `SYSTEM` saat Windows boot,
API mendengarkan gateway `8090`, Grafana native tetap loopback pada `3300`, dan
client remote dapat login melalui HTTPS setelah routing/ACL mengizinkan.

**Pengecualian:** RadMon tidak menerima `admin/admin`, password Grafana kosong,
atau secret lemah untuk managed bootstrap. Konflik port `3300` harus diperbaiki;
RadMon tidak pindah diam-diam ke `3301` atau `3302`. MariaDB tidak dipasang atau
direstart oleh launcher.

## Layout instalasi

```text
RadMon\
  app\
    RadMon.exe
    RadMon Admin.exe
    web\
    docs\manual\
    grafana\
  config\
    .env.example
    .env
  runtime\
  archives\
  reports\
  updater\
```

`config\.env`, `runtime`, `archives`, dan `reports` adalah data lokal yang
dipertahankan selama upgrade. Manual HTML yang ikut installer berada di
`app\docs\manual\`; source Markdown tidak seluruhnya dipaketkan.

## URL dan network boundary

```text
https://monitoring.example/    Grafana monitoring, session RadMon wajib
https://monitoring.example/app Control Plane, session RadMon wajib
http://127.0.0.1:3300         Grafana admin/editor lokal di PC server
```

Firewall host membuka TCP `8090` untuk routed clients sesuai boundary jaringan.
Port `3300`, `3306`, dan `47652` bukan port client web. Routing BRIN-NET,
VLAN, client isolation, dan ACL tetap harus diuji oleh administrator jaringan.
Jangan membuka database atau Grafana direct ke LAN untuk mengatasi kegagalan
route.

## Headless 24/7

Scheduled Task menjalankan:

```text
app\RadMon.exe --server
```

Task menggunakan startup Windows, `SYSTEM`, `StartWhenAvailable`, mengabaikan
instance ganda, dan mempunyai restart bounded sesuai konfigurasi installer.
Shortcut **RadMon** menggunakan `--start` untuk recovery aman dan membuka
Control Plane; shortcut **RadMon Monitoring** membuka landing monitoring.

## Upgrade

1. Pastikan backup terbaru dan lakukan restore drill sesuai kebijakan owner.
2. Pastikan tidak ada perubahan credential production yang belum dicatat.
3. Biarkan updater terverifikasi atau jalankan installer release yang sudah
   disetujui sebagai Administrator.
4. Updater memeriksa ancestry release, checksum SHA-256, marker, dan readiness
   health stabil. Ia men-stage application tree lama dan mengembalikannya bila
   validasi gagal.
5. Setelah berhasil, verifikasi `/health`, `/app`, monitoring Grafana,
   source-health, login/RBAC, alarm, report, dan persistence dashboard.

Jangan menghapus backup/staging diagnostik sebelum validasi upgrade selesai.
Detail updater ada di [UPDATER-ID.md](UPDATER-ID.md).

## Commissioning wajib

CI, package smoke test, dan updater self-test hanya memverifikasi artifact dan
kontrak source. Sebelum operasi penuh, lakukan dan simpan evidence untuk:

- koneksi dan authentication `.50`, `.52`, `.38`, central MariaDB `ipradmon`,
  dan checkpoint source;
- HTTPS, trusted proxy, allowed origin, firewall `8090`, serta akses dari satu
  client BRIN-NET di luar PC server;
- ACL NTFS pada `.env`, `runtime`, archive, report, dan security DB;
- login Viewer/Operator/Administrator dan backend RBAC;
- Grafana datasource least privilege, transport encryption/certificate
  verification, persistence setelah restart, dan port loopback;
- rolling `recent`/`vrecent`, last-reading offline dengan timestamp asli, dan
  pembedaan datasource error versus hasil query kosong;
- source response `i_flag=0` menjadi `i_flag=1` dengan `ack` tidak berubah,
  retry/error handling, suppression, dan acceptance buzzer hardware;
- report 24 jam, full rows versus preview partial 250 baris, archive export,
  backup, dan **restore nyata**.

RadMon tidak melakukan DDL pada database source production dan tidak boleh
dianggap telah tersertifikasi hanya karena commissioning checklist source code
berhasil.
