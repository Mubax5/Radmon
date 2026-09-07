from __future__ import annotations

from datetime import datetime
from fastapi.testclient import TestClient
from radmon.central_api import create_central_app
from radmon.config import Settings
from radmon.sync import SyncAgent


class Checkpoint:
    def __init__(self, value): self.value=value; self.saved=[]
    def load(self): return self.value
    def save(self, value): self.value=value; self.saved.append(value)
class LocalRepo:
    def __init__(self): self.rows=[{"serid":5202,"dtom":datetime(2026,9,7,10,0,0),"doserate":0.123,"dose":0.000068,"previnterval":2,"stat":0}]; self.calls=[]
    def measurements_after(self, after, *, serid=None, limit=100): self.calls.append((after,serid,limit)); return list(self.rows)
class FailedClient:
    def post(self,*args,**kwargs): raise RuntimeError("central unavailable")
class Response:
    def raise_for_status(self): return None
    def json(self): return {"inserted":1,"received":1}
class OkClient:
    def __init__(self): self.calls=[]
    def post(self,*args,**kwargs): self.calls.append((args,kwargs)); return Response()

def enabled_settings(): return Settings(serid=5202,room="IS-1 Koridor",location="Gd.52",sync_enabled=True,central_url="http://central:8090",central_token="secret")

def test_sync_failure_does_not_advance_checkpoint():
    checkpoint=Checkpoint(datetime(2026,9,7,9,0,0)); agent=SyncAgent(LocalRepo(),enabled_settings(),checkpoint=checkpoint,client=FailedClient()); assert agent.run_once()==0; assert checkpoint.saved==[]

def test_sync_success_advances_checkpoint_and_serializes_user_schema_fields():
    repo=LocalRepo(); client=OkClient(); checkpoint=Checkpoint(datetime(2026,9,7,9,0,0)); agent=SyncAgent(repo,enabled_settings(),checkpoint=checkpoint,client=client); assert agent.run_once()==1; assert checkpoint.saved==[datetime(2026,9,7,10,0,0)]; payload=client.calls[0][1]["json"]; assert payload["source_name"].startswith("Gd52"); assert payload["station"]["serid"]==5202; assert payload["station"]["name"]=="IS-1 Koridor"; assert payload["measurements"][0]["dtom"]=="2026-09-07 10:00:00"; assert payload["measurements"][0]["dose"]==0.000068

class CentralRepo:
    def __init__(self): self.keys=set()
    def ping(self): return True
    def ingest_batch(self,measurements,station,source_name):
        inserted=0
        for item in measurements:
            key=(item["serid"],item["dtom"])
            if key not in self.keys: self.keys.add(key); inserted+=1
        return inserted
    def stations(self): return [{"serid":5202,"name":"IS-1 Koridor","location":"Gd.52"}]
    def latest(self,serid): return {"serid":serid,"dtom":"2026-09-07 10:00:00","doserate":0.123}

def test_central_ingest_requires_token_and_is_idempotent():
    settings=Settings(central_token="secret"); client=TestClient(create_central_app(CentralRepo(),settings)); payload={"source_name":"Gd52-IS1Koridor","station":{"serid":5202,"name":"IS-1 Koridor","location":"Gd.52","maxidlemin":30,"warnlevel":8,"alarmlevel":10,"unit":"uSv/h"},"measurements":[{"sample_key":"a"*64,"serid":5202,"dtom":"2026-09-07 10:00:00","doserate":0.123,"dose":0.000068,"previnterval":2,"stat":0}]}; assert client.post("/api/v1/measurements/batch",json=payload).status_code==401; headers={"Authorization":"Bearer secret"}; assert client.post("/api/v1/measurements/batch",json=payload,headers=headers).json()["inserted"]==1; assert client.post("/api/v1/measurements/batch",json=payload,headers=headers).json()["inserted"]==0; assert client.get("/api/v1/stations",headers=headers).json()[0]["serid"]==5202
