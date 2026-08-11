from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src import snapshots
from tests.experimental.p4_temporal_adapter import (
    ExperimentalTemporalError,
    adapt_f1_snapshot,
    replay_record,
    write_immutable_golden,
)

HERE = Path(__file__).parent
CASE = json.loads((HERE / "fixtures" / "f1_temporal_case.json").read_text(encoding="utf-8"))


def _dt(name: str) -> datetime:
    return datetime.fromisoformat(CASE[name].replace("Z", "+00:00"))


class _Cursor:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class _Connection:
    row_factory = None

    def execute(self, sql, _params=()):
        if "FROM races" in sql:
            return _Cursor({"season": 2026, "round": 1, "name": "Synthetic GP", "circuit": "Synthetic"})
        if "SELECT EXISTS" in sql:
            return _Cursor((0,))
        raise AssertionError(f"unexpected synthetic query: {sql}")

    def close(self):
        return None


def _canonical_pair(tmp_path: Path, monkeypatch) -> tuple[dict, dict]:
    root = tmp_path / "project"
    data = root / "data"
    data.mkdir(parents=True)
    for name, content in {
        "f1.db": b"synthetic-db",
        "ratings.json": b"{}",
        "drivers_f1.json": b"[]",
        "fase2_params.json": b'{"w_grid":0.5}',
    }.items():
        (data / name).write_bytes(content)
    (root / "config.yaml").write_text("synthetic: true\n", encoding="utf-8")
    grid = tmp_path / "grid.json"
    grid.write_text(
        json.dumps(
            {
                "source": "synthetic-fixture",
                "source_retrieved_at_utc": "2026-03-08T08:55:00Z",
                "grid": [
                    {"driver_id": "driver-a", "driver": "Driver A", "constructor": "Team A", "position": 1},
                    {"driver_id": "driver-b", "driver": "Driver B", "constructor": "Team B", "position": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    class _Model:
        def __init__(self, **_kwargs):
            pass

        def predict_race_with_grid(self, _circuit, _grid, *, params_file):
            assert params_file == data / "fase2_params.json"
            return {
                "ranking": {
                    "Driver A": {"elo": 1510.0, "win": 0.75},
                    "Driver B": {"elo": 1490.0, "win": 0.25},
                },
                "w_grid": 0.5,
            }

    monkeypatch.setattr(snapshots, "require_open", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(snapshots.db, "connect", lambda *_args, **_kwargs: _Connection())
    monkeypatch.setattr(snapshots, "load_drivers", lambda _root: [
        {"name": "Driver A", "team": "Team A"}, {"name": "Driver B", "team": "Team B"}
    ])
    monkeypatch.setattr(snapshots, "load_circuits", lambda _root: [{"name": "Synthetic"}])
    monkeypatch.setattr(snapshots, "match_circuit_metadata", lambda *_args: {"name": "Synthetic"})
    monkeypatch.setattr(snapshots, "F1EloModel", _Model)
    monkeypatch.setattr(snapshots, "_load_fase2_params", lambda _path: {"w_grid": 0.5})
    monkeypatch.setattr(snapshots, "_core_identity", lambda _root: {"version": "2.2.0", "hash": "c" * 64})
    monkeypatch.setattr(snapshots, "_tools_provenance", lambda _root=root: {"version": "3.0.0"})
    monkeypatch.setattr(snapshots, "_project_commit", lambda _root: "617cb2c49ceed1609c5cbe1e144afb465875977c")
    monkeypatch.setattr(snapshots, "_git", lambda *_args: "")
    monkeypatch.setattr(snapshots, "_result_rows", lambda *_args: [
        {"driver_id": "driver-a", "driver": "Driver A", "constructor": "Team A", "grid": 1, "position": 1, "status": "Finished", "dnf": 0, "points": 25},
        {"driver_id": "driver-b", "driver": "Driver B", "constructor": "Team B", "grid": 2, "position": 2, "status": "Finished", "dnf": 0, "points": 18},
    ])

    pre_path = snapshots.create_pre_event_snapshot(
        season=2026,
        round_=1,
        scheduled_start_utc=CASE["event_start_at"],
        grid_file=grid,
        snapshots_root=tmp_path / "snapshots",
        now=_dt("predicted_at"),
        root=root,
    )
    pre = snapshots.load_and_verify_snapshot(pre_path)
    matured_path = snapshots.mature_snapshot(
        season=2026,
        round_=1,
        snapshots_root=tmp_path / "snapshots",
        now=_dt("matured_at"),
        root=root,
    )
    return pre, json.loads(matured_path.read_text(encoding="utf-8"))


def _adapt(pre, matured, **changes):
    values = {"cutoff_at": _dt("cutoff_at"), "result_available_at": _dt("result_available_at")}
    values.update(changes)
    return adapt_f1_snapshot(pre, matured, **values)


def test_valid_canonical_flow_matches_checked_in_golden(tmp_path, monkeypatch):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    record = _adapt(pre, matured)
    golden = json.loads((HERE / "golden" / "f1_temporal_expected.json").read_text(encoding="utf-8"))
    assert record.to_dict() == golden["record"]
    assert pre["model_output"]["ranking"]["Driver A"]["win"] == golden["predicted_winner_probability"]
    assert matured["official_results"][0]["driver"] == golden["observed_winner"]
    assert matured["metrics"]["winner_brier"] == pytest.approx(golden["record"]["metric_value"], abs=1e-12, rel=1e-12)
    assert golden["metric_rule"] == "round((1.0 - actual_winner_probability) ** 2, 8)"
    assert golden["tolerance"] == {"absolute": 1e-12, "relative": 1e-12}
    replayed = replay_record(record, input_hash=golden["input_hash"])
    assert replayed == {"input_hash": golden["input_hash"], "record": golden["record"]}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"cutoff_at": _dt("predicted_at") - timedelta(seconds=1)}, "predicted_at < cutoff_at"),
        ({"cutoff_at": _dt("event_start_at")}, "cutoff_at < event_start_at"),
        ({"cutoff_at": datetime(2026, 3, 8, 9, 30)}, "timezone-aware"),
        ({"result_available_at": _dt("event_start_at") - timedelta(seconds=1)}, "at or after event_start_at"),
        ({"result_available_at": None}, "timezone-aware"),
    ],
)
def test_invalid_clocks_fail_explicitly(tmp_path, monkeypatch, change, message):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    with pytest.raises(ExperimentalTemporalError, match=message):
        _adapt(pre, matured, **change)


def test_matured_before_result_and_premature_canonical_maturity_fail(tmp_path, monkeypatch):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    early = copy.deepcopy(matured)
    early["matured_at_utc"] = "2026-03-08T11:30:00Z"
    early["payload_hash"] = snapshots._payload_hash(early)
    with pytest.raises(ExperimentalTemporalError, match="matured_at"):
        _adapt(pre, early)
    with pytest.raises(snapshots.SnapshotError, match="prematura"):
        snapshots.mature_snapshot(
            season=2026, round_=1, snapshots_root=tmp_path / "snapshots",
            now=_dt("event_start_at"), root=tmp_path / "project"
        )


def test_prediction_after_event_start_fails(tmp_path, monkeypatch):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    late = copy.deepcopy(pre)
    late["generated_at_utc"] = "2026-03-08T10:01:00Z"
    late["payload_hash"] = snapshots._payload_hash(late)
    linked = copy.deepcopy(matured)
    linked["pre_event_payload_hash"] = late["payload_hash"]
    linked["payload_hash"] = snapshots._payload_hash(linked)
    with pytest.raises(ExperimentalTemporalError, match="predicted_at < cutoff_at"):
        _adapt(late, linked)


def test_identity_and_hash_tampering_fail(tmp_path, monkeypatch):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    changed_identity = copy.deepcopy(matured)
    changed_identity["event_id"] = "f1-2026-r99-other"
    changed_identity["payload_hash"] = snapshots._payload_hash(changed_identity)
    with pytest.raises(ExperimentalTemporalError, match="identity"):
        _adapt(pre, changed_identity)
    for payload, message in ((copy.deepcopy(pre), "prediction payload"), (copy.deepcopy(matured), "matured payload")):
        payload["payload_hash"] = "0" * 64
        with pytest.raises(ExperimentalTemporalError, match=message):
            _adapt(payload, matured) if payload.get("status") == snapshots.PRE_EVENT else _adapt(pre, payload)


def test_result_hash_replay_input_and_immutable_golden(tmp_path, monkeypatch):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    record = _adapt(pre, matured)
    altered_results = copy.deepcopy(matured)
    altered_results["official_results"][0]["position"] = 2
    altered_results["payload_hash"] = snapshots._payload_hash(altered_results)
    with pytest.raises(ExperimentalTemporalError, match="result payload hash"):
        adapt_f1_snapshot(
            pre,
            altered_results,
            cutoff_at=_dt("cutoff_at"),
            result_available_at=_dt("result_available_at"),
            expected_result_payload_hash=record.result_payload_hash,
        )
    with pytest.raises(ExperimentalTemporalError, match="replay input hash"):
        replay_record(record, input_hash="f" * 64, expected_input_hash=pre["payload_hash"])
    path = tmp_path / "golden.json"
    write_immutable_golden(path, record.to_dict())
    write_immutable_golden(path, record.to_dict())
    with pytest.raises(ExperimentalTemporalError, match="overwrite"):
        write_immutable_golden(path, {**record.to_dict(), "event_id": "changed"})


def test_non_finite_metric_fails(tmp_path, monkeypatch):
    pre, matured = _canonical_pair(tmp_path, monkeypatch)
    matured["metrics"]["winner_brier"] = float("nan")
    matured["payload_hash"] = snapshots._payload_hash(matured)
    with pytest.raises(ExperimentalTemporalError, match="finite"):
        _adapt(pre, matured)
