# Panduan Administrator RadMon

## Tujuan dan batas peran

Gunakan panduan ini untuk perubahan administratif yang tidak dilakukan pada
database detector secara langsung. Semua role tetap login ke RadMon.

| Role | Hak utama |
| --- | --- |
| Viewer | Ringkasan, stasiun, riwayat, arsip, dan data baca-saja. |
| Operator | Viewer + laporan, alarm response/silence, suppression, dan edit konfigurasi stasiun dengan PIN. |
| Administrator | Operator + user, audit, system view, retry archive, serta akses editor Grafana lokal. |

PIN administratif harus 4–8 digit. Password user harus 8–256 karakter.
Perubahan sensitif mencabut session/lease yang terkait. Tidak ada 2FA/MFA pada
scope baseline ini.

## Kelola user

**Prasyarat:** login sebagai Administrator dan siapkan PIN Administrator saat
ini. Jangan menulis password/PIN nyata di tiket atau contoh.

1. Buka **Pengguna**.
2. Untuk membuat user, isi username, nama tampilan, role, password, PIN user,
   dan PIN Administrator.
3. Simpan, lalu minta user login ulang.
4. Untuk perubahan role/profil, reset password/PIN, nonaktifkan, aktifkan, atau
   hapus, buka user target dan konfirmasi tindakan dengan PIN Administrator.

**Hasil yang diharapkan:** user baru dapat login sesuai role; perubahan
profil/role berlaku setelah session lama dicabut. Audit tetap menyimpan
peristiwa administratif, termasuk setelah akun dihapus.

**Pengecualian:** username yang sudah dipakai ditolak; Administrator aktif
terakhir tidak boleh dinonaktifkan, diubah menjadi non-Administrator, atau
dihapus. Jika bootstrap admin gagal, periksa apakah security store sudah
mempunyai user sebelum mengubah `.env`.

## Kelola stasiun dan threshold

Operator atau Administrator dapat membuka **Stasiun** dan mengubah konfigurasi
pusat dengan PIN:

1. Pastikan SERID, nama, lokasi, dan sumber LAN sudah dicocokkan dengan
   perangkat yang sebenarnya.
2. Ubah threshold peringatan/alarm dan batas idle hanya berdasarkan keputusan
   operasional yang terdokumentasi.
3. Simpan, kemudian amati status dan timestamp pembacaan baru.

**Hasil yang diharapkan:** konfigurasi central berubah dan status monitoring
mengikuti nilai baru. RadMon tidak mengubah schema atau metadata pada database
source detector. Jangan membuat SERID duplicate atau menghapus stasiun yang
masih menjadi sumber history tanpa persetujuan pemilik data.

## Grafana lokal

1. Dari PC server, buka `http://127.0.0.1:3300`.
2. Login dengan credential Grafana yang dikelola operator.
3. Edit lalu **Save**.
4. Periksa monitoring melalui gateway setelah session RadMon login.

Saved dashboard/playlist menjadi authoritative state. Restart RadMon, Grafana,
Windows, atau upgrade tidak boleh mengembalikan layout yang sudah disimpan.
Port `3300` tetap loopback; jangan membuka firewall atau mengaktifkan akses
remote direct untuk mengatasi masalah tampilan.

**Jika datasource gagal:** pastikan endpoint, database, user least-privilege,
password secure field, transport encryption, dan certificate verification
sesuai kebijakan database. Gunakan **Save & test**; jangan menghapus datasource
atau database Grafana sebagai percobaan.

## Source health, alarm, dan buzzer

Periksa **System** atau **Sources health** sebelum menyimpulkan detector offline.
Kegagalan satu source tidak boleh menghentikan source lain.

Pada **Alarm**:

- event policy central dan source alarm adalah dua evidence berbeda;
- tombol respons source hanya untuk baris source yang masih `i_flag=0`;
- respons menulis `i_op`, `pic`, `note`, lalu memverifikasi `i_flag=1` pada row
  yang sama;
- `ack` legacy tidak diubah;
- SQL/read-back tidak membuktikan bunyi buzzer fisik berhenti.

Lakukan acceptance buzzer pada detector sebagai bagian commissioning. Acceptance
tersebut bukan sertifikasi keamanan atau bukti bahwa semua risiko runtime sudah
selesai.

## Arsip, report, dan backup

- Jalankan report dari **Laporan** dengan rentang WIB yang benar. Batas elapsed
  range adalah 24 jam; full report memuat semua data sampai batas 50.000
  measurement dan 10.000 alarm. Preview paling banyak 250 baris dan harus
  diberi label partial.
- Archive hanya boleh diekspor dari bundle `COMPLETE` yang sudah diverifikasi.
  Jangan mengedit ZIP, `manifest.json`, atau SQL bundle manual.
- Retry archive memerlukan Administrator PIN dan hanya mengulang lifecycle
  archive; ia bukan perintah untuk mempurge source.
- Backup harus mencakup security DB, central measurement DB, archive, report,
  dan state Grafana sesuai kebijakan owner. Uji **restore nyata** secara
  berkala; keberadaan file backup saja bukan bukti dapat dipulihkan.

## Production security checklist

Sebelum menyetujui penggunaan production, pastikan owner telah memiliki bukti
untuk:

- HTTPS termination, renewal certificate, HSTS, trusted proxy network, dan
  allowed origin yang tepat;
- firewall `8090` sesuai boundary BRIN-NET dan `3300` loopback-only;
- ACL NTFS least-privilege untuk `config`, `runtime`, archives, reports, dan
  security DB;
- rotasi password Grafana legacy, database, bootstrap admin, dan central token;
- account MariaDB least-privilege, transport encryption, certificate
  verification, authentication-plugin compatibility, firewall, dan ACL source;
- backup/restore security DB, measurement, archive, report, dan Grafana state;
- commissioning source health, alarm write-through, report, Grafana
  persistence, serta acceptance buzzer.

Source/test evidence dapat menurunkan risiko yang diketahui, tetapi tidak boleh
ditulis sebagai `100% secure`, tidak gagal, atau certified.
