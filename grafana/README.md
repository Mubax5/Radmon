# Grafana Monitoring TV

Grafana membaca schema existing `device`, `measurement`, dan `alarm` secara read-only. Tidak ada migration database.

Dashboard TV dibuat oleh `radmon/grafana_tv.py` saat runtime, jadi tidak ada JSON dashboard duplikat yang bisa basi.

Aplikasi Python meng-import tiga page melalui Grafana API lalu membuat/update playlist `RadMon TV` dengan interval **10 detik**. Tombol Monitoring membuka playlist dalam kiosk + auto-fit; setiap page refresh data **2 detik**.

- Page 1: 15 dose-rate card + waktu pengukuran dalam satu layar.
- Page 2: trend 3 jam dan summary kondisi realtime.
- Page 3: donut status, operational table, status counts, dan alarm 24 jam.

Semua realtime state berasal dari latest `measurement`; panel waktu memakai epoch timestamp yang diformat oleh Grafana. Satuan dose rate adalah **µSv/h**.

Jika Grafana lokal tersedia, auto-setup memakai HTTP API. Bila tidak, runtime mencoba Grafana native dan Docker sebagai fallback terakhir.
