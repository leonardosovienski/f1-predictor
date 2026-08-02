from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import tomllib
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from predictor_core.data.contracts import DataUnavailableError
from predictor_ops import JobConfig, OperationalState, run_job
from predictor_ops.health import HealthPolicy, assess

from src import cli
from scripts import capture_next_forward_snapshot
from src import snapshots
from src.clock import FixedClock, SystemClock
from src.closure import ResearchClosedError
from src.config import ROOT
from src.contracts import (
    Capability,
    CollectionRequest,
    PredictionRequest,
    SettlementRequest,
    SourceEnvelope,
    TemporalKind,
)
from src.data.f1_provider import F1Provider
from src.repositories import FileSnapshotRepository, MemoryOperationalRepository
from src.services import CollectionService, F1Plugin, PredictionService, SettlementService


def _cache(path: Path, payload: dict, *, version: str = F1Provider.CACHE_SCHEMA_VERSION,
           available_at: datetime | None = None, digest: str | None = None) -> None:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()
    path.write_text(json.dumps({
        "schema_version": version, "source": "fixture", "source_path": "fixture",
        "available_at": (available_at or datetime.now(UTC)).isoformat(),
        "payload_hash": digest or hashlib.sha256(canonical).hexdigest(), "payload": payload,
    }), encoding="utf-8")


def test_cache_unknown_schema_tamper_partial_and_stale(tmp_path):
    payload = {"MRData": {"RaceTable": {"Races": []}}}
    path = tmp_path / "schedule_2026.json"
    for kwargs in ({"version": "unknown/9"}, {"digest": "0" * 64}):
        _cache(path, payload, **kwargs)
        with pytest.raises(DataUnavailableError, match="inválido"):
            F1Provider(cache_dir=tmp_path, offline=True).fetch_schedule(2026)
    path.write_text(json.dumps({"schema_version": F1Provider.CACHE_SCHEMA_VERSION}), encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="inválido"):
        F1Provider(cache_dir=tmp_path, offline=True).fetch_schedule(2026)
    _cache(path, payload, available_at=datetime.now(UTC) - timedelta(days=2))
    with pytest.raises(DataUnavailableError, match="stale"):
        F1Provider(cache_dir=tmp_path, offline=True, max_cache_age_seconds=60).fetch_schedule(2026)
    with pytest.raises(ValueError, match="positive"):
        F1Provider(max_cache_age_seconds=0)


def test_timeout_and_rate_limit_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr("src.data.f1_provider.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("src.data.f1_provider.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("late")))
    with pytest.raises(DataUnavailableError, match="indispon"):
        F1Provider(cache_dir=tmp_path).fetch_schedule(2026)

    attempts = []
    def limited(*_args, **_kwargs):
        attempts.append(1)
        raise urllib.error.HTTPError("url", 429, "limited", {"Retry-After": "0"}, None)
    monkeypatch.setattr("urllib.request.urlopen", limited)
    with pytest.raises(DataUnavailableError, match="429"):
        F1Provider(cache_dir=tmp_path).fetch_schedule(2026)
    assert len(attempts) == 4


def test_clock_services_plugin_and_entry_points(monkeypatch):
    instant = datetime(2026, 8, 1, tzinfo=UTC)
    assert FixedClock(instant).now() == instant
    assert SystemClock().now().tzinfo is UTC
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 8, 1))

    request = PredictionRequest(circuit="Monza", predicted_at=instant, data_as_of=instant)
    service = PredictionService(root=ROOT, clock=FixedClock(instant))
    first, second = service.predict(request), service.predict(request)
    assert first.prediction_id == second.prediction_id
    assert first.output["model"] == "elo-plackett-luce-fase0"

    class OfflineProvider:
        offline = True
        def fetch_schedule(self, _season): return []
        def health_check(self): return False
        def capabilities(self): return {"odds": False, "odds_reason": "ODDS_UNAVAILABLE_FOR_F1"}

    plugin = F1Plugin(ROOT, provider=OfflineProvider())
    assert plugin.predict(request).prediction_id == first.prediction_id
    collected = plugin.collect(CollectionRequest(season=2026, observed_at=instant))
    assert collected["status"] == "NO_UPSTREAM_EVENTS"
    health = plugin.health()
    assert health.status == "DEGRADED"
    assert Capability.ODDS_UNAVAILABLE_FOR_F1 in health.capabilities
    assert health.providers["closures"] == ["H8_CLOSED_BY_HUMAN_DECISION", "H2H_CLOSED_BY_HUMAN_DECISION"]

    scripts = set(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"])
    assert {"f1-predictor", "f1-predict", "f1-operate", "f1-archival-collection", "f1-forward-snapshot"} <= scripts


def test_h8_direct_service_and_plugin_fail_closed_with_corrupt_or_missing_closure(tmp_path):
    request = SettlementRequest(prediction_id="p", event_id="f1-2026-r01-race",
                                settled_at=datetime(2026, 8, 1, tzinfo=UTC))
    for root in (tmp_path / "missing", tmp_path / "corrupt"):
        if root.name == "corrupt":
            (root / "data").mkdir(parents=True)
            (root / "data" / "authorized_closure.json").write_text("{", encoding="utf-8")
        with pytest.raises(ResearchClosedError):
            SettlementService(root=root).settle(request)
        with pytest.raises(ResearchClosedError):
            F1Plugin(root, provider=object()).settle(request)


def test_h8_cli_paths_fail_closed_without_traceback(capsys):
    assert capture_next_forward_snapshot.main() == 2
    assert "CLOSED_BY_HUMAN_DECISION" in capsys.readouterr().err
    assert snapshots.main(["snapshot-pre-event", "--season", "2026", "--round", "1",
                           "--scheduled-start-utc", "2026-08-02T00:00:00Z",
                           "--grid-file", "missing.json"]) == 2
    assert "CLOSED_BY_HUMAN_DECISION" in capsys.readouterr().err


def test_cli_health_and_prediction_paths(monkeypatch, capsys):
    class Provider:
        offline = False
    class FakePlugin:
        def __init__(self, _root): self.provider = Provider()
        def health(self):
            class Result:
                def model_dump_json(self, indent): return '{"status":"DEGRADED"}'
            return Result()
        def predict(self, request):
            class Result:
                def model_dump_json(self, indent): return json.dumps({"circuit": request.circuit})
            return Result()
    monkeypatch.setattr(cli, "F1Plugin", FakePlugin)
    assert cli.main(["health", "--offline"]) == 0
    assert "DEGRADED" in capsys.readouterr().out
    assert cli.main(["predict", "--circuit", "Monza"]) == 0
    assert "Monza" in capsys.readouterr().out


def test_repositories_hash_idempotency_latest_and_read_only_failure(tmp_path, monkeypatch):
    repo = FileSnapshotRepository(tmp_path / "objects")
    payload, digest = b"snapshot", hashlib.sha256(b"snapshot").hexdigest()
    assert repo.get("a/x") is None
    assert repo.put_if_absent("a/x", payload, digest) is True
    assert repo.put_if_absent("a/x", payload, digest) is False
    assert repo.get("a/x") == payload
    with pytest.raises(ValueError, match="hash"):
        repo.put_if_absent("bad", payload, "0" * 64)
    with pytest.raises(ValueError, match="key"):
        repo.get("../escape")
    monkeypatch.setattr("src.repositories.os.link", lambda *_a: (_ for _ in ()).throw(PermissionError("read-only")))
    with pytest.raises(PermissionError):
        repo.put_if_absent("readonly", payload, digest)
    assert not list((tmp_path / "objects").glob(".snapshot-*.tmp"))

    now = datetime(2026, 8, 1, tzinfo=UTC)
    def envelope(suffix, available):
        return SourceEnvelope(kind=TemporalKind.OFFICIAL_RESULT, event_id="race",
            observed_at=available, available_at=available, data_as_of=available,
            source="fixture", source_record_id=suffix, payload_hash=suffix * 64,
            provenance={}, payload={})
    memory = MemoryOperationalRepository()
    older, newer = envelope("a", now), envelope("b", now + timedelta(seconds=1))
    memory.save_envelope(older); memory.save_envelope(older); memory.save_envelope(newer)
    assert memory.latest("race", TemporalKind.OFFICIAL_RESULT) == newer
    assert memory.latest("other", TemporalKind.OFFICIAL_RESULT) is None


def test_portable_scheduler_success_heartbeat_and_terminal_failure(tmp_path):
    def job(job_id: str, command: list[str], **kwargs) -> JobConfig:
        return JobConfig(id=job_id, command=command, runtime={"root": tmp_path},
                         heartbeat_interval_seconds=0.01, **kwargs)

    success = run_job(job("ok", [sys.executable, "-c", "raise SystemExit(0)"]))
    assert success.status == OperationalState.SUCCEEDED
    heartbeat = tmp_path / "ok" / "heartbeat.json"
    assert assess(HealthPolicy(job_id="ok", heartbeat_path=heartbeat, max_age_seconds=60), None)["status"] == OperationalState.SUCCEEDED
    terminal = json.loads((tmp_path / "ok" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert terminal["status"] == OperationalState.SUCCEEDED

    failed = run_job(job("fail", [sys.executable, "-c", "raise SystemExit(7)"]))
    assert failed.status == OperationalState.FAILED and failed.exit_code == 7
    assert assess(HealthPolicy(job_id="fail", heartbeat_path=tmp_path / "fail" / "heartbeat.json",
                               max_age_seconds=60), None)["status"] == OperationalState.FAILED
    terminal = json.loads((tmp_path / "fail" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert terminal["status"] == OperationalState.FAILED and terminal["exit_code"] == 7


def test_portable_scheduler_timeout_closes_process_resources(tmp_path):
    started = time.monotonic()
    result = run_job(JobConfig(
        id="timeout",
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        runtime={"root": tmp_path},
        timeout_seconds=0.1,
        heartbeat_interval_seconds=0.01,
    ))
    assert time.monotonic() - started < 5
    assert result.status == OperationalState.FAILED and result.exit_code == 124
    assert result.record["termination"]["reason"] == "timeout"
    assert not any(thread.name.startswith(f"predictor-ops-output-{result.run_id}")
                   for thread in threading.enumerate())
    heartbeat = json.loads((tmp_path / "timeout" / "heartbeat.json").read_text(encoding="utf-8"))
    terminal = json.loads((tmp_path / "timeout" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert heartbeat["status"] == terminal["status"] == OperationalState.FAILED
    assert terminal["termination"]["reason"] == "timeout"
