# Review keamanan RadMon (ID)

**Tanggal review:** 8 Oktober 2026  
**Baseline:** `127c1907`  
**Status:** implementasi sudah diverifikasi di workspace dan belum dideploy ke
produksi. Dokumen ini adalah catatan engineering dan readiness, bukan sertifikasi
keamanan atau jaminan tidak ada kerentanan yang belum diketahui.

## Ruang lingkup

Review mencakup backend FastAPI/API dan auth/session, gateway Grafana dan proxy
header, archive/report dan worker, LAN/source health, audit/config, central
bearer token, Windows updater/installer, dependency evidence, regression test
keamanan, dan integrasi UI yang ada di workspace. Perubahan UI dibatasi pada
pekerjaan concurrent yang sudah ada dan perbaikan kontrak test; `logs/` untracked
yang sudah ada dipertahankan.

## Temuan dan mitigasi

| Risiko | Kondisi yang dieksploitasi | Mitigasi pada source | Status |
|---|---|---|---|
| Brute-force login | Penyerang dapat mengulang password dari satu IP atau banyak IP tanpa throttling yang konsisten | Counter atomik per-IP dan per-IP+username; akun tidak dikunci global; respons dan audit rate-limit dibatasi | Fixed, perlu uji runtime dari jaringan produksi |
| CSRF dan browser hardening | Browser korban mengirim mutasi auth/control dari origin lain | Validasi `Origin`/`Referer`/Fetch Metadata, SameSite/HttpOnly cookie, CSP dan security headers | Fixed |
| Spoofed forwarded identity / Grafana exposure | Header forwarded dari peer tak tepercaya dapat memalsukan client; proxy Grafana dapat menjadi jalan ke API/query/admin | Forwarded header hanya dipercaya dari network eksplisit; remote Grafana memerlukan session RadMon, memblokir endpoint login/admin/write/datasource-management, membuang credential Grafana dari client, dan native maupun Docker fallback Grafana bind loopback | Fixed secara kode; TLS, published read-only boundary, dan datasource least privilege tetap harus diverifikasi |
| Kebocoran data alarm | Viewer menerima PIC, notes, action, atau metadata operator | Read model allowlist hanya field alarm yang aman; route operator dipisahkan | Fixed |
| Path traversal, symlink, ZIP/SQL/resource abuse | User mengontrol pilihan archive/report atau artifact dan dapat membaca/menulis di luar root, membuat decompression/row/byte overload, atau menjalankan SQL arbitrary | Canonical path + symlink checks, ZIP manifest/bounds, SQL statement allowlist, row/byte/partition/line limits, preflight, pending-job limits, artifact temp-then-rename | Fixed, perlu uji corpus archive rusak di deployment |
| Unauthenticated Grafana fallback | Bootstrap lama dapat jatuh ke akses yang salah saat auth Grafana gagal | Fallback unauthenticated setelah auth failure dihapus; kegagalan Grafana tidak menurunkan auth Control Plane | Fixed; kompatibilitas TV anonim remote berubah menjadi session-required |
| Updater merusak release aktif | Installer menghapus `app` lalu gagal sebelum marker/readiness; server tertinggal memakai tree rusak | Updater menghentikan proses terverifikasi, memindahkan tree lama ke `runtime/updates/<sha>/previous-app`, menjalankan installer, memeriksa marker dan health stabil, lalu memulihkan tree lama saat gagal. Failed tree dipindahkan, bukan dihapus massal. `[InstallDelete]` dihapus | Fixed secara kode; rollback smoke test Windows wajib sebelum persetujuan produksi |
| Default Grafana `admin/admin` | Installer/config baru atau legacy memberi credential yang dapat ditebak | Template memakai `GENERATE_ON_FIRST_START`; first start membuat secret unik atomik dan membatasi mode file best-effort; `admin`, kosong, atau secret lemah memblokir bootstrap Grafana managed. Nilai legacy tidak dirotasi diam-diam | Fixed untuk instalasi baru; legacy harus dimitigasi operator |
| Session cookie melalui HTTP remote | Cookie non-Secure dapat disadap pada LAN bila gateway HTTP digunakan | `RADMON_WEB_COOKIE_SECURE=1` sebagai default; remote production login tanpa HTTPS ditolak, termasuk konfigurasi secure flag yang salah; loopback HTTP tetap tersedia untuk recovery lokal | Fixed secara guard; TLS belum dipasang di server |
| Source tampak OFFLINE karena policy/cache error | Exception policy dari cycle live mengalir ke state connectivity | `remote_connected` dan `policy_state` dipisah. Source yang menjawab tetap `CONNECTED` dengan `policy_state=DEGRADED`; kegagalan konektivitas tetap menaikkan DEGRADED/OFFLINE | Fixed dan dites |
| Worker menulis setelah shutdown | `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=False)` meninggalkan queued/active job yang dapat menulis setelah lifecycle API selesai | Queue tetap durable untuk recovery, queued future dibatalkan, active work diberi cancellation checkpoint dan bounded wait, artifact hanya dipublish atomic rename, partial temp dihapus | Fixed secara kode; timeout jaringan dan restart Windows harus diuji |

## Perubahan perilaku yang harus disetujui operator

1. Akses Grafana remote melalui RadMon `/` **tidak lagi anonymous**. Session
   RadMon wajib ada sebelum request Grafana dashboard/query diteruskan; cookie
   dan Authorization Grafana dari client tidak pernah diteruskan. Jangan
   menghapus session gate atau membuka API Grafana langsung hanya untuk
   memenuhi kebutuhan TV. Datasource Grafana harus memakai account database
   read-only dan published-monitor boundary tetap perlu disetujui serta diaudit.
2. Grafana langsung hanya untuk loopback/local recovery. Port 3300 tidak boleh
   dibuka ke LAN.
3. Production launcher memang memaksa `lan_enabled=True`; nilai
   `RADMON_LAN_ENABLED=0` pada template bukan kill-switch production. Jangan
   menganggap perubahan itu mematikan source collection atau source workflow;
   ubah mode tersebut hanya melalui desain dan approval deployment tersendiri.
4. Tidak ada 2FA/MFA yang ditambahkan dalam scope review ini.

## Matriks boundary route

| Boundary | Anonymous | Viewer | Operator | Administrator | Bukti |
|---|---:|---:|---:|---:|---|
| `/app`, asset SPA | shell saja | session | session | session | `secure_api`/`web_host` + UI suite |
| `/api/v1/web/*` | tolak | baca sesuai role | baca | baca | `tests/test_web_role_matrix.py`, full pytest |
| `/api/v1/control/alarms` | tolak | allowlist read-only | allowlist read-only | allowlist read-only | `test_security_hardening.py` |
| alarm response/suppression/station edit | tolak | tolak | role + PIN | role + PIN | `test_secure_api.py`, alarm suites |
| user/audit/archive retry | tolak | tolak | tolak | role + PIN bila sensitif | `user_admin.py`, full pytest |
| Grafana via remote `/` | tolak | session | session | session | `web_host.py`, `test_web_platform_contract.py` |
| Grafana direct | loopback only | Grafana auth/anonymous local boundary | sama | admin lokal | bind `127.0.0.1`, no LAN publish |

Grafana anonymous viewer yang dipakai untuk dashboard gateway bukan boundary
remote: Grafana hanya bind loopback, credential client dibuang, dan request
remote tanpa session RadMon ditolak. Port 3300 tidak boleh dipublish ke LAN.

## Bukti validasi

Validasi yang tersedia pada workspace:

- `py -3 -m compileall -q radmon` berhasil.
- Full pytest setelah integrasi: **684 passed, 1 skipped, 39 warnings**.
  Dua contract assertion lama direkonsiliasi terhadap semantik UI yang benar;
  tidak ada failure backend/security/UI contract yang tersisa.
- Frontend `npm.cmd run check` dan `npm.cmd run build` berhasil.
- Test UI: **20 passed** (7 UI state, 5 dialog, 2 format, 6 notification).
- `packaging/radmon_update.ps1 -SelfTest`: **passed**, termasuk simulated
  rollback tree aplikasi dan stable readiness gate.
- `npm.cmd audit --package-lock-only --omit=dev --json`: **0 vulnerability**
  pada 189 dependency production yang ter-resolve.
- `pip-audit` tidak tersedia di environment dan tidak di-install sesuai
  pembatasan task. Dependensi Python belum memiliki evidence audit setara.
- Browser executable/Playwright tidak tersedia; tidak ada klaim visual live.
- Tidak ada deploy, restart production, perubahan credential production,
  perubahan certificate, atau perubahan firewall yang dilakukan.

## Checklist sebelum deployment

- [ ] Owner menyetujui remote Grafana session requirement dan menyediakan URL
  reverse proxy HTTPS yang benar.
- [ ] TLS termination, certificate renewal, HSTS policy, dan forwarded-proto
  allowlist diuji; `RADMON_TRUSTED_PROXY_NETS` hanya berisi network proxy yang
  benar-benar dimiliki.
- [ ] `RADMON_WEB_ALLOWED_ORIGINS` diisi origin HTTPS resmi; jangan memakai
  wildcard atau origin yang tidak dikuasai.
- [ ] Secret Grafana legacy (`admin` atau nilai lemah), DB, bootstrap admin,
  dan token central dirotasi melalui change yang disetujui. Jangan menaruh
  secret nyata di repository/log.
- [ ] ACL Windows pada `config/.env`, `runtime`, archive, report, dan security
  DB dibatasi ke service account/Administrator yang diperlukan; mode `0600`
  dari generator bukan pengganti review ACL NTFS.
- [ ] MariaDB memakai account least-privilege; transport encryption,
  certificate verification, plugin auth yang didukung connector, firewall,
  dan network ACL diverifikasi untuk central serta setiap source LAN.
- [ ] Port 8090 dibatasi sesuai network boundary; Grafana 3300 tetap loopback.
- [ ] Backup security DB, measurement DB, archive, report, dan Grafana state
  diuji restore; retention lima tahun dan jadwal restore drill memiliki owner.
- [ ] Windows CI/package smoke menjalankan updater self-test, simulated
  installer failure, marker mismatch, readiness timeout, rollback, preserved
  config/DB/archive/report, dan start ulang release lama.
- [x] Full backend tests, `npm.cmd run check`, frontend build, dan seluruh test
  UI yang tersedia sudah dijalankan setelah integrasi.
- [ ] Validasi visual browser pada 360/768/1280/1366 px oleh owner UI atau CI
  browser; static CSS review bukan pengganti visual runtime.
- [ ] Setelah approval, lakukan canary upgrade dan pantau audit login,
  source-health transitions, archive/report jobs, serta orphan temp artifacts.

## Residual risk dan area yang belum terverifikasi

- Source code tidak dapat membuktikan konfigurasi TLS, firewall, ACL NTFS,
  account/database privilege, certificate expiry, physical buzzer, atau
  apakah source LAN benar-benar aktif pada deployment produksi.
- MariaDB transport encryption dan authentication plugin compatibility masih
  bergantung pada connector/server setting; Grafana bootstrap sekarang gagal
  tertutup bila datasource tetap unhealthy, tetapi tidak dapat memperbaiki
  plugin yang tidak didukung tanpa perubahan operasional.
- Updater rollback aman terhadap tree milik RadMon dalam desain script, tetapi
  belum dieksekusi terhadap installer Windows nyata pada mesin produksi.
  Migration/schema yang tidak backward-compatible tidak boleh di-rollback
  secara buta; migration gate dan backup restore tetap menjadi kewajiban.
- Worker shutdown memiliki bounded wait. Jika driver/database call melanggar
  timeout, proses worker dapat tetap hidup di luar batas dan harus ditangani
  oleh service supervisor; hal itu bukan bukti data corruption sudah mustahil.
- Dependency scan Python tidak tersedia, browser/Windows packaging CI dan
  runtime production belum seluruhnya dijalankan dalam audit ini.
- `FastAPI/Starlette` mengeluarkan deprecation warning untuk `on_event`; ini
  bukan failure keamanan, tetapi migrasi ke lifespan API sebaiknya masuk backlog.
- Review ini mengurangi vulnerability yang terkonfirmasi dari source dan test,
  tetapi tidak dapat menjamin tidak ada vulnerability baru atau unknown.
