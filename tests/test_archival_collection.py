"""COLLECTION_ONLY stays calendar-aware and outside closed scientific tracks."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from src import archival_collection
from src.archival_collection import collect, verify_closure_hashes
from scripts import run_archival_collection
from src.data.f1_provider import DataUnavailableError


class Provider:
    def __init__(self, schedule, results=None):
        self.schedule, self.results = schedule, results or []
    def fetch_schedule(self, season): return self.schedule
    def fetch_results(self, season, round_): return self.results


def root_with_closure(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "authorized_closure.json").write_text(json.dumps({"preserved_artifact_sha256": {}}), encoding="utf-8")
    return tmp_path


def event(start="2026-07-26T13:00:00Z"):
    return {"season": 2026, "round": 12, "name": "Test GP", "circuit": "Test Circuit",
            "scheduled_start_utc": start, "qualifying_start_utc": "2026-07-25T14:00:00Z"}


def test_empty_calendar_is_no_upstream_events(tmp_path):
    root = root_with_closure(tmp_path)
    out = collect(season=2026, now=datetime(2026, 7, 24, tzinfo=timezone.utc),
                  provider=Provider([]), root=root, collection_run_id="f1-archival-empty")
    assert out["status"] == "NO_UPSTREAM_EVENTS"
    assert not (root / "data" / "collection_only").exists()


def test_weekend_archives_snapshot_and_missing_result_without_science(tmp_path, monkeypatch):
    root = root_with_closure(tmp_path)
    monkeypatch.setattr("src.archival_collection.load_drivers", lambda: [{"name": "Driver", "team": "Team"}])
    out = collect(season=2026, now=datetime(2026, 7, 25, 18, tzinfo=timezone.utc),
                  provider=Provider([event()]), root=root, collection_run_id="f1-archival-weekend")
    assert out["states"] == {"f1-2026-r12-race": "SNAPSHOT_RECORDED"}
    assert (root / "data" / "collection_only" / "snapshots" / "f1-archival-weekend" / "f1-2026-r12-race.json").is_file()
    assert "trial" not in (root / "data" / "collection_only" / "archive.jsonl").read_text(encoding="utf-8").casefold()


def test_result_completes_and_retry_is_idempotent(tmp_path, monkeypatch):
    root = root_with_closure(tmp_path)
    monkeypatch.setattr("src.archival_collection.load_drivers", lambda: [])
    result = [{"driver_id": "a", "driver": "A", "constructor": "T", "position": 1}]
    provider = Provider([event("2026-07-19T13:00:00Z")], result)
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    first = collect(season=2026, now=now, provider=provider, root=root, collection_run_id="f1-archival-result")
    second = collect(season=2026, now=now, provider=provider, root=root, collection_run_id="f1-archival-result")
    assert first["states"]["f1-2026-r12-race"] == "COMPLETE"
    assert second["states"]["f1-2026-r12-race"] == "COMPLETE"


def test_closure_hash_drift_blocks_collection(tmp_path):
    root = root_with_closure(tmp_path)
    (root / "preserved.txt").write_text("original", encoding="utf-8")
    (root / "data" / "authorized_closure.json").write_text(json.dumps({"preserved_artifact_sha256": {"preserved.txt": "0" * 64}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="closure artifact drift"):
        verify_closure_hashes(root)


def test_closure_hashes_ignore_only_git_crlf_materialization(tmp_path):
    root = root_with_closure(tmp_path)
    artifact = root / "evidence.json"
    artifact.write_bytes(b'{\r\n  "status": "closed"\r\n}\r\n')
    closure = json.loads((root / "data" / "authorized_closure.json").read_text(encoding="utf-8"))
    closure["preserved_artifact_sha256"] = {
        "evidence.json": hashlib.sha256(b'{\n  "status": "closed"\n}\n').hexdigest()
    }
    (root / "data" / "authorized_closure.json").write_text(json.dumps(closure), encoding="utf-8")

    verify_closure_hashes(root)


def test_installed_core_replaces_historical_vendor_evidence(tmp_path):
    root = tmp_path / "f1-predictor"
    data = root / "data"; data.mkdir(parents=True)
    (data / "authorized_closure.json").write_text(json.dumps({
        "preserved_artifact_sha256": {"vendor/predictor_core/CORE_MANIFEST.json": "0" * 64}}),
        encoding="utf-8")
    verify_closure_hashes(root)


def test_vendor_reappearance_is_rejected(tmp_path):
    root = tmp_path / "f1-predictor"
    vendor = root / "vendor" / "predictor_core"; vendor.mkdir(parents=True)
    (vendor / "CORE_MANIFEST.json").write_text("{}", encoding="utf-8")
    data = root / "data"; data.mkdir()
    (data / "authorized_closure.json").write_text(json.dumps({
        "preserved_artifact_sha256": {"vendor/predictor_core/CORE_MANIFEST.json": "0" * 64}}),
        encoding="utf-8")
    with pytest.raises(RuntimeError, match="vendored predictor-core is forbidden"):
        verify_closure_hashes(root)


def test_source_unavailable_is_retryable_status(tmp_path):
    root = root_with_closure(tmp_path)
    class Unavailable:
        def fetch_schedule(self, season):
            raise DataUnavailableError("temporary upstream outage")
    out = collect(season=2026, provider=Unavailable(), root=root,
                  collection_run_id="f1-archival-retry")
    assert out["status"] == "SOURCE_UNAVAILABLE"
    assert out["events"] == 0


def test_entrypoint_publishes_atomic_operational_status(tmp_path, monkeypatch):
    expected = {"collection_only": True, "collection_run_id": "r1",
                "status": "NO_UPSTREAM_EVENTS", "events": 0}
    monkeypatch.setattr(run_archival_collection, "collect", lambda **_: expected)
    status = tmp_path / "runtime" / "status.json"

    assert run_archival_collection.main(["--status-output", str(status)]) == 0
    assert json.loads(status.read_text(encoding="utf-8")) == expected


def test_installed_entrypoint_publishes_atomic_domain_status(tmp_path, monkeypatch):
    expected = {"collection_only": True, "collection_run_id": "r1",
                "status": "NO_UPSTREAM_EVENTS", "events": 0}
    monkeypatch.setattr(archival_collection, "collect", lambda **_: expected)
    status = tmp_path / "runtime" / "status.json"

    assert archival_collection.main(["--offline", "--status-output", str(status)]) == 0
    assert json.loads(status.read_text(encoding="utf-8")) == expected
