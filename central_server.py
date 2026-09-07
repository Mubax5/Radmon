from __future__ import annotations
import argparse
import uvicorn
from radmon.central_api import CentralMariaDBRepository,create_central_app
from radmon.config import Settings
from radmon.logging_setup import configure_logging

def build_app():
    settings=Settings.from_env(); return create_central_app(CentralMariaDBRepository(settings),settings)
app=build_app()
def parser():
    p=argparse.ArgumentParser(description="Run central DPFK measurement ingest API."); p.add_argument("--host",default=None); p.add_argument("--port",type=int,default=None); return p

def main()->int:
    args=parser().parse_args(); settings=Settings.from_env(); configure_logging(settings.log_dir); uvicorn.run("central_server:app",host=args.host or settings.central_host,port=args.port or settings.central_port,reload=False); return 0
if __name__=="__main__": raise SystemExit(main())
