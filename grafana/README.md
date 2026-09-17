# Grafana Monitoring TV

Grafana adalah visualization engine untuk landing monitoring RadMon. Ia membaca schema existing `device`, `measurement`, dan `alarm` secara read-only; tidak ada migration/DDL ke database source production.

## Access model

```text
http://192.168.1.2:8090/  -> redirect ke Playlist Grafana kiosk, anonymous read-only
http://localhost:3300     -> Grafana normal UI/login/editor di PC server
```

Anonymous Grafana mempunyai role Viewer. Login form tetap aktif untuk Administrator lokal. Default credential Grafana adalah `admin/admin` sampai diganti melalui prosedur admin.

Landing RadMon tidak membungkus Grafana dengan React/header/sign-in. User anonymous melihat Grafana fullscreen/kiosk secara langsung.

## Persistence dan editing

Dashboard Grafana yang sudah tersimpan adalah **authoritative state**.

Factory generator `radmon/grafana_tv.py` membuat resource yang belum ada dan menjadi sumber kontrak query panel RadMon. Startup RadMon:

- memperbarui konfigurasi datasource agar mengikuti settings aktif;
- hanya menyegarkan target/datasource panel RadMon yang dikenal;
- melakukan migrasi aman range root page 2 dan label trend factory;
- mempertahankan JSON/panel/layout/panel custom operator yang tersimpan.

Karena itu Administrator dapat membuka `localhost:3300`, Edit, Save, lalu perubahan langsung dipakai monitoring dan tetap ada setelah:

```text
RadMon restart
Grafana restart
Windows reboot
RadMon-Setup.exe upgrade
```

Data Grafana native berada di persistent runtime path `runtime/grafana`. Installer tidak menghapus runtime tersebut.

Port production sengaja stabil di **3300**. RadMon tidak mencari 3301/3302 bila 3300 konflik dengan proses asing; konflik harus dibetulkan agar URL monitoring/admin tidak berubah.

Production normal memakai Grafana **native**, bukan Docker, untuk menghemat RAM host 6 GB. Docker fallback hanya aktif bila `RADMON_GRAFANA_DOCKER_FALLBACK=1` atau dipakai eksplisit dalam maintenance/test.

## Factory seed

Bila instalasi benar-benar baru dan dashboard belum ada, generator menghasilkan:

```text
1 Realtime
1 Trends
5 Operations variants
= 7 dashboard payloads
```

Playlist `RadMon TV` mempunyai 15 item dengan interval **10 detik**:

```text
Realtime -> Trends -> Operations 1/5
Realtime -> Trends -> Operations 2/5
Realtime -> Trends -> Operations 3/5
Realtime -> Trends -> Operations 4/5
Realtime -> Trends -> Operations 5/5
```

Factory dashboard refresh **2 detik** dan dibatasi agar muat dalam grid <=24 row untuk kiosk sekitar 1920x1080. Setelah factory seed dibuat, Grafana Save menjadi sumber kebenaran dan RadMon tidak memaksa factory layout kembali.

## Header bersama factory dashboard

Baris organisasi terdiri dari:

- kiri: hari + tanggal WIB;
- tengah: `Instalasi Pengelolaan Limbah Radioaktif` dan `Direktorat Pengelolaan Fasilitas Ketenaganukliran`;
- kanan: waktu update WIB.

Hari/tanggal dan update time menggunakan konversi eksplisit `UTC -> +07:00`.

## Page 1 factory

Menampilkan 15 dose-rate card, mini sparkline, dan waktu measurement. Waktu measurement dikirim sebagai epoch milliseconds, bukan string SQL:

```sql
SELECT UNIX_TIMESTAMP(MAX(m.dtom)) * 1000 AS value
```

Panel memakai Grafana unit `dateTimeAsLocal`, menghindari regresi `No data` dari hasil string `DATE_FORMAT(...)`.

## Page 2 factory

Trend 1 jam sebagai small-multiple per gedung plus summary kondisi realtime. Contract Y-axis `0..1 µSv/h` factory tetap dipertahankan sampai Administrator mengubahnya di Grafana.

## Page 3 factory

Lima Operations variants, masing-masing menampilkan 3 station. Donut status, count NORMAL/ALERT/ALARM/OFFLINE, dan alarm terbaru 24 jam tersedia di factory seed.

Semua realtime state memakai latest `measurement`; satuan dose rate adalah **µSv/h**.
