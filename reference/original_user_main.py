import serial
import mariadb
from datetime import datetime

ser = serial.Serial(port="COM15", baudrate=2400, bytesize=8, parity="N", stopbits=1, timeout=3)
print("Monitoring detector dimulai...")
print("--------------------------------")
db = mariadb.connect(host="localhost", user="root", password="", database="ipradmon", port=3306)
cursor = db.cursor()
while True:
    raw_bytes = ser.readline()
    if raw_bytes:
        raw = raw_bytes.decode("ascii", errors="ignore").strip()
        waktu = datetime.now()
        try:
            laju_dosis = float(raw[:7])
            print(f"Raw: {raw}")
            print(f"Waktu: {waktu.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Laju dosis: {laju_dosis:.3f} µSv/h")
            print("--------------------------------")
            serid = 5201
            cursor.execute("INSERT INTO rawdata (serid, dtom, raw) VALUES (?, ?, ?)", (serid, waktu, raw))
            cursor.execute("INSERT INTO measurement (serid, dtom, doserate, previnterval, stat) VALUES (?, ?, ?, ?, ?)", (serid, waktu, laju_dosis, 2, 0))
            db.commit()
        except ValueError:
            print(f"Raw tidak valid: {raw}")
