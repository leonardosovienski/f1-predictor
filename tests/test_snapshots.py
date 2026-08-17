"""Forward snapshot contract: no network, no database writes, no Elo updates."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pytest

from src import snapshots


@pytest.fixture(autouse=True)
def _snapshot_contract_unit_tests_do_not_use_project_closure(monkeypatch):
    """Existing fixtures verify snapshot invariants; closure is tested separately."""
    monkeypatch.setattr(snapshots, "require_open", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _installed_ops_provenance():
    """Provenance is supplied by the installed release wheel, not a checkout."""
    assert version("predictor-ops") == "3.1.0"
from src.config import ROOT, load_drivers

# Estes artefatos são OPERACIONAIS: nascem do pipeline de ingestão local e estão
# no .gitignore, então nunca existem num clone fresco. Os testes que dependem
# deles falhavam sempre em CI — o que o `|| true` do workflow escondia.
#
# O CI agora roda `scripts/seed_test_fixtures.py` antes da suíte, que monta um
# substrato sintético determinístico a partir do que JÁ é versionado; com ele
# presente, estes testes RODAM de verdade em vez de pular. O skip continua aqui
# para o caso de alguém rodar `pytest` num clone sem semear: melhor pular
# explicando do que estourar FileNotFoundError.
_OPERATIONAL_ARTIFACTS = (ROOT / "data" / "f1.db", ROOT / "data" / "ratings.json",
                          ROOT / "data" / "fase2_params.json")
requires_operational_data = pytest.mark.skipif(
    not all(path.is_file() for path in _OPERATIONAL_ARTIFACTS),
    reason="artefatos operacionais ausentes (gitignored) — rode "
           "scripts/seed_test_fixtures.py para gerar o substrato de teste")


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


def _next_open_round() -> tuple[int, str]:
    """Primeira rodada de 2026 SEM resultado no banco vivo (o fixture não
    pode apodrecer a cada corrida disputada — regressão: R10 hardcoded
    quebrou 7 testes no dia seguinte ao GP da Bélgica)."""
    conn = snapshots.db.connect(ROOT / "data" / "f1.db", readonly=True)
    try:
        row = conn.execute(
            "SELECT r.round, r.date FROM races r WHERE r.season=2026 AND NOT "
            "EXISTS(SELECT 1 FROM results x WHERE x.season=2026 AND x.round=r.round) "
            "ORDER BY r.round LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None, "temporada 2026 já terminou — atualizar fixture"
    return int(row[0]), f"{row[1]}T13:00:00Z"


def _create_r10(tmp_path: Path, *, now=None, grid=None):
    round_, start = _next_open_round()
    return snapshots.create_pre_event_snapshot(
        season=2026, round_=round_, scheduled_start_utc=start,
        grid_file=grid or _grid_file(tmp_path), snapshots_root=tmp_path / "snapshots",
        now=now or (snapshots._parse_utc(start, "start")
                    - __import__("datetime").timedelta(days=1)))


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


@requires_operational_data
def test_valid_snapshot_is_deterministic_and_does_not_write_db_or_ratings(
        tmp_path, monkeypatch):
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
    # Lê do MESMO checkout que o fixture resolveu — `ROOT.parent/"tools"` só
    # existe no layout de pastas irmãs; no CI o clone fica em ./tools.
    assert persisted["tools_provenance"]["version"] == version("predictor-ops")
    assert persisted["consumer_provenance"]["project_name"] == "f1-predictor"
    assert persisted["consumer_provenance"]["input_hashes"] == persisted["input_hashes"]
    assert snapshots.load_and_verify_snapshot(first)["status"] == snapshots.PRE_EVENT
    assert before == (_sha(db_path), _sha(ratings))


@requires_operational_data
def test_rejects_naive_and_late_timestamp(tmp_path):
    with pytest.raises(snapshots.SnapshotError, match="timezone"):
        snapshots.create_pre_event_snapshot(season=2026, round_=10,
            scheduled_start_utc="2026-07-19T13:00:00", grid_file=_grid_file(tmp_path),
            snapshots_root=tmp_path / "snapshots")
    _, start = _next_open_round()
    with pytest.raises(snapshots.SnapshotError, match="após início"):
        _create_r10(tmp_path, now=snapshots._parse_utc(start, "start"))


@requires_operational_data
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


@requires_operational_data
def test_still_rejects_duplicate_nonzero_position(tmp_path):
    duplicated = _grid_file(tmp_path, mutate=lambda rows: rows.__setitem__(1, {**rows[1], "position": rows[0]["position"]}))
    with pytest.raises(snapshots.SnapshotError, match="posição duplicada"):
        _create_r10(tmp_path, grid=duplicated)


@requires_operational_data
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


@requires_operational_data
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


@requires_operational_data
def test_mature_rejects_duplicate_final_position(tmp_path):
    # Empate/corrupção: duas linhas do resultado com a MESMA posição final
    # não podem maturar (classificação oficial da F1 tem posições únicas).
    import sqlite3
    root = _temp_root_with_db(tmp_path)
    snapshots_root = tmp_path / "snaps"
    _manual_pre(root, snapshots_root)
    conn = sqlite3.connect(root / "data" / "f1.db")
    conn.execute("UPDATE results SET position=1 WHERE season=2026 AND round=1 "
                 "AND driver_id=(SELECT driver_id FROM results WHERE season=2026 "
                 "AND round=1 AND position=2)")
    conn.commit(); conn.close()
    with pytest.raises(snapshots.SnapshotError, match="posição final duplicada"):
        snapshots.mature_snapshot(season=2026, round_=1, snapshots_root=snapshots_root,
                                  root=root, now=datetime(2026, 3, 8, 14, tzinfo=timezone.utc))


@requires_operational_data
def test_rejects_premature_maturation_and_revalidates_timestamp(tmp_path):
    root = _temp_root_with_db(tmp_path)
    snapshots_root = tmp_path / "snaps"
    pre = _manual_pre(root, snapshots_root)
    with pytest.raises(snapshots.SnapshotError, match="prematura"):
        snapshots.mature_snapshot(
            season=2026, round_=1, snapshots_root=snapshots_root, root=root,
            now=datetime(2026, 3, 8, 9, 30, tzinfo=timezone.utc))

    matured = snapshots.mature_snapshot(
        season=2026, round_=1, snapshots_root=snapshots_root, root=root,
        now=datetime(2026, 3, 8, 14, tzinfo=timezone.utc))
    payload = json.loads(matured.read_text(encoding="utf-8"))
    payload["matured_at_utc"] = "2026-03-08T09:30:00Z"
    payload["payload_hash"] = snapshots._payload_hash(payload)
    matured.write_text(json.dumps(payload), encoding="utf-8")
    result = snapshots.h8_eligibility(pre, matured)
    assert result["status"] == "INVALID_FOR_H8"
    assert "prematura" in result["reason"]


def test_atomic_create_cleans_partial_file_on_write_error(tmp_path, monkeypatch):
    destination = tmp_path / "snapshots" / "event.json"

    def fail_fsync(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(snapshots.os, "fsync", fail_fsync)
    with pytest.raises(snapshots.SnapshotError, match="atômico"):
        snapshots._atomic_create(destination, {"event": 1})
    assert not destination.exists()
    assert list(destination.parent.glob("*.tmp")) == []


def test_atomic_create_has_exactly_one_concurrent_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    destination = tmp_path / "snapshots" / "event.json"

    def publish(value):
        try:
            snapshots._atomic_create(destination, {"event": value})
            return "created"
        except snapshots.SnapshotError:
            return "exists"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, (1, 2)))
    assert sorted(outcomes) == ["created", "exists"]
    assert json.loads(destination.read_text(encoding="utf-8"))["event"] in (1, 2)


@requires_operational_data
def test_corrected_result_invalidates_existing_maturity(tmp_path):
    import sqlite3

    root = _temp_root_with_db(tmp_path)
    snapshots_root = tmp_path / "snaps"
    pre = _manual_pre(root, snapshots_root)
    matured = snapshots.mature_snapshot(
        season=2026, round_=1, snapshots_root=snapshots_root, root=root,
        now=datetime(2026, 3, 8, 14, tzinfo=timezone.utc))
    assert snapshots.h8_eligibility(pre, matured, root=root)["status"] == "VALID_FOR_H8"

    conn = sqlite3.connect(root / "data" / "f1.db")
    conn.execute("UPDATE results SET status='Disqualified', dnf=1, points=0 "
                 "WHERE season=2026 AND round=1 AND position=2")
    conn.commit(); conn.close()
    result = snapshots.h8_eligibility(pre, matured, root=root)
    assert result["status"] == "INVALID_FOR_H8"
    assert "corrigido" in result["reason"]


@requires_operational_data
def test_truncated_snapshot_file_is_invalid_for_h8(tmp_path):
    pre = _create_r10(tmp_path / "trunc")
    raw = pre.read_text(encoding="utf-8")
    pre.write_text(raw[: len(raw) // 2], encoding="utf-8")
    with pytest.raises(snapshots.SnapshotError, match="ilegível"):
        snapshots.load_and_verify_snapshot(pre)
    assert snapshots.h8_eligibility(pre, None)["status"] == "INVALID_FOR_H8"


def test_snapshot_status_empty_season_reports_full_gate(tmp_path):
    status = snapshots.snapshot_status(season=2026, snapshots_root=tmp_path / "vazio")
    assert status["valid_h8_races"] == 0
    assert status["missing_to_gate"] == snapshots.H8_REQUIRED_RACES == 15


@requires_operational_data
def test_pre_event_uses_the_same_params_it_freezes(tmp_path):
    # Regressão: o modelo lia fase2_params do ROOT do processo enquanto o
    # payload congelava/hasheava os params do `root` passado — proveniência
    # divergia da previsão quando root != ROOT.
    root = _temp_root_with_db(tmp_path)
    # circuits_f1.json entra aqui porque F1EloModel.__init__ chama
    # load_circuits(self.root): sem ele o root alternativo fica incompleto e o
    # teste morre em FileNotFoundError antes de chegar na asserção — inclusive
    # numa máquina com data/ real. Faltava desde sempre; só não aparecia porque
    # o `|| true` do CI e a ausência do f1.db mascaravam o resultado.
    for name in ("ratings.json", "drivers_f1.json", "fase2_params.json",
                 "circuits_f1.json"):
        shutil.copy2(ROOT / "data" / name, root / "data" / name)
    shutil.copy2(ROOT / "config.yaml", root / "config.yaml")
    # muda o w_grid SÓ no root alternativo — a previsão tem que refletir isso
    params = json.loads((root / "data" / "fase2_params.json").read_text(encoding="utf-8"))
    params["w_grid"] = 0.99
    (root / "data" / "fase2_params.json").write_text(json.dumps(params), encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-q", "-m", "fixture"], check=True)
    round_, start = _next_open_round()
    path = snapshots.create_pre_event_snapshot(
        season=2026, round_=round_, scheduled_start_utc=start,
        grid_file=_grid_file(tmp_path), snapshots_root=tmp_path / "snaps",
        now=snapshots._parse_utc(start, "start")
        - __import__("datetime").timedelta(days=1), root=root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["frozen_parameters"]["w_grid"] == 0.99
    assert payload["model_output"]["w_grid"] == 0.99
