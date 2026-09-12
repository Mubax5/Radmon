# User Manual

## Start dan shutdown

Production central dijalankan dari **`app\RadMon.exe`**. Jangan menjalankan collector/API sebagai proses terpisah. Satu proses RadMon menjadi owner untuk LAN collection, secure API, desktop Admin, alarm policy, archive lifecycle, dan bootstrap Grafana.

Untuk shutdown normal, tutup desktop Admin. Central service yang dimiliki RadMon akan ikut berhenti. Jika aplikasi tidak bisa dibuka karena instance lain masih aktif, cek proses RadMon yang sedang berjalan; jangan mematikan semua proses Python/port secara membabi buta.

Konfigurasi production berada di `config\.env`. Data runtime penting berada di `runtime\`, `archives\`, dan `reports\` dan harus dipertahankan saat upgrade.

## Login dan role

- **Administrator**: monitoring, Response/Silence, suppression, user management, edit station, archive admin.
- **Operator**: monitoring/report, Response/Silence, suppression.
- **Viewer**: read-only.

Aksi sensitif memerlukan PIN sesuai policy security. Jangan berbagi credential antar operator.

## Station dan source health

Central PC `.2` menarik data dari:

```text
gd50 -> 192.168.1.50
gd52 -> 192.168.1.52
gd38 -> 192.168.1.38
```

Sidebar mengelompokkan station berdasarkan source dan menampilkan status `CONNECTED`, `DEGRADED`, `OFFLINE`, atau `RECOVERED`. Kegagalan satu source tidak menghentikan source lain.

Identity station LAN berasal dari `device.serid` source production. Hardware identity untuk station LAN bersifat read-only di Admin.

## Monitoring realtime

Tab desktop:

```text
Recent | Tabular | Chart | Reports | Alarm | Logs
```

`Recent` membaca snapshot `vrecent`. Refresh UI/live monitoring default **2 detik**. Chart dan Reports menggunakan history `measurement`.

Tombol **Monitoring** membuka Grafana Playlist `Realtime -> Trends -> Operations`. Dashboard refresh **2 detik**, sedangkan perpindahan Playlist **10 detik**.

## Alarm response

Tab Alarm menampilkan event operator-facing dari Alarm Policy, bukan sekadar setiap raw row source. Untuk menangani event:

1. Pilih alarm aktif.
2. Klik **Response / Silence**.
3. Isi Action, PIC, Note/Reason, dan PIN bila diminta.
4. Submit.
5. Pastikan event berubah menjadi responded dan source health tetap normal.

Source write-through mengisi `i_op`, `pic`, `note`, dan `i_flag=1`. Kolom legacy `ack` tidak diubah oleh RadMon.

Jika source sedang offline, central menyimpan state retry dan mencoba kembali dengan backoff terbatas. Jangan membuat response kedua hanya karena source belum pulih.

## Alarm Policy

Episode HIGH mengikuti aturan maksimum tiga surfaced ALARM dalam window lima menit yang di-anchor ke ALARM #1. Setelah ALARM #3, detector masuk `RETRIGGER_LOCKED`. Hanya pembacaan `NORMAL` di bawah LOW/WARN yang mereset episode; `ALERT` tidak mereset.

Historical/backfill alarm tetap disimpan sebagai evidence tetapi tidak menjadi notifikasi operator baru.

## Timed Alarm Suppression

Administrator/Operator dapat memilih **Suppress Alarm...** untuk detector tertentu.

- Durasi 1 menit sampai 24 jam.
- PIN, PIC, dan reason wajib.
- Hanya satu active suppression per detector.
- Auto Resume on NORMAL dapat digunakan.
- Dose measurement tetap berjalan dan nilai aktual tetap terlihat.
- Satu sesi suppression menghasilkan paling banyak satu event `SUPPRESSED` walaupun HIGH berulang.
- `SUPPRESSED` tidak dikirim sebagai alarm WhatsApp baru.

## Reports

Workflow report:

```text
Preview -> Print / Export PDF / Export CSV
```

Reports dapat membaca data aktif maupun quarterly archive yang sudah terverifikasi. Jangan memodifikasi file archive secara manual.

## Grafana

Jika tombol Monitoring gagal membuka dashboard:

1. pastikan Docker Desktop berjalan;
2. cek status Grafana bootstrap/log;
3. pastikan central MariaDB dapat diakses;
4. jangan mengubah file provisioning di paket tanpa prosedur maintenance.

## WhatsApp

WhatsApp alarm default OFF. Jika diaktifkan, dispatcher hanya mengirim active unsent policy ALARM. `SUPPRESSED`, responded, historical seed, dan retrigger-locked state tidak dikirim sebagai alarm baru.

## Upgrade operator

Sebelum upgrade:

1. tutup RadMon;
2. backup folder instalasi;
3. pertahankan `config\.env`, `runtime\`, `archives\`, dan `reports\`;
4. ganti aplikasi dengan artifact baru;
5. jalankan `app\RadMon.exe` dan lakukan commissioning singkat.

Jangan menghapus security DB, checkpoint, audit, archive, report, atau konfigurasi production ketika memperbarui aplikasi.
