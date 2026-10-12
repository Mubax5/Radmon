# Status deployment HTTPS RadMon

## Status nyata pada central PC

Deployment selesai pada host `10.10.140.101` tanpa mematikan guard
authentication remote:

```text
https://10.10.140.101/       Grafana monitoring, session RadMon wajib
https://10.10.140.101/app    RadMon Control Plane, session RadMon wajib
http://10.10.140.101:8090    Navigasi `/` dan `/app*` redirect ke HTTPS; POST login tetap ditolak
http://127.0.0.1:3300        Grafana native/editor lokal saja
```

TLS diterminasi oleh Caddy `v2.11.7` pada TCP `443`, lalu hanya meneruskan
request ke RadMon `127.0.0.1:8090`. Port `80` tidak diambil alih dan port
Grafana `3300`, Grafana lain `3000`, MariaDB, serta port instance `47652` tidak
diubah.

Konfigurasi RadMon yang diterapkan secara atomik pada
`%LOCALAPPDATA%\RadMon\config\.env` hanya menambahkan/menguatkan:

```env
RADMON_WEB_COOKIE_SECURE=1
RADMON_TRUSTED_PROXY_NETS=127.0.0.1/32
RADMON_WEB_ALLOWED_ORIGINS=https://10.10.140.101
```

Tidak ada wildcard proxy/origin. Navigasi GET/HEAD remote ke `/`, `/app`, dan
`/app/*` pada URL lama `:8090` diarahkan ke origin HTTPS exact; API, health,
Grafana, local loopback, dan plaintext POST login tidak di-redirect. Caddy
menimpa `X-Forwarded-Proto` menjadi
`https`, meneruskan WebSocket melalui `reverse_proxy`, membatasi request body
menjadi 32 MiB, dan access log menghapus header `Cookie`, `Authorization`, dan
`Proxy-Authorization`. HSTS belum dipasang sebelum trust client diselesaikan.

## Sertifikat dan trust client

Saat ini digunakan Caddy internal CA khusus RadMon, bukan sertifikat enterprise
atau public CA. CA publiknya berada di:

```text
%LOCALAPPDATA%\RadMon\https\public\RadMon-HTTPS-RootCA.cer
```

File publik yang sama tersedia melalui route HTTPS eksplisit:

```text
https://10.10.140.101/__radmon-ca/RadMon-HTTPS-RootCA.cer
```

Fingerprint SHA-256 CA publik:

```text
2E:EE:9B:5F:48:B6:E9:26:A1:C3:9B:6E:8D:1D:98:74:79:D2:16:58:D8:46:3F:D5:37:BC:C0:C3:A8:BE:94:89
```

Operator harus memindahkan file melalui kanal yang disetujui, memverifikasi
fingerprint di atas, lalu dengan persetujuan Administrator pada **setiap
client** memasangnya ke `Trusted Root Certification Authorities`, misalnya:

```powershell
certutil.exe -addstore -f Root .\RadMon-HTTPS-RootCA.cer
```

Jangan memasang private key, jangan memakai `tls_skip_verify`, dan jangan
menganggap CA ini otomatis dipercaya seluruh PC. Jika organisasi menyediakan
DNS dan sertifikat enterprise dengan SAN yang sesuai, CA ini harus diganti
melalui change yang disetujui. Private key Caddy berada di storage data yang
ACL-nya hanya `SYSTEM` dan `Administrators`; tidak pernah disajikan oleh route
sertifikat atau disimpan di repository.

## Startup, renewal, dan bukti verifikasi

Scheduled Task `RadMon HTTPS` menjalankan Caddy sebagai `SYSTEM`, memakai
`MultipleInstances=IgnoreNew`, restart bounded, dan menyimpan CA/certificate
state di `%LOCALAPPDATA%\RadMon\https\data`. Caddy menangani renewal leaf
certificate secara otomatis. Task `RadMon Server` juga telah dipastikan
menjalankan RadMon sebagai `SYSTEM`; tidak ada loop start ganda.

Bukti read-only setelah deployment:

- listener `10.10.140.101:443` milik Caddy dan `0.0.0.0:8090` milik RadMon;
- CA-file validation berhasil untuk TLS 1.2 dan TLS 1.3, termasuk SAN leaf
  `IP Address:10.10.140.101`;
- `/health` HTTPS `200`, `/app` HTTPS `200`, route CA publik `200`, dan root
  HTTPS melakukan redirect canonical `307`;
- request login dummy tanpa credential operator melalui HTTP LAN mendapat
  `426 remote authentication requires HTTPS`; tidak ada login operator,
  password, PIN, alarm, acknowledgement, suppression, atau userdata yang
  dijalankan;
- Grafana `127.0.0.1:3300/api/health` dan `127.0.0.1:3000/api/health` tetap
  `200`;
- fixture security `tests/test_security_hardening.py` dan
  `tests/test_secure_api.py`: `19 passed`.

Trust browser client dan login operator HTTPS nyata tetap memerlukan tindakan
operator pada client. Bukti ini tidak mencakup acceptance browser dari PC lain,
buzzer fisik, atau commissioning source LAN.
