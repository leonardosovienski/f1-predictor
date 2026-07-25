"""Entrypoint for F1 COLLECTION_ONLY archival weekends."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.archival_collection import collect  # noqa: E402
from src.data.f1_provider import F1Provider  # noqa: E402


def write_status(path: Path, result: dict[str, object]) -> None:
    """Publish the consumer outcome atomically for operational_runner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F1 archival COLLECTION_ONLY")
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--collection-run-id")
    parser.add_argument("--status-output", type=Path,
                        help="atomic operational status JSON for operational_runner")
    args = parser.parse_args(argv)
    result = collect(season=args.season, provider=F1Provider(offline=args.offline),
                     collection_run_id=args.collection_run_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.status_output:
        write_status(args.status_output, result)
        # operational_runner maps this explicit, non-destructive outcome to
        # SOURCE_UNAVAILABLE rather than hiding it behind a generic failure.
        return 0
    return 0 if result["status"] != "SOURCE_UNAVAILABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
