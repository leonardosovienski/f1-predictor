"""Entrypoint for F1 COLLECTION_ONLY archival weekends."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.archival_collection import collect  # noqa: E402
from src.data.f1_provider import F1Provider  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F1 archival COLLECTION_ONLY")
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--collection-run-id")
    args = parser.parse_args(argv)
    result = collect(season=args.season, provider=F1Provider(offline=args.offline),
                     collection_run_id=args.collection_run_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] != "SOURCE_UNAVAILABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
