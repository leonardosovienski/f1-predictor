"""Build the isolated pre-2022 F1 sample; never writes data/f1.db."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from src.data.f1_provider import F1Provider  # noqa: E402
from src.data.historical_expansion import connect_shadow,coverage_report,ingest_season  # noqa: E402

def main():
    p=argparse.ArgumentParser(); p.add_argument('--seasons',nargs='+',type=int,default=list(range(2012,2022)))
    p.add_argument('--offline',action='store_true'); p.add_argument('--output',default=str(ROOT/'data'/'f1_historical_shadow.db'))
    args=p.parse_args(); conn=connect_shadow(args.output); provider=F1Provider(offline=args.offline)
    for season in args.seasons: ingest_season(conn,provider,season)
    print(json.dumps(coverage_report(conn),sort_keys=True))

if __name__=='__main__': main()
