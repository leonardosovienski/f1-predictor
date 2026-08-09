from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.market_h2h import MarketH2HDatabase
from src.market_collection.archive_db import MarketArchive
from src.market_collection.cli import import_main, quality_main
from src.market_collection.contracts import BatchState
from src.market_collection.ingest import MarketCollectionError, ingest_batch
from src.market_collection.quality import assess_market_quality

HASH = "a" * 64


def market(*, market_id: str = "m-1", bookmaker: str = "book-a", post_event: bool = False):
    published = "2026-07-26T15:00:00Z" if post_event else "2026-07-25T10:00:00Z"
    quotes = []
    for selection, odds, sequence in (("norris", 1.8, "1"), ("verstappen", 2.1, "2")):
        quotes.append(
            {
                "selection_driver_id": selection,
                "published_at_utc": published,
                "captured_at_utc": published,
                "available_at_utc": published,
                "decimal_odds": odds,
                "available_to_back": 100.0,
                "available_to_lay": 90.0,
                "traded_volume": 500.0,
                "currency": "BRL",
                "is_in_play": post_event,
                "source_sequence": sequence,
            }
        )
    return {
        "provider": "licensed-fixture",
        "source_market_id": market_id,
        "canonical_event_id": "f1-2026-r11-race",
        "season": 2026,
        "round": 11,
        "scheduled_start_utc": "2026-07-26T14:00:00Z",
        "source_event_id": "event-11",
        "driver_a_id": "norris",
        "driver_b_id": "verstappen",
        "bookmaker": bookmaker,
        "market_type": "race_h2h",
        "session": "race",
        "currency": "BRL",
        "commission_rate": 0.065,
        "settlement_rule_version": "betfair-h2h/v1",
        "settlement_rule_sha256": HASH,
        "quotes": quotes,
        "settlement": {
            "settled_at_utc": "2026-07-26T17:00:00Z",
            "winner_driver_id": "norris",
            "outcome": "WIN_LOW",
            "rule_version": "betfair-h2h/v1",
            "official_result_sha256": HASH,
        },
    }


def batch(
    tmp_path: Path, records: list[dict] | None = None, *, batch_id: str = "batch-1", licence: bool = True
) -> tuple[Path, Path]:
    root = tmp_path / batch_id
    root.mkdir()
    source = root / "quotes.json"
    source.write_text(json.dumps(records or [market()]), encoding="utf-8")
    raw = source.read_bytes()
    manifest = {
        "schema_version": "market-raw-batch/1",
        "batch_id": batch_id,
        "provider": "licensed-fixture",
        "received_at": "2026-08-09T12:00:00Z",
        "obtained_by": "synthetic-test-operator",
        "licence_reference": "synthetic-fixture-only",
        "licence_allows_research_storage": licence,
        "licence_allows_derived_results": licence,
        "source_schema_version": "fixture/1",
        "source_files": [
            {
                "path": "quotes.json",
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
        "export_parameters": {"synthetic": True},
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, tmp_path / "archive.db"


def test_valid_batch_is_normalized_and_idempotent(tmp_path):
    manifest, archive = batch(tmp_path)
    first = ingest_batch(manifest, archive)
    second = ingest_batch(manifest, archive)
    assert first.state is BatchState.NORMALIZED
    assert (first.imported_markets, first.imported_quotes) == (1, 2)
    assert second.idempotent is True
    conn = MarketArchive(archive).connect(readonly=True)
    try:
        assert conn.execute("select count(*) from market_quotes").fetchone()[0] == 2
    finally:
        conn.close()


def test_manifest_hash_and_licence_fail_closed_without_database(tmp_path):
    manifest, archive = batch(tmp_path, licence=False)
    with pytest.raises(MarketCollectionError, match="licence"):
        ingest_batch(manifest, archive)
    assert not archive.exists()

    manifest, archive = batch(tmp_path, batch_id="batch-2")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["source_files"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MarketCollectionError, match="hash mismatch"):
        ingest_batch(manifest, archive)


def test_same_market_identity_with_different_content_rolls_back(tmp_path):
    records = [market(), market()]
    manifest, archive = batch(tmp_path, records)
    with pytest.raises(MarketCollectionError, match="atomically"):
        ingest_batch(manifest, archive)
    conn = MarketArchive(archive).connect(readonly=True)
    try:
        assert conn.execute("select count(*) from acquisition_batches").fetchone()[0] == 0
        assert conn.execute("select count(*) from market_quotes").fetchone()[0] == 0
    finally:
        conn.close()


def test_post_event_quotes_are_preserved_but_never_eligible(tmp_path):
    manifest, archive = batch(tmp_path, [market(post_event=True)])
    report = ingest_batch(manifest, archive)
    assert report.ineligible_quotes == 2
    conn = MarketArchive(archive).connect(readonly=True)
    try:
        rows = conn.execute("select eligible_for_decision,ineligibility_reason from market_quotes").fetchall()
        assert {(row[0], row[1]) for row in rows} == {(0, "IN_PLAY_OR_POST_EVENT")}
    finally:
        conn.close()


def test_quality_requires_human_selection_and_measures_both_sides(tmp_path):
    records = [market(market_id="m-a", bookmaker="book-a"), market(market_id="m-b", bookmaker="book-b")]
    manifest, archive = batch(tmp_path, records)
    ingest_batch(manifest, archive)
    options: dict[str, dict[str, float]] = {
        "fixture": {"duels": 2, "race_coverage": 1, "timestamp_coverage": 1, "bookmakers": 2}
    }
    undecided = assess_market_quality(archive, scheduled_races=1, options=options)
    assert undecided.decision == "MARKET_H2H_REQUIRES_HUMAN_DECISION"
    decided = assess_market_quality(archive, scheduled_races=1, options=options, selected_option="fixture")
    assert decided.decision == "MARKET_H2H_FEASIBLE_FOR_PROTOCOL_DESIGN"
    assert decided.both_sides_coverage == 1
    assert decided.settlement_coverage == 1
    assert decided.volume_coverage == 1


def test_cli_reports_operational_and_scientific_state(tmp_path, capsys):
    manifest, archive = batch(tmp_path)
    assert import_main(["--manifest", str(manifest), "--archive", str(archive)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["run_status"] == "SUCCEEDED"
    assert imported["scientific_state"] == "COLLECTION_ONLY"
    assert quality_main(["--archive", str(archive), "--scheduled-races", "1"]) == 0
    quality = json.loads(capsys.readouterr().out)
    assert quality["scientific_state"] == "COLLECTION_ONLY"


def test_zone_one_does_not_bypass_closed_zone_two(tmp_path):
    db = MarketH2HDatabase(tmp_path / "scientific-market.db")
    with pytest.raises(RuntimeError, match="CLOSED_BY_HUMAN_DECISION"):
        db.ingest([], source_status="SOURCE_ACCEPTED")


def test_zone_one_is_not_imported_by_serving_betting_or_backtests():
    root = Path(__file__).resolve().parents[1] / "src"
    consumers = [root / name for name in ("betting.py", "operate.py", "predict.py", "backtest.py")]
    assert all("market_collection" not in path.read_text(encoding="utf-8") for path in consumers)
