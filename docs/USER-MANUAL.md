# Manual pengguna RadMon

## Tujuan

RadMon membantu operator melihat status stasiun, meninjau pembacaan asli,
menangani alarm sumber, membuat laporan, dan memeriksa kesehatan source LAN.
Manual ini menjelaskan workflow yang dapat dilakukan user; konfigurasi server
dan perubahan credential berada di [Panduan Administrator](ADMIN-GUIDE-ID.md).

## Prasyarat dan role

Semua role harus mempunyai akun RadMon dan login. Remote anonymous tidak
didukung.

| Role | Menu dan tindakan |
| --- | --- |
| Viewer | Ringkasan, Stasiun, Riwayat, Arsip, dan data baca-saja. |
| Operator | Viewer + Laporan, Alarm, response/silence, suppression, dan edit konfigurasi stasiun dengan PIN. |
| Administrator | Operator + Pengguna, Sistem, retry archive, dan editor Grafana lokal. |

PIN harus 4–8 digit. Password user harus 8–256 karakter. Hak yang terlihat di
browser bukan pengganti pemeriksaan role di backend.

## Masuk ke RadMon

Dari client BRIN-NET yang mempunyai route ke server, buka alamat HTTPS yang
disediakan owner, misalnya:

```text
https://monitoring.example/app
```

Login `/app` menampilkan Control Plane. Landing monitoring Grafana memakai
session RadMon yang sama:

```text
https://monitoring.example/
```

Di PC server, Administrator dapat membuka Grafana native melalui
`http://127.0.0.1:3300`. Port tersebut bukan alamat remote.

**Hasil yang diharapkan:** setelah login, sidebar hanya menampilkan menu yang
diizinkan role. Menutup browser tidak menghentikan server.

## Ringkasan, Stasiun, dan Riwayat

1. Buka **Ringkasan** untuk jumlah `NORMAL`, `WARNING/ALERT`, `ALARM`, dan
   `OFFLINE`.
2. Buka **Stasiun** untuk mencari nama, lokasi, atau SERID. Pilih stasiun untuk
   melihat pembacaan terakhir, umur data, threshold, dan konteks offline.
3. Buka **Riwayat** untuk melihat sampel historis. Rentang ini bukan rolling
   three-hour Grafana view dan dapat membaca `measurement`.

Jika stasiun offline, nilai terakhir boleh tetap terlihat sebagai last-known
value. Cocokkan selalu nilai dengan timestamp dan umur aslinya. RadMon tidak
membuat nilai baru, timestamp baru, atau garis trend datar untuk menutupi
kehilangan data.

## Alarm: bedakan policy central dan alarm source

Pada halaman **Alarm**, event policy central adalah evidence operator-facing;
baris alarm source adalah evidence dari alat. **Tombol respons source hanya
berlaku untuk baris source yang masih `i_flag=0`.** Alarm policy HIGH di central
tidak dengan sendirinya menjadi target response source.

### Menangani alarm source

1. Buka **Alarm** dan periksa source, SERID, waktu event, nilai, threshold, dan
   source health.
2. Pastikan baris yang dipilih adalah alarm source aktif dengan `i_flag=0`.
3. Pilih **Response/Silence**, isi Action, PIC, catatan/alasan, dan PIN.
4. Kirim satu kali dan tunggu konfirmasi read-back.
5. Muat ulang bila perlu dan catat hasil pada log operasional.

**Hasil sukses:** backend menulis `i_op`, `pic`, `note`, dan `i_flag=1` pada
row `(serid, dtoa)` yang dipilih, commit, lalu membaca row yang sama. Field
legacy `ack` tidak diubah.

**Pengecualian:**

- `ALREADY_HANDLED` berarti row exact sudah `i_flag=1`; jangan membuat response
  duplikat.
- Source timeout, row berubah, commit gagal, atau read-back gagal berarti
  response belum terbukti; alarm tetap dianggap aktif/error.
- Source silence yang dipicu suppression dapat dicoba kembali oleh worker dengan
  backoff terbatas. Operator response biasa tidak diulang secara buta setelah
  hasil tidak pasti; tunggu observasi source/reconciliation sebelum tindakan
  berikutnya. Jangan menyimpulkan bunyi sudah berhenti hanya dari status lokal.
- SQL/read-back hanya membuktikan state database. Buzzer fisik harus diterima
  pada detector saat commissioning dan itu bukan sertifikasi keamanan.

### Suara dan notifikasi

Klik **Aktifkan suara alarm** dari halaman Alarm jika browser meminta izin
audio/notifikasi. Izin browser dapat ditolak oleh kebijakan workstation.
Notifikasi dalam aplikasi dan status source tetap harus diperiksa; suara browser
tidak membuktikan penerimaan buzzer hardware.

## Timed suppression

Gunakan suppression hanya setelah memastikan alasan operasionalnya:

1. Pilih stasiun pada bagian tindakan operator.
2. Isi durasi **1 menit sampai 24 jam**, PIC, reason, dan PIN.
3. Pilih opsi auto-resume saat kondisi kembali `NORMAL` bila sesuai prosedur.
4. Simpan dan pastikan status suppression serta waktu kedaluwarsa tampil.

Measurement dan dose tetap dikumpulkan selama suppression. Satu sesi menghasilkan
paling banyak satu event `SUPPRESSED`. Suppression tidak membuat alarm WhatsApp
baru. Untuk mengakhiri lebih awal, gunakan **Akhiri suppression** dengan PIN dan
alasan.

## Laporan

### Workflow

1. Buka **Laporan** (Operator atau Administrator).
2. Pilih stasiun, waktu mulai, dan waktu selesai dalam WIB.
3. Pastikan waktu selesai setelah mulai dan rentang elapsed tidak lebih dari
   **24 jam**. Tepat 24 jam diperbolehkan.
4. Baca pratinjau sebelum menekan **Buat laporan**.
5. Tunggu status job `Selesai`, lalu pilih **Tampilkan PDF** atau **Unduh PDF**.

Preview menampilkan paling banyak **250 baris** dan harus diperlakukan sebagai
**partial preview**. Summary dapat dihitung dari seluruh rentang, tetapi detail
yang terlihat pada preview bukan seluruh baris.

PDF penuh berisi seluruh measurement pada rentang yang dipilih sampai batas
**50.000 measurement** dan seluruh alarm sampai batas **10.000 alarm**. Jika
data melebihi batas atau preflight menemukan data tidak lengkap, job gagal dan
meminta rentang lebih sempit; RadMon tidak menerbitkan PDF penuh yang diam-diam
terpotong. Timestamp PDF ditulis sebagai WIB dan nilai dose rate ditampilkan
dengan dua desimal.

Pada aplikasi desktop, workflow report tetap **Preview → Print / Export PDF /
Export CSV**. Jangan menyebut preview sebagai export penuh.

## Arsip

Viewer dapat membaca inventory dan recap archive yang sudah `COMPLETE`.
Operator/Administrator dapat meminta export SQL archive sesuai haknya. Jangan
mengubah ZIP, `manifest.json`, atau SQL bundle secara manual. Archive export
tidak sama dengan restore database; restore harus mengikuti prosedur
Administrator dan diuji terlebih dahulu.

## Jika Grafana menampilkan `No data`

Jangan langsung restart RadMon. Bedakan dua kondisi:

1. **Datasource error:** buka Grafana **Connections → Data sources → ipradmon →
   Save & test** atau minta Administrator memeriksa datasource health. Grafana
   dapat hidup sementara koneksi MariaDB `ipradmon` gagal.
2. **Query berhasil tetapi hasil kosong:** gunakan **Inspect → Query/Response**
   dan cek detector, datasource UID, query, serta current time window. Page
   **Trends** menggunakan rentang **Last 1 hour**; rentang itu tidak boleh
   diperluas secara buta menjadi history.

Untuk status dan pembacaan terakhir, pahami batas data berikut:

- `recent` adalah rolling hot window tiga jam;
- `recent_last` berisi paling banyak 30 pembacaan asli per detector untuk
  tampilan offline;
- `measurement` adalah history authoritative.

Jika offline, tampilkan last reading hanya bila data asli tersedia, dengan
timestamp dan umur asli. Tidak ada data bukan alasan untuk menginvent nilai.
Lihat [Troubleshooting](TROUBLESHOOTING-ID.md) sebelum meminta restart.

## Layanan 24/7 dan eskalasi

Scheduled Task **RadMon Server** menjalankan `app\RadMon.exe --server` sebagai
`SYSTEM` saat Windows boot. Jika halaman tidak dapat dibuka:

1. jalankan shortcut **RadMon** satu kali;
2. periksa status `/health`, task, port, log, Grafana, dan source health;
3. eskalasikan masalah MariaDB, routing, TLS, atau hardware kepada pemiliknya.

Jangan membunuh semua proses Python, menghapus `runtime`, menghapus database,
atau menghapus archive/report sebagai langkah coba-coba. Ikuti
[Panduan startup](OPERATOR-STARTUP-ID.md) dan [Troubleshooting](TROUBLESHOOTING-ID.md).
