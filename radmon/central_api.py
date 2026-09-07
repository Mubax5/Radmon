from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .db import connect_mariadb


class IngestMeasurement(BaseModel):
    sample_key: str = Field(min_length=64,max_length=64)
    serid: int = Field(gt=0)
    dtom: datetime
    doserate: float = Field(ge=0)
    previnterval: int = Field(default=2,ge=0)
    stat: int = 0


class IngestBatch(BaseModel):
    source_name: str = Field(min_length=1,max_length=128)
    measurements: list[IngestMeasurement] = Field(min_length=1,max_length=1000)


class CentralRepositoryProtocol(Protocol):
    def ping(self)->bool: ...
    def ingest_batch(self,measurements:list[dict[str,Any]],source_name:str)->int: ...
    def stations(self)->list[dict[str,Any]]: ...
    def latest(self,serid:int)->dict[str,Any]|None: ...


class CentralMariaDBRepository:
    def __init__(self,settings:Settings): self.settings=settings
    def _connect(self): return connect_mariadb(self.settings)
    def ping(self)->bool:
        try:
            c=self._connect()
            try:
                with c.cursor() as cur: cur.execute("SELECT 1"); cur.fetchone()
                return True
            finally: c.close()
        except Exception: return False
    def ingest_batch(self,measurements:list[dict[str,Any]],source_name:str)->int:
        c=self._connect(); inserted=0
        try:
            with c.cursor() as cur:
                for item in measurements:
                    cur.execute("INSERT IGNORE INTO radmon_sync_receipt (sample_key,received_at,source_name) VALUES (?, ?, ?)",(item["sample_key"],datetime.now(),source_name))
                    if getattr(cur,"rowcount",0)==1:
                        cur.execute("INSERT INTO measurement (serid,dtom,doserate,previnterval,stat) VALUES (?, ?, ?, ?, ?)",(item["serid"],item["dtom"],item["doserate"],item["previnterval"],item["stat"])); inserted+=1
            c.commit(); return inserted
        except Exception: c.rollback(); raise
        finally: c.close()
    def stations(self)->list[dict[str,Any]]:
        c=self._connect()
        try:
            with c.cursor() as cur: cur.execute("SELECT serid,name,location,warnlevel,alarmlevel,unit FROM device ORDER BY location,name"); rows=cur.fetchall()
            keys=("serid","name","location","warnlevel","alarmlevel","unit"); return [dict(row) if isinstance(row,dict) else dict(zip(keys,row)) for row in rows]
        finally: c.close()
    def latest(self,serid:int)->dict[str,Any]|None:
        c=self._connect()
        try:
            with c.cursor() as cur: cur.execute("SELECT serid,dtom,doserate,previnterval,stat FROM measurement WHERE serid=? ORDER BY dtom DESC LIMIT 1",(serid,)); row=cur.fetchone()
            if row is None:return None
            keys=("serid","dtom","doserate","previnterval","stat"); return dict(row) if isinstance(row,dict) else dict(zip(keys,row))
        finally:c.close()


def create_central_app(repository:CentralRepositoryProtocol,settings:Settings)->FastAPI:
    app=FastAPI(title="Radmon DPFK Central API",version="0.1.0")
    def require_token(authorization:str|None=Header(default=None)):
        expected=f"Bearer {settings.central_token}"
        if authorization!=expected: raise HTTPException(status_code=401,detail="invalid bearer token")
    @app.get("/health")
    def health(): return {"status":"ok" if repository.ping() else "error"}
    @app.post("/api/v1/measurements/batch",dependencies=[Depends(require_token)])
    def ingest(batch:IngestBatch):
        items=[item.model_dump() for item in batch.measurements]; inserted=repository.ingest_batch(items,batch.source_name)
        return {"received":len(items),"inserted":inserted,"duplicates":len(items)-inserted}
    @app.get("/api/v1/stations",dependencies=[Depends(require_token)])
    def stations(): return repository.stations()
    @app.get("/api/v1/latest/{serid}",dependencies=[Depends(require_token)])
    def latest(serid:int):
        row=repository.latest(serid)
        if row is None: raise HTTPException(status_code=404,detail="station has no measurements")
        return row
    return app
