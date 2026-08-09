from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import MarketCollectionError, ingest_batch
from .quality import assess_market_quality


def import_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="f1-market-import")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = ingest_batch(args.manifest, args.archive)
    except MarketCollectionError as exc:
        print(
            json.dumps(
                {"run_status": "FAILED", "scientific_state": "COLLECTION_ONLY", "error": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "run_status": "SUCCEEDED",
                "scientific_state": "COLLECTION_ONLY",
                "result": report.model_dump(mode="json"),
            },
            sort_keys=True,
        )
    )
    return 0


def quality_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="f1-market-quality")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--scheduled-races", type=int, required=True)
    parser.add_argument("--selected-option")
    args = parser.parse_args(argv)
    try:
        report = assess_market_quality(
            args.archive,
            scheduled_races=args.scheduled_races,
            selected_option=args.selected_option,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"run_status": "FAILED", "scientific_state": "COLLECTION_ONLY", "error": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "run_status": "SUCCEEDED",
                "scientific_state": "COLLECTION_ONLY",
                "result": report.model_dump(mode="json"),
            },
            sort_keys=True,
        )
    )
    return 0
