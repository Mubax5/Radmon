# User Manual

## Cara mengakses RadMon

Server production berjalan otomatis melalui Scheduled Task Windows. User tidak perlu membuka `RadMon.exe` untuk membuat collector/API tetap hidup.

### Monitoring tanpa login

Dari network BRIN/LAN yang diizinkan buka:

```text
http://192.168.1.2:8090/
```

Alamat tersebut langsung membuka Grafana Playlist fullscreen/kiosk. Halaman ini tidak memiliki tombol Sign in RadMon, sidebar RadMon, atau fitur kontrol. Anonymous Grafana adalah read-only Viewer.

### RadMon Control Plane

Untuk fitur aplikasi buka:

```text
http://192.168.1.2:8090/app
```

Semua role RadMon **wajib login**, termasuk Viewer.

- **Viewer** — Overview, Stations, History, Archives/Reports read-only.
- **Operator** — Viewer + Alarm, Response/Silence, Suppression.
- **Administrator** — Operator + user/station/system administration dan Grafana administration.

Permission write selalu diverifikasi di backend; menyembunyikan menu di browser bukan mekanisme security.

## Tampilan web

Control Plane memakai design system Cloudflare **Kumo UI**. Sidebar hanya menampilkan menu yang diizinkan role user. Menutup browser tidak menghentikan server RadMon.

Overview menampilkan jumlah station `NORMAL`, `WARNING`, `ALARM`, dan `OFFLINE` beserta dose aktual. Stations dan History membaca central MariaDB; source production tetap `.50`, `.52`, `.38` dan schema source tidak dimodifikasi.

## Grafana monitoring dan editing

Monitoring public-BRIN dan editor memakai state dashboard Grafana yang sama.

Untuk editing, Administrator bekerja dari PC server dan membuka:

```text
http://localhost:3300
```

Login Grafana default adalah `admin/admin` bila belum diubah. Setelah dashboard diedit dan **Save**, hasil itu menjadi state authoritative dan langsung dipakai monitoring. RadMon tidak melakukan overwrite factory setiap startup.

Dashboard factory hanya dibuat bila UID dashboard belum ada. Dashboard lama yang masih `editable=false` dapat dibuka editing melalui migrasi satu kali yang mempertahankan panel/layout/query tersimpan.

Restart berikut **tidak boleh** menghapus hasil edit:

```text
RadMon restart
Grafana restart
Windows reboot
installer upgrade
```

Port Grafana production tetap `3300`. Bila port dipakai aplikasi lain, RadMon melaporkan konflik dan tidak pindah diam-diam ke 3301/3302.

## Alarm response

Operator dan Administrator dapat menangani Alarm Policy event. Aksi sensitif tetap memerlukan PIN.

Workflow operasional:

1. Buka **Alarms**.
2. Periksa event, detector, underlying dose, dan source health.
3. Response/Silence hanya dilakukan oleh role yang berhak.
4. Isi Action, PIC, Reason/Note, dan PIN.
5. Backend memvalidasi session, role, PIN, serta state event sebelum source write-through.

Source response mengisi `i_op`, `pic`, `note`, dan `i_flag=1`; legacy `ack` tidak diubah RadMon. Bila source offline, central menyimpan retry dengan backoff terbatas dan operator tidak perlu membuat response duplikat.

## Alarm Policy

Episode HIGH maksimum menghasilkan tiga surfaced ALARM dalam window lima menit yang di-anchor ke ALARM #1. Setelah ALARM #3, detector masuk `RETRIGGER_LOCKED`. Hanya pembacaan `NORMAL` di bawah LOW/WARN yang mereset episode; `ALERT` tidak mereset.

Historical/backfill alarm disimpan sebagai evidence tetapi tidak menjadi notifikasi operator baru.

## Timed Alarm Suppression

Administrator/Operator dapat menjalankan suppression detector:

- durasi 1 menit sampai 24 jam;
- PIN, PIC, reason wajib;
- hanya satu active suppression per detector;
- Auto Resume on NORMAL opsional;
- measurement/dose aktual tetap berjalan dan terlihat;
- satu sesi suppression maksimal satu event `SUPPRESSED`;
- `SUPPRESSED` tidak menjadi alarm WhatsApp baru.

## Reports dan Archives

Reports mempertahankan workflow:

```text
Preview -> Print / Export PDF / Export CSV
```

Quarter archive yang sudah terverifikasi dapat dibaca tanpa restore SQL. Jangan memodifikasi bundle archive secara manual.

## Administrasi user

Administrator mengelola user RadMon. Viewer bukan anonymous; Viewer mempunyai username/password/session sendiri. Password dan PIN tersimpan sebagai salted hash di `runtime\radmon-security.db`.

Untuk first installation headless, Administrator pertama dapat dibootstrap melalui `config\.env`; setelah user terbentuk, credential bootstrap sebaiknya dihapus dari file config.

## Operasi server 24/7

Scheduled Task **RadMon Server** berjalan sebagai SYSTEM saat Windows startup dengan argument:

```text
app\RadMon.exe --server
```

Task dikonfigurasi restart otomatis bila proses berhenti. Browser/desktop user tidak menjadi lifecycle owner server.

Jika server tidak dapat diakses:

1. cek Scheduled Task `RadMon Server`;
2. cek `runtime\logs`;
3. cek port `8090` dan `3300`;
4. cek Grafana native / `RADMON_GRAFANA_BIN`;
5. cek central/source MariaDB;
6. jangan membunuh semua proses Python atau menghapus `runtime` secara membabi buta.

## Upgrade

Installer baru boleh mengganti application files, tetapi harus mempertahankan:

```text
config\.env
runtime\
archives\
reports\
```

Setelah upgrade, Scheduled Task otomatis didaftarkan ulang. Lakukan commissioning singkat untuk monitoring, login/RBAC, source health, alarm response/suppression, Grafana editing/persistence, dan report.

## WhatsApp

WhatsApp default OFF. Jika diaktifkan, dispatcher hanya mengirim active unsent policy ALARM; `SUPPRESSED`, responded event, historical seed, dan retrigger-locked state tidak dikirim sebagai alarm baru.
