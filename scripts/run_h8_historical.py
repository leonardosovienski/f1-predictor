"""Frozen retrospective robustness check for H8; never counts as forward."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import run_h8_historical_windows  # noqa: E402
from src.config import ROOT                          # noqa: E402
from src.data.f1_provider import F1Provider          # noqa: E402

TRANSITIONS = (2014, 2017, 2022)
BURN_IN_SEASONS, WINDOW = 2, 8
SHRINK_FACTOR, N_SIMS, SIM_SEED, ALPHA = 0.8, 10000, 13, 0.05


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_races(provider: F1Provider) -> list[dict]:
    seasons = sorted({season for transition in TRANSITIONS
                      for season in range(transition - BURN_IN_SEASONS,
                                          transition + 1)})
    races = []
    for season in seasons:
        for event in provider.fetch_schedule(season):
            results = provider.fetch_results(season, event["round"])
            if results:
                races.append({**event, "results": results})
    return races


def main() -> int:
    provider = F1Provider()
    races = collect_races(provider)
    result = run_h8_historical_windows(
        races, transitions=TRANSITIONS, burn_in_seasons=BURN_IN_SEASONS,
        window=WINDOW, shrink_factor=SHRINK_FACTOR, n_sims=N_SIMS,
        sim_seed=SIM_SEED, alpha=ALPHA)
    seasons = sorted({race["season"] for race in races})
    cache_files = ([provider.cache_dir / f"schedule_{season}.json" for season in seasons]
                   + [provider.cache_dir / f"results_{race['season']}_{race['round']:02d}.json"
                      for race in races])
    payload = {**result, "artifact_kind": "H8_RETROSPECTIVE_AUXILIARY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_commit": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip(),
        "source": "Jolpica/Ergast via F1Provider",
        "input_hashes": {str(path.relative_to(ROOT)): _sha256(path)
                         for path in cache_files},
        "forward_h8_counter": "UNCHANGED; use src.snapshots snapshot-status"}
    output = ROOT / "data" / "backtest_h8_historical.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                 sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in
                      ("classification", "n", "mean_delta", "rps_shock",
                       "rps_plain", "dm", "per_transition")},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
