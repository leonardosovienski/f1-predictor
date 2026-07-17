"""Forward snapshot contract: no network, no database writes, no Elo updates."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import snapshots
from src.config import ROOT, load_drivers


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grid_file(tmp_path: Path, *, mutate=None) -> Path:
    rows = [{"driver_id": f"driver-{index}", "driver": driver["name"],
             "constructor": driver["team"], "position": index}
            for index, driver in enumerate(load_drivers(), start=1)]
    if mutate:
        mutate(rows)
    path = tmp_path / "grid.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": "fixture-qualifying",
                                "source_retrieved_at_utc": "2026-07-15T09:00:00Z",
                                "grid": rows}), encoding="utf-8")
    return path


def _create_r10(tmp_path: Path, *, now=None, grid=None):
    return snapshots.create_pre_event_snapshot(
        season=2026, round_=10, scheduled_start_utc="2026-07-19T13:00:00Z",
        grid_file=grid or _grid_file(tmp_path), snapshots_root=tmp_path / "snapshots",
        now=now or datetime(2026, 7, 15, 10, tzinfo=timezone.utc))


def _temp_root_with_db(tmp_path: Path) -> Path:
    root = tmp_path / "project"; (root / "data").mkdir(parents=True)
    shutil.copy2(ROOT / "data" / "f1.db", root / "data" / "f1.db")
    return root


def _manual_pre(root: Path, snapshots_root: Path) -> Path:
    rows = snapshots._result_rows(root, 2026, 1)
    event = {"season": 2026, "round": 1, "name": "Australian Grand Prix"}
    path = snapshots._snapshot_path(snapshots_root, event)
    # vencedor real (position=1) com a maior P(win): a escrita em disco
    # alfabetiza as chaves (sort_keys=True), então winner_hit só é correto
    # se a maturação olhar a probabilidade, não a primeira chave
    ranking = {row["driver"]: {"win": 0.9 if row["position"] == 1 else 0.01}
               for row in rows}
    payload = {"schema_version": snapshots.SCHEMA_VERSION, "status": snapshots.PRE_EVENT,
               "event_id": snapshots.event_id(event), "season": 2026, "round": 1,
               "grand_prix": event["name"], "scheduled_start_utc": "2026-03-08T10:00:00Z",
               "generated_at_utc": "2026-03-08T09:00:00Z", "grid": [{key: row[key] for key in ("driver_id", "driver", "constructor", "grid")} | {"position": row["grid"]} for row in rows],
               "model_output": {"ranking": ranking}, "input_hashes": {"fixture": "x"},
               "project_commit": "fixture", "predictor_core_hash": "fixture",
               "consumer_provenance": {"project_name": "f1-predictor", "project_commit": "fixture",
               "project_branch": None, "project_worktree_clean": True, "predictor_core_version": "fixture",
               "predictor_core_hash": "fixture", "input_hashes": {"fixture": "x"},
               "artifact_schema_version": "f1-forward-snapshot/1.1", "generated_at_utc": "2026-03-08T09:00:00Z",
               "artifact_kind": "pre_event_snapshot"}}
    payload["payload_hash"] = snapshots._payload_hash(payload)
    snapshots._atomic_create(path, payload)
    return path


def test_valid_snapshot_is_deterministic_and_does_not_write_db_or_ratings(tmp_path, monkeypatch):
    db_path, ratings = ROOT / "data" / "f1.db", ROOT / "data" / "ratings.json"
    before = (_sha(db_path), _sha(ratings))
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("rede não permitida"))
    first = _create_r10(tmp_path / "one")
    second = _create_r10(tmp_path / "two")
    first_payload, second_payload = json.loads(first.read_text(encoding="utf-8")), json.loads(second.read_text(encoding="utf-8"))
    first_payload.pop("tools_provenance"); second_payload.pop("tools_provenance")
    first_payload.pop("payload_hash"); second_payload.pop("payload_hash")
    assert first_payload == second_payload
    persisted = json.loads(first.read_text(encoding="utf-8"))
    tools_version = (ROOT.parent / "tools" / "VERSION").read_text(encoding="utf-8").strip()
    assert persisted["tools_provenance"]["version"] == tools_version
    assert persisted["consumer_provenance"]["project_name"] == "f1-predictor"
    assert persisted["consumer_provenance"]["input_hashes"] == persisted["input_hashes"]
    assert snapshots.load_and_verify_snapshot(first)["status"] == snapshots.PRE_EVENT
    assert before == (_sha(db_path), _sha(ratings))


def test_rejects_naive_and_late_timestamp(tmp_path):
    with pytest.raises(snapshots.SnapshotError, match="timezone"):
        snapshots.create_pre_event_snapshot(season=2026, round_=10,
            scheduled_start_utc="2026-07-19T13:00:00", grid_file=_grid_file(tmp_path),
            snapshots_root=tmp_path / "snapshots")
    with pytest.raises(snapshots.SnapshotError, match="após início"):
        _create_r10(tmp_path, now=datetime(2026, 7, 19, 13, tzinfo=timezone.utc))


def test_accepts_multiple_pit_lane_starters_at_position_zero(tmp_path):
    # Regressão: position=0 ("saiu do pit lane", ver src/model.py) é
    # documentado como não-único, mas _load_grid rejeitava qualquer posição
    # repetida incluindo 0 — bloqueava o cenário real de múltiplas
    # penalidades de grid na mesma corrida. Posições reais (>=1) continuam
    # exigindo unicidade.
    pit_lane = _grid_file(tmp_path, mutate=lambda rows: (
        rows.__setitem__(0, {**rows[0], "position": 0}),
        rows.__setitem__(1, {**rows[1], "position": 0}),
    ))
    path = _create_r10(tmp_path, grid=pit_lane)
    payload = json.loads(path.read_text(encoding="utf-8"))
    positions = [row["position"] for row in payload["grid"]]
    assert positions.count(0) == 2


def test_still_rejects_duplicate_nonzero_position(tmp_path):
    duplicated = _grid_file(tmp_path, mutate=lambda rows: rows.__setitem__(1, {**rows[1], "position": rows[0]["position"]}))
    with pytest.raises(snapshots.SnapshotError, match="posição duplicada"):
        _create_r10(tmp_path, grid=duplicated)


def test_rejects_existing_result_grid_absent_ambiguous_identity_and_overwrite(tmp_path):
    with pytest.raises(snapshots.SnapshotError, match="resultado já existe"):
        snapshots.create_pre_event_snapshot(season=2026, round_=1,
            scheduled_start_utc="2026-07-20T13:00:00Z", grid_file=_grid_file(tmp_path),
            snapshots_root=tmp_path / "snapshots", now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc))
    empty = tmp_path / "empty.json"; empty.write_text(json.dumps({"source": "x", "source_retrieved_at_utc": "2026-07-15T09:00:00Z", "grid": []}), encoding="utf-8")
    with pytest.raises(snapshots.SnapshotError, match="incompleto"):
        _create_r10(tmp_path / "empty", grid=empty)
    ambiguous = _grid_file(tmp_path / "ambiguous", mutate=lambda rows: rows.__setitem__(0, {**rows[0], "driver": "Piloto Inexistente"}))
    with pytest.raises(snapshots.SnapshotError, match="ambígua"):
        _create_r10(tmp_path / "bad", grid=ambiguous)
    _create_r10(tmp_path / "overwrite")
    with pytest.raises(snapshots.SnapshotError, match="já existe"):
        _create_r10(tmp_path / "overwrite")


def test_detects_hash_tampering_and_maturity_contract(tmp_path):
    pre = _create_r10(tmp_path / "tamper")
    payload = json.loads(pre.read_text(encoding="utf-8")); payload["round"] = 99
    pre.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(snapshots.SnapshotError, match="hash"):
        snapshots.load_and_verify_snapshot(pre)
    root = _temp_root_with_db(tmp_path)
    with pytest.raises(snapshots.SnapshotError, match="sem snapshot"):
        snapshots.mature_snapshot(season=2026, round_=1, snapshots_root=tmp_path / "none", root=root)
    snapshots_root = tmp_path / "mature"; pre = _manual_pre(root, snapshots_root)
    assert snapshots.h8_eligibility(pre, None)["status"] == "PENDING"
    matured = snapshots.mature_snapshot(season=2026, round_=1, snapshots_root=snapshots_root, root=root,
                                        now=datetime(2026, 3, 8, 14, tzinfo=timezone.utc))
    result = snapshots.h8_eligibility(pre, matured)
    assert result["status"] == "VALID_FOR_H8"
    metrics = json.loads(matured.read_text(encoding="utf-8"))["metrics"]
    assert metrics["winner_hit"] is True
    assert metrics["actual_winner_probability"] == 0.9
    with pytest.raises(snapshots.SnapshotError, match="já existe"):
        snapshots.mature_snapshot(season=2026, round_=1, snapshots_root=snapshots_root, root=root)
    status = snapshots.snapshot_status(season=2026, snapshots_root=snapshots_root)
    assert status["valid_h8_races"] == 1
