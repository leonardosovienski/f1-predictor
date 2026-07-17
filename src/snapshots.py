"""Forward-only, append-only evidence for F1 race predictions.

This module deliberately does not ingest data, write ``f1.db``, update Elo
ratings, or call the normal serving function (which appends to predictions
logs).  A pre-event snapshot is created only from explicit local inputs; a
separate maturity record later binds the unchanged snapshot to final results
already present in the local database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any

from .config import ROOT, load_circuits, load_drivers
from .context_factors import match_circuit_metadata
from .data import db
from .model import F1EloModel, _load_fase2_params

SCHEMA_VERSION = "1.0"
PRE_EVENT = "PRE_EVENT"
MATURED = "MATURED"
H8_REQUIRED_RACES = 15


class SnapshotError(ValueError):
    """A snapshot contract invariant was not met."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise SnapshotError(f"hash impossível: arquivo ausente {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{field} inválido: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotError(f"{field} deve ter timezone UTC")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotError("datetime deve ter timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _project_commit(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            text=True, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise SnapshotError("commit Git não pôde ser determinado")
    return result.stdout.strip()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], text=True,
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise SnapshotError("proveniÃªncia Git do projeto nÃ£o pÃ´de ser determinada")
    return result.stdout.strip()


def _core_identity(root: Path) -> dict[str, str]:
    vendor = root / "vendor" / "predictor_core"
    version = vendor / "VERSION"
    if not version.is_file():
        raise SnapshotError("VERSION do predictor_core ausente")
    return {"version": version.read_text(encoding="utf-8").strip(),
            "hash": _sha256_file(vendor / "CORE_MANIFEST.json")}


def _tools_provenance() -> dict[str, Any]:
    workspace = ROOT.parent
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))
    try:
        from tools.tools_provenance import ToolsProvenanceError, collect_tools_provenance
        return collect_tools_provenance(workspace / "tools", strict=True)
    except (ImportError, OSError, RuntimeError) as exc:
        raise SnapshotError(f"proveniÃªncia strict de tools indisponÃ­vel: {exc}") from exc


def _consumer_provenance(root: Path, core: dict[str, str], inputs: dict[str, str], generated: datetime) -> dict[str, Any]:
    return {
        "project_name": "f1-predictor",
        "project_commit": _project_commit(root),
        "project_branch": _git(root, "branch", "--show-current") or None,
        "project_worktree_clean": not bool(_git(root, "status", "--porcelain")),
        "predictor_core_version": core["version"],
        "predictor_core_hash": core["hash"],
        "input_hashes": inputs,
        "artifact_schema_version": "f1-forward-snapshot/1.1",
        "generated_at_utc": _utc_text(generated),
        "artifact_kind": "pre_event_snapshot",
    }


def _event(conn, season: int, round_: int) -> dict[str, Any]:
    conn.row_factory = __import__("sqlite3").Row
    row = conn.execute("SELECT season, round, name, circuit, date FROM races WHERE season=? AND round=?",
                       (season, round_)).fetchone()
    if row is None:
        raise SnapshotError(f"evento inexistente: season={season}, round={round_}")
    return dict(row)


def _has_result(conn, season: int, round_: int) -> bool:
    return conn.execute("SELECT EXISTS(SELECT 1 FROM results WHERE season=? AND round=?)",
                        (season, round_)).fetchone()[0] == 1


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def event_id(event: dict[str, Any]) -> str:
    return f"f1-{event['season']}-r{int(event['round']):02d}-{_slug(event['name'])}"


def _snapshot_path(snapshots_root: Path, event: dict[str, Any]) -> Path:
    return snapshots_root / "pre_event" / str(event["season"]) / f"R{int(event['round']):02d}_{event_id(event)}.json"


def _matured_path(snapshots_root: Path, event: dict[str, Any]) -> Path:
    return snapshots_root / "matured" / str(event["season"]) / f"R{int(event['round']):02d}_{event_id(event)}.json"


def _atomic_create(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise SnapshotError(f"artefato já existe; overwrite proibido: {path}") from exc


def _load_grid(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"grid inválido: {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("grid"), list):
        raise SnapshotError("grid deve ser objeto com lista 'grid'")
    if not isinstance(raw.get("source"), str) or not raw["source"].strip():
        raise SnapshotError("grid exige source")
    retrieved = _parse_utc(str(raw.get("source_retrieved_at_utc", "")), "source_retrieved_at_utc")
    known = {driver["name"]: driver for driver in load_drivers()}
    rows: list[dict[str, Any]] = []
    positions: set[int] = set()
    ids: set[str] = set()
    names: set[str] = set()
    for item in raw["grid"]:
        if not isinstance(item, dict):
            raise SnapshotError("cada linha do grid deve ser objeto")
        name = item.get("driver")
        driver_id = item.get("driver_id")
        constructor = item.get("constructor")
        position = item.get("position")
        if not all(isinstance(value, str) and value.strip() for value in (name, driver_id, constructor)):
            raise SnapshotError("grid exige driver_id, driver e constructor")
        if name not in known:
            raise SnapshotError(f"identidade de piloto ambígua/desconhecida: {name!r}")
        if known[name]["team"] != constructor:
            raise SnapshotError(f"construtor inconsistente para {name}: {constructor!r}")
        if not isinstance(position, int) or position < 0:
            raise SnapshotError(f"posição de grid inválida para {name}")
        if position in positions or driver_id in ids or name in names:
            raise SnapshotError("grid contém posição ou identidade duplicada")
        positions.add(position); ids.add(driver_id); names.add(name)
        rows.append({"driver_id": driver_id, "driver": name,
                     "constructor": constructor, "position": position})
    if len(rows) != len(known) or names != set(known):
        raise SnapshotError("grid ausente ou incompleto para o grid canônico")
    return sorted(rows, key=lambda row: row["position"]), raw, _utc_text(retrieved)


def _payload_hash(payload: dict[str, Any]) -> str:
    without_hash = {key: value for key, value in payload.items() if key != "payload_hash"}
    return _sha256_bytes(_canonical(without_hash))


def create_pre_event_snapshot(*, season: int, round_: int, scheduled_start_utc: str,
                              grid_file: Path, snapshots_root: Path,
                              now: datetime | None = None, root: Path = ROOT) -> Path:
    start = _parse_utc(scheduled_start_utc, "scheduled_start_utc")
    generated = now or datetime.now(timezone.utc)
    generated = _parse_utc(_utc_text(generated), "generated_at_utc")
    if generated >= start:
        raise SnapshotError("snapshot após início oficial do evento é proibido")
    conn = db.connect(root / "data" / "f1.db", readonly=True)
    try:
        event = _event(conn, season, round_)
        if _has_result(conn, season, round_):
            raise SnapshotError("resultado já existe no banco; snapshot pré-evento proibido")
    finally:
        conn.close()
    grid, grid_raw, retrieved_at = _load_grid(grid_file)
    if _parse_utc(retrieved_at, "source_retrieved_at_utc") > generated:
        raise SnapshotError("source_retrieved_at_utc não pode ser posterior à geração")
    destination = _snapshot_path(snapshots_root, event)
    if destination.exists():
        raise SnapshotError(f"snapshot já existe; overwrite proibido: {destination}")
    model = F1EloModel(ratings_file=root / "data" / "ratings.json")
    grid_map = {row["driver"]: row["position"] for row in grid}
    circuit = match_circuit_metadata(event["circuit"], load_circuits())
    if circuit is None:
        raise SnapshotError(f"circuito do evento sem identidade canônica: {event['circuit']!r}")
    output = model.predict_race_with_grid(circuit["name"], grid_map)
    params_path = root / "data" / "fase2_params.json"
    inputs = {"grid": _sha256_file(grid_file), "database": _sha256_file(root / "data" / "f1.db"),
              "ratings": _sha256_file(root / "data" / "ratings.json"),
              "drivers": _sha256_file(root / "data" / "drivers_f1.json"),
              "phase2_parameters": _sha256_file(params_path),
              "config": _sha256_file(root / "config.yaml")}
    core = _core_identity(root)
    consumer = _consumer_provenance(root, core, inputs, generated)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "status": PRE_EVENT,
        "maturity_status": "PENDING", "event_id": event_id(event),
        "season": season, "round": round_, "grand_prix": event["name"],
        "scheduled_start_utc": _utc_text(start), "generated_at_utc": _utc_text(generated),
        "source": grid_raw["source"], "source_retrieved_at_utc": retrieved_at,
        "grid": grid, "driver_identities": [{"driver_id": row["driver_id"], "driver": row["driver"], "constructor": row["constructor"]} for row in grid],
        "constructor_identities": sorted({row["constructor"] for row in grid}),
        "ratings": {name: output["ranking"][name]["elo"] for name in output["ranking"]},
        "frozen_parameters": _load_fase2_params(params_path), "model_output": output,
        "project_commit": _project_commit(root), "predictor_core_version": core["version"],
        "predictor_core_hash": core["hash"], "tools_provenance": _tools_provenance(),
        "consumer_provenance": consumer,
        "input_hashes": inputs, "audit_metadata": {"network_used": False, "database_write": False,
        "ratings_write": False, "model_training": False},
    }
    payload["payload_hash"] = _payload_hash(payload)
    _atomic_create(destination, payload)
    return destination


def load_and_verify_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"snapshot ilegível: {path}: {exc}") from exc
    required = {"schema_version", "status", "event_id", "scheduled_start_utc", "generated_at_utc", "grid", "payload_hash", "model_output", "input_hashes", "project_commit", "predictor_core_hash"}
    missing = sorted(required - set(payload))
    if missing:
        raise SnapshotError(f"snapshot sem campos obrigatórios: {missing}")
    if payload["schema_version"] != SCHEMA_VERSION or payload["status"] != PRE_EVENT:
        raise SnapshotError("schema/status de snapshot inválido")
    if _payload_hash(payload) != payload["payload_hash"]:
        raise SnapshotError("hash do snapshot inconsistente")
    generated = _parse_utc(payload["generated_at_utc"], "generated_at_utc")
    start = _parse_utc(payload["scheduled_start_utc"], "scheduled_start_utc")
    if generated >= start:
        raise SnapshotError("proteção temporal violada: snapshot não é pré-evento")
    if not isinstance(payload["grid"], list) or not payload["grid"]:
        raise SnapshotError("grid ausente")
    return payload


def _result_rows(root: Path, season: int, round_: int) -> list[dict[str, Any]]:
    conn = db.connect(root / "data" / "f1.db", readonly=True)
    try:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute("SELECT driver_id, driver, constructor, grid, position, status, dnf, points FROM results WHERE season=? AND round=? ORDER BY position", (season, round_)).fetchall()
        if not rows:
            raise SnapshotError("resultado oficial ainda não existe no banco")
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mature_snapshot(*, season: int, round_: int, snapshots_root: Path,
                    now: datetime | None = None, root: Path = ROOT) -> Path:
    conn = db.connect(root / "data" / "f1.db", readonly=True)
    try:
        event = _event(conn, season, round_)
    finally:
        conn.close()
    pre_path = _snapshot_path(snapshots_root, event)
    if not pre_path.is_file():
        raise SnapshotError("maturação sem snapshot PRE_EVENT é proibida")
    pre = load_and_verify_snapshot(pre_path)
    consumer = pre.get("consumer_provenance")
    if not isinstance(consumer, dict):
        raise SnapshotError("snapshot PRE_EVENT sem consumer_provenance; maturaÃ§Ã£o strict proibida")
    target = _matured_path(snapshots_root, event)
    if target.exists():
        raise SnapshotError(f"maturação já existe; overwrite proibido: {target}")
    results = _result_rows(root, season, round_)
    snapshot_names = {row["driver"] for row in pre["grid"]}
    result_names = {row["driver"] for row in results}
    if snapshot_names != result_names:
        raise SnapshotError("identidades do resultado não correspondem ao snapshot")
    winner = next((row for row in results if row["position"] == 1), None)
    if winner is None:
        raise SnapshotError("resultado sem vencedor")
    predicted = pre["model_output"]["ranking"]
    probability = predicted[winner["driver"]]["win"]
    # a ordem das chaves no disco é alfabética (sort_keys=True na escrita);
    # o favorito tem que sair da probabilidade, nunca da posição da chave
    top = max(predicted, key=lambda name: predicted[name]["win"])
    matured = now or datetime.now(timezone.utc)
    payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "status": MATURED,
        "event_id": pre["event_id"], "season": season, "round": round_,
        "matured_at_utc": _utc_text(matured), "pre_event_path": str(pre_path),
        "pre_event_payload_hash": pre["payload_hash"], "result_source": "f1.db/results",
        "result_database_hash": _sha256_file(root / "data" / "f1.db"), "official_results": results,
        "metrics": {"actual_winner": winner["driver"], "actual_winner_probability": probability,
                    "winner_brier": round((1.0 - probability) ** 2, 8),
                    "winner_hit": top == winner["driver"]},
        "tools_provenance": _tools_provenance(), "consumer_provenance": {
            **consumer, "artifact_kind": "matured_snapshot",
            "generated_at_utc": _utc_text(matured)},
        "audit_metadata": {"model_reexecuted": False, "database_write": False,
                           "ratings_write": False, "network_used": False}}
    payload["payload_hash"] = _payload_hash(payload)
    _atomic_create(target, payload)
    return target


def h8_eligibility(pre_path: Path, matured_path: Path | None) -> dict[str, Any]:
    try:
        pre = load_and_verify_snapshot(pre_path)
    except SnapshotError as exc:
        return {"status": "INVALID_FOR_H8", "reason": str(exc)}
    if matured_path is None or not matured_path.is_file():
        return {"status": "PENDING", "reason": "resultado/maturação ausente", "event_id": pre["event_id"]}
    try:
        matured = json.loads(matured_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "INVALID_FOR_H8", "reason": f"maturação ilegível: {exc}"}
    if matured.get("status") != MATURED or matured.get("pre_event_payload_hash") != pre["payload_hash"]:
        return {"status": "INVALID_FOR_H8", "reason": "vínculo criptográfico PRE_EVENT→MATURED inválido"}
    if _payload_hash(matured) != matured.get("payload_hash"):
        return {"status": "INVALID_FOR_H8", "reason": "hash de maturação inconsistente"}
    names = {row["driver"] for row in pre["grid"]}
    result_names = {row.get("driver") for row in matured.get("official_results", [])}
    if names != result_names or not matured.get("metrics"):
        return {"status": "INVALID_FOR_H8", "reason": "identidades/métricas incompletas"}
    return {"status": "VALID_FOR_H8", "event_id": pre["event_id"],
            "pre_event_payload_hash": pre["payload_hash"], "matured_payload_hash": matured["payload_hash"]}


def snapshot_status(*, season: int, snapshots_root: Path) -> dict[str, Any]:
    entries = []
    for pre in sorted((snapshots_root / "pre_event" / str(season)).glob("*.json")) if (snapshots_root / "pre_event" / str(season)).exists() else []:
        try:
            payload = load_and_verify_snapshot(pre)
            mature = _matured_path(snapshots_root, {"season": payload["season"], "round": payload["round"], "name": payload["grand_prix"]})
            entries.append({"round": payload["round"], "event_id": payload["event_id"], "snapshot": str(pre), **h8_eligibility(pre, mature)})
        except SnapshotError as exc:
            entries.append({"snapshot": str(pre), "status": "INVALID_FOR_H8", "reason": str(exc)})
    valid = sum(item["status"] == "VALID_FOR_H8" for item in entries)
    return {"season": season, "entries": entries, "valid_h8_races": valid,
            "required_h8_races": H8_REQUIRED_RACES, "missing_to_gate": max(0, H8_REQUIRED_RACES - valid)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshots forward imutáveis de F1")
    sub = parser.add_subparsers(dest="command", required=True)
    def common(command):
        command.add_argument("--season", type=int, default=2026)
        command.add_argument("--round", type=int, required=True)
        command.add_argument("--snapshots-dir", type=Path, default=ROOT / "snapshots")
    create = sub.add_parser("snapshot-pre-event"); common(create)
    create.add_argument("--scheduled-start-utc", required=True)
    create.add_argument("--grid-file", type=Path, required=True)
    verify = sub.add_parser("verify-snapshot"); common(verify)
    mature = sub.add_parser("mature-snapshot"); common(mature)
    status = sub.add_parser("snapshot-status"); status.add_argument("--season", type=int, default=2026); status.add_argument("--snapshots-dir", type=Path, default=ROOT / "snapshots")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot-pre-event":
            result: Any = {"path": str(create_pre_event_snapshot(season=args.season, round_=args.round, scheduled_start_utc=args.scheduled_start_utc, grid_file=args.grid_file, snapshots_root=args.snapshots_dir))}
        elif args.command == "verify-snapshot":
            conn = db.connect(ROOT / "data" / "f1.db", readonly=True)
            try: event = _event(conn, args.season, args.round)
            finally: conn.close()
            result = {"snapshot": load_and_verify_snapshot(_snapshot_path(args.snapshots_dir, event)),
                      "tools_provenance": _tools_provenance()}
        elif args.command == "mature-snapshot":
            result = {"path": str(mature_snapshot(season=args.season, round_=args.round, snapshots_root=args.snapshots_dir))}
        else:
            result = {**snapshot_status(season=args.season, snapshots_root=args.snapshots_dir),
                      "tools_provenance": _tools_provenance()}
    except SnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
