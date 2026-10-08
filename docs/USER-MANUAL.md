# User Manual

## Cara mengakses RadMon

Server production berjalan otomatis melalui Scheduled Task Windows. User tidak perlu membuka `RadMon.exe` untuk membuat collector/API tetap hidup.

### Monitoring remote dengan session RadMon

Dari network BRIN/LAN yang diizinkan buka:

```text
https://monitoring.example/
```

Alamat tersebut membuka Grafana Playlist fullscreen/kiosk setelah login session
RadMon. Remote anonymous tidak didukung; Grafana direct/anonymous hanya boleh
berada di loopback server dan port 3300 tidak boleh dibuka ke LAN.

### RadMon Control Plane

Untuk fitur aplikasi buka:

```text
https://monitoring.example/app
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

Monitoring remote yang sudah authenticated dan editor memakai state dashboard
Grafana yang sama.

Untuk editing, Administrator bekerja dari PC server dan membuka:

```text
http://localhost:3300
```

Login Grafana harus memakai secret yang dikelola operator; `admin/admin`,
kosong, atau secret lemah akan memblokir managed bootstrap. Setelah dashboard
diedit dan **Save**, hasil itu menjadi state authoritative dan langsung dipakai
monitoring. RadMon tidak melakukan overwrite factory setiap startup.

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

Source response memilih exact row `(serid, dtoa)`, mengisi `i_op`, `pic`, `note`, dan `i_flag=1`; legacy `ack` tidak diubah RadMon. Central membaca kembali row source yang sama setelah commit sebelum menampilkan sukses. Bila row sudah `i_flag=1`, hasilnya diberi label sudah ditangani sebelumnya; bila source offline, timeout, row berubah, atau read-back gagal, alarm tetap ditampilkan sebagai error aktif. Central menyimpan retry dengan backoff terbatas dan operator tidak perlu membuat response duplikat. SQL tidak membuktikan bunyi buzzer fisik sudah berhenti; acceptance hardware harus dilakukan saat commissioning.

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

Updater terverifikasi men-stage release lama dan memeriksa marker/readiness;
jika gagal, release lama dipulihkan. Application files boleh diganti, tetapi
harus mempertahankan:

```text
config\.env
runtime\
archives\
reports\
```

Setelah upgrade, Scheduled Task otomatis didaftarkan ulang. Lakukan commissioning singkat untuk monitoring, login/RBAC, source health, alarm response/suppression, Grafana editing/persistence, dan report.

## WhatsApp

WhatsApp default OFF. Jika diaktifkan, dispatcher hanya mengirim active unsent policy ALARM; `SUPPRESSED`, responded event, historical seed, dan retrigger-locked state tidak dikirim sebagai alarm baru.
