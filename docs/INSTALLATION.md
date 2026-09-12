# Installation Guide

## Production Windows

Production RadMon dipasang dengan **`RadMon-Setup.exe`** pada central PC `192.168.1.2`. Installer membutuhkan Administrator karena ia mendaftarkan Scheduled Task 24/7 dan firewall rule LocalSubnet.

Struktur instalasi:

```text
RadMon\
  app\
    RadMon.exe
    web\
    docs\manual\
    grafana\
  config\
    .env.example
    .env
  runtime\
  archives\
  reports\
```

`config\.env`, `runtime`, `archives`, dan `reports` dipertahankan saat upgrade/uninstall sesuai kebijakan data lokal.

## Instalasi awal

1. Jalankan `RadMon-Setup.exe` sebagai Administrator.
2. Installer membuat Scheduled Task **RadMon Server** dengan trigger Windows startup, user SYSTEM, restart otomatis, dan tanpa batas runtime.
3. Installer membuat firewall inbound TCP `8090` dan `3300` hanya untuk `LocalSubnet`.
4. Edit `config\.env`.
5. Isi central/source database credential serta bootstrap Administrator bila security DB masih kosong.

Contoh minimum:

```env
RADMON_CENTRAL_HOST=192.168.1.2
RADMON_DB_HOST=localhost
RADMON_DB_NAME=ipradmon

RADMON_LAN_ENABLED=1
RADMON_LAN_SOURCES=gd50@192.168.1.50;gd52@192.168.1.52;gd38@192.168.1.38
RADMON_LAN_DB_PORT=3306
RADMON_LAN_DB_USER=ISI_USER_PRODUCTION
RADMON_LAN_DB_PASSWORD=ISI_PASSWORD_PRODUCTION
RADMON_LAN_DB_NAME=ipradmon

RADMON_BOOTSTRAP_ADMIN_USER=admin-radmon
RADMON_BOOTSTRAP_ADMIN_PASSWORD=GANTI_PASSWORD_KUAT
RADMON_BOOTSTRAP_ADMIN_PIN=GANTI_PIN

RADMON_GRAFANA_PORT=3300
RADMON_GRAFANA_USER=admin
RADMON_GRAFANA_PASSWORD=admin
RADMON_GRAFANA_BIN=
RADMON_GRAFANA_DOCKER_FALLBACK=0
```

Jika Grafana native terpasang di lokasi yang tidak ditemukan otomatis, isi `RADMON_GRAFANA_BIN` dengan path `grafana-server.exe`.

Sesudah `.env` valid, restart Scheduled Task `RadMon Server` atau reboot PC. Service tidak memerlukan user Windows login.

## URL production

Dari network BRIN/LAN yang diizinkan:

```text
http://192.168.1.2:8090/       monitoring Grafana fullscreen/kiosk, tanpa login RadMon
http://192.168.1.2:8090/app    RadMon Control Plane, wajib login
```

Di PC server:

```text
http://localhost:3300          Grafana normal/admin/editor
```

Viewer, Operator, dan Administrator semuanya merupakan user RadMon yang wajib login. Anonymous hanya boleh melihat Grafana monitoring.

## Grafana native dan persistence

Production normal tidak membutuhkan Docker Desktop. RadMon memakai Grafana native untuk menghemat RAM pada host 6 GB.

Data Grafana berada di persistent runtime storage. Bootstrap hanya membuat datasource/dashboard/playlist yang belum ada. Dashboard existing tidak dikembalikan ke factory JSON. Jika dashboard dari versi lama masih read-only, RadMon melakukan migrasi satu kali untuk membuka editing sambil mempertahankan isi dashboard tersimpan.

Administrator dapat login ke `http://localhost:3300` menggunakan akun Grafana (default `admin/admin` bila belum diganti), mengedit dashboard, lalu Save. Monitoring anonymous memakai UID/dashboard yang sama sehingga perubahan langsung terlihat dan tetap ada setelah restart RadMon/Grafana/Windows maupun upgrade installer.

Port production Grafana sengaja stabil di `3300`; RadMon tidak diam-diam berpindah ke 3301/3302. Bila 3300 dipakai proses asing, perbaiki konflik port tersebut.

## Headless 24/7 mode

Scheduled Task menjalankan:

```text
app\RadMon.exe --server
```

Mode ini menjalankan collector LAN, secure API, archive/alarm policy, web platform, dan bootstrap Grafana tanpa membuka PySide desktop. Task Scheduler dikonfigurasi `StartWhenAvailable` dan restart setiap satu menit bila proses berhenti.

Shortcut **RadMon** hanya membuka browser ke authenticated web control plane. Shortcut **RadMon Monitoring** membuka landing monitoring anonymous. Menutup browser tidak mematikan server.

## Upgrade

1. Backup instalasi production.
2. Jalankan `RadMon-Setup.exe` terbaru sebagai Administrator.
3. Installer mengganti `app\` tetapi mempertahankan `config\.env`, `runtime`, `archives`, dan `reports`.
4. Scheduled Task didaftarkan ulang dan dijalankan kembali.
5. Verifikasi `/`, `/app`, Grafana `localhost:3300`, source health, alarm response/suppression, dan report.

Jangan mengganti label `gd50`, `gd52`, atau `gd38`; checkpoint dan policy state menggunakan `source_id` tersebut.

## Mode developer

Detector serial dan dummy hanya untuk source checkout:

```text
python -m radmon.dev_app --source detector
python -m radmon.dev_app --source dummy
```

Node.js/Vite hanya diperlukan untuk development/build frontend; Node tidak diperlukan pada production runtime.

## Commissioning wajib

CI dan smoke test memastikan source, Kumo frontend, executable, serta installer dapat dibuild. Sebelum operasi penuh tetap commissioning langsung pada PC `.2`:

- konektivitas `.50`, `.52`, `.38`;
- central MariaDB `ipradmon`;
- Grafana native pada port 3300 dan persistence setelah restart;
- anonymous monitoring hanya dari network BRIN yang diizinkan;
- login Viewer/Operator/Administrator dan backend RBAC;
- response/silence source `i_flag=1` tanpa mengubah `ack`;
- source health/recovery;
- archive/report path dan permission.

RadMon tidak melakukan DDL pada source MariaDB production.
