# Grafana Monitoring TV

Grafana adalah visualization engine untuk landing monitoring RadMon. Target
dashboard membaca read model central `device`, `recent`, `recent_last`,
`vrecent`, dan event `alarm` secara read-only. Grafana tidak memigrasikan schema
database detector/source; rolling read model central dikelola oleh RadMon.

Compose fallback juga bind ke `127.0.0.1:${RADMON_GRAFANA_PORT:-3300}` dan
menolak start bila `RADMON_GRAFANA_PASSWORD` belum diisi. Port Grafana tidak
boleh dipublish langsung ke LAN.

## Access model

```text
https://monitoring.example/ -> Playlist Grafana kiosk, session RadMon required
http://localhost:3300     -> Grafana normal UI/login/editor di PC server
```

Remote anonymous tidak didukung. Login form hanya untuk Administrator lokal;
Grafana direct/anonymous, bila dipakai untuk compatibility, tetap loopback-only.
Secret `admin/admin`, kosong, dan secret lemah ditolak oleh managed bootstrap;
instalasi baru dapat membuat secret unik dari marker first-start.

Landing RadMon tidak membungkus Grafana dengan React/header/sign-in. User
remote membuka session RadMon lalu melihat Grafana fullscreen/kiosk melalui
gateway.

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

Playlist `RadMon TV` mempunyai 15 item dengan interval **30 detik**:

```text
Realtime -> Trends -> Operations 1/5
Realtime -> Trends -> Operations 2/5
Realtime -> Trends -> Operations 3/5
Realtime -> Trends -> Operations 4/5
Realtime -> Trends -> Operations 5/5
```

Factory dashboard refresh **5 detik** dan dibatasi agar muat dalam grid <=24 row untuk kiosk sekitar 1920x1080. Setelah factory seed dibuat, Grafana Save menjadi sumber kebenaran dan RadMon tidak memaksa factory layout kembali.

## Header bersama factory dashboard

Baris organisasi terdiri dari:

- kiri: hari + tanggal WIB;
- tengah: `Instalasi Pengelolaan Limbah Radioaktif` dan `Direktorat Pengelolaan Fasilitas Ketenaganukliran`;
- kanan: waktu update WIB.

Hari/tanggal dan update time menggunakan konversi eksplisit `UTC -> +07:00`.

## Page 1 factory

Menampilkan 15 dose-rate card, mini sparkline, dan waktu measurement. Card,
status, dan waktu measurement membaca `vrecent`; sparkline membaca sampel nyata
dari `recent` pada window dashboard 30 menit. Waktu measurement dikirim sebagai
epoch milliseconds, bukan string SQL:

```sql
SELECT TIMESTAMPDIFF(MICROSECOND, '1970-01-01 00:00:00',
       CONVERT_TZ(dtom, '+07:00', '+00:00')) / 1000 AS value
FROM vrecent
WHERE serid = <SERID>
ORDER BY dtom DESC
LIMIT 1
```

Panel memakai Grafana unit `dateTimeAsLocal`, menghindari regresi `No data` dari hasil string `DATE_FORMAT(...)`.

## Page 2 factory

Trend 1 jam sebagai small-multiple per gedung plus summary kondisi realtime.
Contract Y-axis `0..1 µSv/h` factory tetap dipertahankan sampai Administrator
mengubahnya di Grafana. Hasil kosong pada window ini harus dibedakan dari
datasource error melalui **Inspect → Query/Response**; jangan langsung restart.

## Page 3 factory

Lima Operations variants, masing-masing menampilkan 3 station. Donut status, count NORMAL/ALERT/ALARM/OFFLINE, dan alarm terbaru 24 jam tersedia di factory seed.

Semua current/latest state memakai latest row dari rolling `vrecent`; bila tidak ada
rolling sample, view dapat menampilkan last-known sample asli dari
`measurement` dengan status `OFFLINE`. `recent_last` menyimpan paling banyak 30
pembacaan asli per detector untuk tabel offline dan mempertahankan timestamp
serta umur asli. Satuan dose rate adalah **µSv/h**. Tidak ada nilai atau waktu
synthetic yang dibuat untuk mengisi panel.
