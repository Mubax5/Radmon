# Grafana Monitoring

Grafana membaca tabel existing `device`, `measurement`, `recent`, dan `alarm` secara read-only. Tidak ada migration database.

Jika Docker Desktop tersedia, `RADMON.bat` dan `RUN_DUMMY.bat` mencoba menjalankan Grafana secara background dengan `docker compose up -d`; tidak ada console Grafana tambahan.

Jika Grafana sudah terpasang sendiri, import `dashboards/radiation-monitoring.json` dan gunakan datasource MySQL dengan UID `ipradmon-mysql`.

Untuk Docker, database pada komputer host harus dapat diakses dari container. Default host adalah `host.docker.internal`; ubah `RADMON_GRAFANA_DB_HOST` di `.env` jika MariaDB berada pada server lain.

Dashboard melakukan refresh setiap 2 detik. Gunakan akun Viewer/kiosk untuk layar monitoring umum.
