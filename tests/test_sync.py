from __future__ import annotations
from datetime import datetime
from fastapi.testclient import TestClient
from radmon.central_api import create_central_app
from radmon.config import Settings
from radmon.sync import SyncAgent


class LocalRepo:
    def __init__(self):
        self.rows=[{"queueid":1,"sample_key":"a"*64,"serid":5202,"dtom":datetime(2026,9,7,10,0,0),"doserate":0.123,"previnterval":2,"stat":0,"attempts":0}]; self.sent=[]; self.failed=[]
    def pending_sync(self,limit=100): return list(self.rows)[:limit]
    def mark_sync_sent(self,queue_ids,at=None): self.sent.extend(queue_ids)
    def mark_sync_failed(self,queue_ids,error): self.failed.append((tuple(queue_ids),error))


class FailedClient:
    def post(self,*args,**kwargs): raise RuntimeError("central unavailable")
class Response:
    def raise_for_status(self): return None
    def json(self): return {"inserted":1,"received":1}
class OkClient:
    def __init__(self): self.calls=[]
    def post(self,*args,**kwargs): self.calls.append((args,kwargs)); return Response()


def test_sync_agent_keeps_local_queue_on_http_failure():
    repo=LocalRepo(); agent=SyncAgent(repo,Settings(),client=FailedClient()); sent=agent.run_once(); assert sent==0; assert repo.sent==[]; assert repo.failed and repo.failed[0][0]==(1,)


def test_sync_agent_marks_batch_sent_after_success_and_serializes_datetime():
    repo=LocalRepo(); client=OkClient(); agent=SyncAgent(repo,Settings(),client=client); assert agent.run_once()==1; assert repo.sent==[1]
    payload=client.calls[0][1]["json"]; assert payload["source_name"].startswith("Gd52"); assert payload["measurements"][0]["serid"]==5202; assert payload["measurements"][0]["dtom"]=="2026-09-07 10:00:00"


class CentralRepo:
    def __init__(self): self.keys=set()
    def ping(self): return True
    def ingest_batch(self,measurements,source_name):
        inserted=0
        for item in measurements:
            if item["sample_key"] not in self.keys: self.keys.add(item["sample_key"]); inserted+=1
        return inserted
    def stations(self): return [{"serid":5202,"name":"IS-1 Koridor","location":"Gd.52"}]
    def latest(self,serid): return {"serid":serid,"dtom":"2026-09-07 10:00:00","doserate":0.123}


def test_central_ingest_requires_token_and_is_idempotent():
    settings=Settings(central_token="secret"); client=TestClient(create_central_app(CentralRepo(),settings)); payload={"source_name":"Gd52-IS1Koridor","measurements":[{"sample_key":"a"*64,"serid":5202,"dtom":"2026-09-07 10:00:00","doserate":0.123,"previnterval":2,"stat":0}]}
    assert client.post("/api/v1/measurements/batch",json=payload).status_code==401
    headers={"Authorization":"Bearer secret"}; assert client.post("/api/v1/measurements/batch",json=payload,headers=headers).json()["inserted"]==1; assert client.post("/api/v1/measurements/batch",json=payload,headers=headers).json()["inserted"]==0; assert client.get("/api/v1/stations",headers=headers).json()[0]["serid"]==5202
