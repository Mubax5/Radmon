from __future__ import annotations
import argparse
from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.repository import MariaDBRepository
from radmon.sync import SyncAgent

def parser():
    p=argparse.ArgumentParser(description="Sync pending local Radmon measurements to the central DPFK API."); p.add_argument("--once",action="store_true"); p.add_argument("--interval",type=float,default=2.0); return p

def main()->int:
    args=parser().parse_args(); settings=Settings.from_env(); configure_logging(settings.log_dir); agent=SyncAgent(MariaDBRepository(settings),settings)
    if args.once: sent=agent.run_once(); print(f"sent={sent}"); return 0
    agent.run_forever(args.interval); return 0
if __name__=="__main__": raise SystemExit(main())
