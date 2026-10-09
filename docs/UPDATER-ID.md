# Automatic updater RadMon

## Tujuan

Pada instalasi Windows, task **RadMon Updater** memeriksa release channel
`latest` secara berkala. Updater hanya mengubah application tree setelah
release, ancestry, checksum installer, marker, dan readiness tervalidasi.

Dokumen ini menjelaskan kontrak updater pada source baseline `403efbce`; ia
tidak menyatakan release tertentu sudah terpasang di PC production.

## Perilaku normal

- Task updater dijalankan sebagai `SYSTEM` dan terjadwal setiap dua menit.
- `RADMON_AUTO_UPDATE` default aktif. Nilai `0`, `false`, `no`, `off`, atau
  `disabled` menonaktifkannya.
- Updater membaca `app\release.json` untuk SHA terpasang dan hanya menerima
  release remote yang merupakan descendant (`ahead`) dari SHA lokal.
- Installer dan checksum disimpan sementara di staging per-release.
- `config\.env`, `runtime`, `archives`, dan `reports` berada di luar application
  tree yang diganti.

## Urutan verifikasi

1. Baca marker release lokal dan ref release remote.
2. Bandingkan ancestry; release yang bukan descendant dilewati.
3. Unduh installer serta checksum ke staging per-release.
4. Cocokkan SHA-256 installer dengan checksum release yang sama.
5. Hentikan server terkelola, stage application tree lama, lalu jalankan
   installer silent.
6. Cocokkan SHA pada marker hasil instalasi dengan release yang diharapkan.
7. Tunggu `/health` `HTTP 200` dengan status `ok` sebanyak tiga pemeriksaan
   stabil dalam jendela readiness.
8. Jika berhasil, updater membersihkan staging lama sesuai lifecycle-nya.

## Jika upgrade gagal

Installer/checksum/marker/readiness yang gagal harus menghentikan upgrade.
Updater berusaha mengembalikan application tree sebelumnya dan meminta task
`RadMon Server` berjalan lagi. Application tree yang gagal dipindahkan ke nama
diagnostik, bukan dihapus secara massal sebelum dapat ditinjau.

Periksa:

```powershell
Get-ScheduledTask -TaskName "RadMon Updater"
Get-ScheduledTask -TaskName "RadMon Server"
Get-Content "$env:LOCALAPPDATA\RadMon\runtime\logs\radmon-updater.log" -Tail 120
```

Jika `/health` belum siap, jangan menganggap rollback sukses hanya karena task
terdaftar. Simpan pesan error, timestamp, status task, dan hasil health tanpa
membagikan credential atau isi `.env`; eskalasikan kepada Administrator.

## Batas tanggung jawab

Updater memverifikasi tree aplikasi dan readiness API. Ia tidak membuktikan
TLS, routing/ACL BRIN, privilege MariaDB, backup restore, source hardware,
physical buzzer, atau kecocokan perubahan schema yang tidak backward-compatible.
Lakukan canary/staging dan backup restore sebelum menyetujui upgrade production.
