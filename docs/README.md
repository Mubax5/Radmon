# Dokumentasi RadMon

Dokumentasi ini menjelaskan perilaku RadMon pada source baseline yang diaudit.
Ia tidak membuktikan bahwa konfigurasi jaringan, credential, atau hardware pada
PC production sudah benar.

**Baseline dokumentasi:** `403efbce`, 8 Oktober 2026. Commit tersebut hanya
menyegarkan evidence audit; hasil CI dan test bukan bukti deployment production.

## Mulai dari sini

| Kebutuhan | Dokumen |
| --- | --- |
| Memahami arsitektur dan batas data | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Memasang Windows production | [INSTALLATION.md](INSTALLATION.md) |
| Menjalankan atau memulihkan layanan | [OPERATOR-STARTUP-ID.md](OPERATOR-STARTUP-ID.md) |
| Menggunakan Control Plane | [USER-MANUAL.md](USER-MANUAL.md) |
| Mengelola user, stasiun, Grafana, dan backup | [ADMIN-GUIDE-ID.md](ADMIN-GUIDE-ID.md) |
| Memahami automatic updater dan rollback | [UPDATER-ID.md](UPDATER-ID.md) |
| Menggunakan endpoint API | [API-REFERENCE.md](API-REFERENCE.md) |
| Mendiagnosis gangguan | [TROUBLESHOOTING-ID.md](TROUBLESHOOTING-ID.md) |
| Meninjau security evidence dan residual risk | [SECURITY-REVIEW-ID.md](SECURITY-REVIEW-ID.md) |

## Manual yang ikut installer

Installer menyalin hanya manual HTML dan stylesheet berikut ke
`app\docs\manual\`. Keduanya dapat dibuka offline dan mempunyai navigasi
bersama:

- [Manual operator](manual/user-manual.html)
- [Panduan instalasi](manual/installation.html)

File Markdown di atas adalah referensi source checkout. Untuk operasi harian,
ikuti manual HTML atau panduan operator Bahasa Indonesia.

## Aturan membaca status

- **Verified in source/CI** berarti perilaku dibuktikan oleh source atau test.
- **Commissioning required** berarti harus diuji pada PC `.2`, source LAN,
  jaringan BRIN-NET, Grafana native, database, atau hardware yang sebenarnya.
- **Residual risk** berarti belum boleh ditulis sebagai risiko yang selesai.

Jangan memasukkan password, PIN, token bearer, cookie, dump database, atau
credential datasource ke dokumen, issue, maupun log yang dibagikan.
