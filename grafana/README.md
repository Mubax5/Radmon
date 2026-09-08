# Grafana Monitoring TV

Grafana membaca schema existing `device`, `measurement`, dan `alarm` secara read-only. Tidak ada migration database production.

Dashboard TV dibuat oleh `radmon/grafana_tv.py` saat runtime. Generator menghasilkan:

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

Setiap dashboard refresh **2 detik** dan tetap dibatasi agar muat dalam grid <=24 row untuk kiosk sekitar 1920x1080.

## Header bersama

Baris atas setiap dashboard mempertahankan title utama existing. Baris organisasi terdiri dari:

- kiri: hari + tanggal WIB dengan font kecil;
- tengah: `Instalasi Pengelolaan Limbah Radioaktif` dan `Direktorat Pengelolaan Fasilitas Ketenaganukliran` dengan ukuran font existing;
- kanan: waktu update WIB dengan font kecil.

Hari/tanggal dan update time menggunakan konversi eksplisit `UTC -> +07:00`, sehingga tidak bergantung pada timezone browser.

## Page 1

Menampilkan 15 dose-rate card, mini sparkline, dan waktu measurement. Nilai realtime berasal dari latest `measurement`.

Waktu measurement **bukan string SQL**. Query mengembalikan epoch milliseconds:

```sql
SELECT UNIX_TIMESTAMP(MAX(m.dtom)) * 1000 AS value
```

Panel memakai Grafana unit `dateTimeAsLocal`. Contract ini menghindari regresi `No data` yang terjadi saat nilai timestamp dipaksa menjadi hasil string `DATE_FORMAT(...)`.

## Page 2

Trend 3 jam sebagai small-multiple per gedung plus summary kondisi realtime. Contract Y-axis `0..1 µSv/h` masih dipertahankan dari versi sebelumnya sampai ada keputusan scaling terpisah.

## Page 3

Lima Operations variants, masing-masing menampilkan 3 station pada tabel kondisi operasional. Donut status, count NORMAL/ALERT/ALARM/OFFLINE, dan alarm terbaru 24 jam tetap tersedia pada setiap variant.

Semua realtime state memakai latest `measurement`; `recent` bukan sumber state Grafana. Satuan dose rate adalah **µSv/h**.

Jika Grafana lokal tersedia, auto-setup memakai HTTP API. Bila tidak, runtime mencoba Grafana native lalu Docker sebagai fallback terakhir.
