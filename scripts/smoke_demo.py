"""Offline smoke test: no detector, MariaDB, or GUI display server required."""
from __future__ import annotations

from datetime import datetime,timedelta
from io import BytesIO
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from radmon.config import Settings
from radmon.dummy import DummyDoseGenerator
from radmon.models import LatestReading,StationConfig
from radmon.public_api import create_public_app
from radmon.reports import ReportService


class MemoryRepo:
    def __init__(self):
        self.station=StationConfig(5202,"52","IS-1 Koridor","Gd.52",8,10,5,"uSv/h")
        now=datetime.now().replace(microsecond=0)
        self.rows=[{"serid":5202,"dtom":now-timedelta(seconds=4-i*2),"doserate":0.10+i*0.02,"dose":None,"previnterval":2,"stat":0} for i in range(3)]
    def station_config(self,serid=None): return self.station
    def latest_reading(self,serid=None):
        current=self.rows[-1]; previous=self.rows[-2]
        return LatestReading(self.station,current["dtom"],current["doserate"],previous["doserate"])
    def measurement_history(self,start,end,*,serid=None,limit=5000): return [r for r in self.rows if start<=r["dtom"]<=end][:limit]
    def alarm_history(self,start=None,end=None,*,serid=None,limit=1000): return []


def main()->int:
    settings=Settings(); repo=MemoryRepo()
    gen=DummyDoseGenerator("normal",seed=42,warnlevel=8,alarmlevel=10)
    assert 0<=gen.next_value()<8
    client=TestClient(create_public_app(repo,settings))
    payload=client.get("/api/latest").json(); assert payload["serid"]==5202 and payload["status"]=="NORMAL"
    response=client.get("/"); assert response.status_code==200 and "IS-1 Koridor" in response.text
    with tempfile.TemporaryDirectory() as tmp:
        service=ReportService(repo,settings); start=repo.rows[0]["dtom"]-timedelta(seconds=1); end=repo.rows[-1]["dtom"]+timedelta(seconds=1)
        pdf=service.export_pdf(start,end,Path(tmp)/"smoke.pdf"); assert pdf.read_bytes().startswith(b"%PDF")
        csv=service.export_csv(start,end,Path(tmp)/"smoke.csv"); assert "5202" in csv.read_text(encoding="utf-8")
    print("OK: domain, dummy, public API/page, CSV and PDF smoke checks passed")
    return 0
if __name__=="__main__": raise SystemExit(main())
