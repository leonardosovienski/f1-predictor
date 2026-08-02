"""Report branch-aware coverage for homologated runtime and research/legacy."""
from __future__ import annotations

import json
from pathlib import Path

LEGACY = {
    "src/backtest.py",
    "src/context_factors.py",
    "src/manual_approval.py",
    "src/data/historical_expansion.py",
}


def _percentage(files: dict, selected) -> float:
    covered = total = 0
    for raw, details in files.items():
        path = raw.replace("\\", "/")
        if not selected(path):
            continue
        summary = details["summary"]
        covered += summary["covered_lines"] + summary["covered_branches"]
        total += summary["num_statements"] + summary["num_branches"]
    return 100.0 * covered / total if total else 100.0


def main() -> int:
    report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
    files = report["files"]
    global_ = float(report["totals"]["percent_covered"])
    runtime = _percentage(files, lambda path: path not in LEGACY)
    legacy = _percentage(files, lambda path: path in LEGACY)
    print(f"global={global_:.2f}% runtime={runtime:.2f}% research_legacy={legacy:.2f}%")
    return 0 if global_ >= 80 and runtime >= 80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
