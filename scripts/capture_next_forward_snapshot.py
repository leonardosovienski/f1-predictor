"""Capture the next F1 snapshot only inside a genuine PRE_EVENT window."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.f1_provider import F1Provider  # noqa: E402
from src.snapshots import SnapshotError, create_pre_event_snapshot, snapshot_status  # noqa: E402


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp sem timezone")
    return parsed.astimezone(timezone.utc)


def eligible_race(schedule: list[dict], now: datetime) -> dict | None:
    """First race whose qualifying has ended but whose start is still future."""
    current = now.astimezone(timezone.utc)
    for race in sorted(schedule, key=lambda item: int(item["round"])):
        start_raw = race.get("scheduled_start_utc")
        qualifying_raw = race.get("qualifying_start_utc")
        if not start_raw or not qualifying_raw:
            continue
        start = _parse_utc(start_raw)
        qualifying = _parse_utc(qualifying_raw)
        # Two hours avoids freezing a partially published qualifying table.
        if qualifying.timestamp() + 2 * 3600 <= current.timestamp() < start.timestamp():
            return race
    return None


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def capture(*, season: int, now: datetime | None = None,
            provider: F1Provider | None = None, root: Path = ROOT) -> dict:
    generated = now or datetime.now(timezone.utc)
    client = provider or F1Provider()
    schedule = client.fetch_schedule(season)
    race = eligible_race(schedule, generated)
    if race is None:
        return {"status": "WAITING", "reason": "fora da janela pós-quali/pré-largada"}
    round_ = int(race["round"])
    current = snapshot_status(season=season, snapshots_root=root / "snapshots", root=root)
    if any(item.get("round") == round_ for item in current["entries"]):
        return {"status": "EXISTS", "round": round_}
    grid = client.fetch_qualifying(season, round_)
    if not grid:
        return {"status": "WAITING", "round": round_,
                "reason": "classificação ainda não publicada pela Jolpica"}
    retrieved = generated.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    grid_file = root / "data" / "raw" / f"grid_{season}_R{round_:02d}.json"
    _atomic_json(grid_file, {"source": "Jolpica qualifying endpoint",
                             "source_retrieved_at_utc": retrieved, "grid": grid})
    path = create_pre_event_snapshot(
        season=season, round_=round_,
        scheduled_start_utc=str(race["scheduled_start_utc"]),
        grid_file=grid_file, snapshots_root=root / "snapshots",
        now=generated, root=root)
    return {"status": "CREATED", "round": round_, "path": str(path)}


def main() -> int:
    season = datetime.now(timezone.utc).year
    try:
        result = capture(season=season)
    except (OSError, ValueError, SnapshotError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
