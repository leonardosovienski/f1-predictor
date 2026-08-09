"""Calendar-aware archival collection, isolated from all scientific gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from packaging.version import Version

from .config import ROOT, load_drivers
from .data.f1_provider import F1Provider
from predictor_core.contracts.collection import CollectionArchive, LifecycleState, ObservationEnvelope
from predictor_core.data.contracts import DataUnavailableError

# `pythonw.exe` (executavel de toda tarefa agendada) nao tem console: um
# processo de console filho ganharia janela VISIVEL na tela do dono.
# Saida ja e capturada, entao a flag nao esconde nada.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ARCHIVE_DIR = "collection_only"


def canonical_event_id(season: int, round_: int) -> str:
    return f"f1-{season}-r{round_:02d}-race"


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("upstream timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _artifact_sha256(path: Path) -> str:
    """Hash repository text canonically so Git's Windows checkout filter is harmless."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()


def _commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True,
                              creationflags=_NO_WINDOW).stdout.strip()
    except subprocess.CalledProcessError:
        return "test-collection-root"


def verify_closure_hashes(root: Path = ROOT) -> None:
    record = json.loads((root / "data" / "authorized_closure.json").read_text(encoding="utf-8"))
    for relative, expected in record["preserved_artifact_sha256"].items():
        if relative == "vendor/predictor_core/CORE_MANIFEST.json":
            if (root / relative).exists():
                raise RuntimeError("vendored predictor-core is forbidden after package migration")
            installed = Version(version("predictor-core"))
            if installed < Version("2.1") or installed >= Version("3"):
                raise RuntimeError("predictor-core version must be >=2.1,<3")
            continue
        actual = _artifact_sha256(root / relative)
        if actual != expected.upper():
            raise RuntimeError(f"authorized closure artifact drift: {relative}")


def _participants(results: list[dict]) -> dict[str, Any]:
    if results:
        return {"drivers": [{"driver_id": row["driver_id"], "driver": row["driver"],
                              "team": row["constructor"]} for row in results]}
    return {"drivers": [{"driver": row["name"], "team": row["team"]}
                        for row in load_drivers()]}


def _store_snapshot(root: Path, run_id: str, event_id: str, payload: dict[str, Any], expected_hash: str) -> Path:
    path = root / "data" / ARCHIVE_DIR / "snapshots" / run_id / f"{event_id}.json"
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if _hash(json.loads(path.read_text(encoding="utf-8"))) != expected_hash:
            raise RuntimeError(f"collection snapshot collision: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    if _hash(payload) != expected_hash:
        raise RuntimeError("collection snapshot hash changed before storage")
    return path


def _archive_event(*, archive: CollectionArchive, run_id: str, event: dict,
                   results: list[dict], observed_at: datetime, root: Path) -> str:
    scheduled = _utc(event["scheduled_start_utc"])
    raw = {"event": event, "official_results": results, "sessions": [
        {"kind": "qualifying", "scheduled_at": event.get("qualifying_start_utc")},
        {"kind": "race", "scheduled_at": event["scheduled_start_utc"]}]}
    snapshot_hash = _hash(raw)
    event_id = canonical_event_id(event["season"], event["round"])
    snapshot_path = _store_snapshot(root, run_id, event_id, raw, snapshot_hash)
    history = archive.history(run_id, event_id)
    if history and history[-1].is_terminal:
        return history[-1].lifecycle_state
    envelope = ObservationEnvelope(
        collection_run_id=run_id, project="f1-predictor", domain="f1-archival",
        canonical_event_id=event_id, observed_at=observed_at, scheduled_at=scheduled,
        source="Jolpica/Ergast", source_record_id=f"{event['season']}:{event['round']}",
        provenance_hash=_hash({"source": "Jolpica/Ergast", "event": event}),
        source_snapshot_hash=snapshot_hash, code_commit=_commit(root),
        core_version=version("predictor-core"),
        participants=_participants(results),
        competition={"season": event["season"], "round": event["round"], "name": event["name"],
                     "circuit": event["circuit"], "sessions": raw["sessions"],
                     "snapshot_path": str(snapshot_path.relative_to(root))},
        created_at=observed_at, updated_at=observed_at)
    archive.append(envelope)
    for state in (LifecycleState.VALIDATED, LifecycleState.SNAPSHOT_RECORDED):
        envelope = envelope.transition(state, at=observed_at)
        archive.append(envelope)
    if observed_at >= scheduled:
        envelope = envelope.transition(LifecycleState.EVENT_STARTED, at=observed_at)
        archive.append(envelope)
    if results:
        official = {"results": results, "result_status": "official_source_payload"}
        envelope = envelope.transition(LifecycleState.OFFICIAL_RESULT_FOUND, at=observed_at,
                                       official_result=official)
        archive.append(envelope)
        envelope = envelope.transition(LifecycleState.COMPLETE, at=observed_at,
                                       official_result=official)
        archive.append(envelope)
    return envelope.lifecycle_state


def collect(*, season: int, now: datetime | None = None, provider: F1Provider | None = None,
            root: Path = ROOT, collection_run_id: str | None = None) -> dict[str, Any]:
    """Archive only the current/upcoming race weekend; never evaluate a model."""
    verify_closure_hashes(root)
    # CollectionArchive serializes UTC values to seconds; normalize before
    # appending so immediate lifecycle transitions retain exact identity.
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    run_id = collection_run_id or f"f1-archival-{observed.strftime('%Y%m%dT%H%M%SZ')}"
    client = provider or F1Provider()
    try:
        schedule = client.fetch_schedule(season)
    except DataUnavailableError as exc:
        return {"collection_only": True, "collection_run_id": run_id,
                "status": "SOURCE_UNAVAILABLE", "reason": str(exc), "events": 0}
    window_start, window_end = observed - timedelta(hours=48), observed + timedelta(days=7)
    events = [event for event in schedule if event.get("scheduled_start_utc") and
              window_start <= _utc(event["scheduled_start_utc"]) <= window_end]
    if not events:
        return {"collection_only": True, "collection_run_id": run_id,
                "status": "NO_UPSTREAM_EVENTS", "events": 0}
    archive = CollectionArchive(root / "data" / ARCHIVE_DIR / "archive.jsonl")
    states: dict[str, str] = {}
    for event in events:
        try:
            results = client.fetch_results(event["season"], event["round"])
        except DataUnavailableError:
            results = []
        event_id = canonical_event_id(event["season"], event["round"])
        states[event_id] = _archive_event(archive=archive, run_id=run_id, event=event,
                                          results=results, observed_at=observed, root=root)
    return {"collection_only": True, "collection_run_id": run_id,
            "status": "COLLECTED", "events": len(states), "states": states}


def _write_status(path: Path, result: dict[str, Any]) -> None:
    """Publish the domain outcome atomically beside predictor-ops artifacts."""
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
    parser.add_argument("--status-output", type=Path, help="atomic domain status JSON")
    args = parser.parse_args(argv)
    result = collect(
        season=args.season,
        provider=F1Provider(offline=args.offline),
        collection_run_id=args.collection_run_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.status_output:
        _write_status(args.status_output, result)
        return 0
    return 0 if result["status"] != "SOURCE_UNAVAILABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
