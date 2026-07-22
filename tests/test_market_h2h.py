"""Stage-0 market contracts: no source becomes economic data by accident."""
import math

import pytest

from src.data.fastf1_contract import FastF1ContractError, validate_fastf1_snapshot
from src.data.market_h2h import (MarketContractError, MarketH2HDatabase,
                                 QUALIFYING_H2H, QUALITY_ACCEPTED, RACE_H2H,
                                 RACE_SESSION, SOURCE_ACCEPTED,
                                 SOURCE_QUARANTINED, canonical_event_id,
                                 coverage_gate, settlement_outcome,
                                 validate_h2h_quote)


def quote(**changes):
    base = {"source_market_id": "m-1", "provider": "licensed-fixture",
            "canonical_event_id": canonical_event_id(2026, 11),
            "driver_a_id": "norris", "driver_b_id": "verstappen",
            "market_type": RACE_H2H, "selection": "norris",
            "captured_at": "2026-07-25T10:00:00Z", "bookmaker": "book-a",
            "opening_odds": 1.80, "closing_odds": 1.85,
            "opponent_opening_odds": 2.10, "opponent_closing_odds": 2.05,
            "settlement_rule_version": "official-classification/v1",
            "ingestion_batch_id": "b-1", "session": RACE_SESSION,
            "provenance": "licensed export sha256:fixture"}
    return {**base, **changes}


def test_quote_normalizes_margin_and_is_deterministic():
    a, b = validate_h2h_quote(quote()), validate_h2h_quote(quote())
    assert a["provenance_hash"] == b["provenance_hash"]
    assert 0 < a["implied_probability_normalized"] < 1
    assert a["market_margin"] > 0


@pytest.mark.parametrize("changes", [
    {"captured_at": ""}, {"market_type": QUALIFYING_H2H}, {"session": "sprint"},
    {"selection": "other"}, {"driver_b_id": "norris"}, {"closing_odds": 0},
    {"closing_odds": math.nan}, {"opponent_closing_odds": math.inf},
])
def test_quote_rejects_missing_time_mixed_market_identity_and_bad_odds(changes):
    with pytest.raises(MarketContractError):
        validate_h2h_quote(quote(**changes))


def test_ingestion_blocks_unaccepted_source_and_duplicate_is_atomic(tmp_path):
    db = MarketH2HDatabase(tmp_path / "market.db")
    with pytest.raises(MarketContractError, match="not accepted"):
        db.ingest([quote()], source_status=SOURCE_QUARANTINED)
    assert db.ingest([quote()], source_status=SOURCE_ACCEPTED) == 1
    with pytest.raises(Exception):
        db.ingest([quote()], source_status=SOURCE_ACCEPTED)
    conn = db.connect()
    try:
        assert conn.execute("select count(*) from market_h2h_quotes").fetchone()[0] == 1
    finally:
        conn.close()


def test_coverage_gate_does_not_choose_threshold_for_operator():
    record = validate_h2h_quote(quote())
    result = coverage_gate([record], scheduled_races=10,
                           options={"conservative": {"duels": 100, "race_coverage": .8,
                                                      "timestamp_coverage": .98, "bookmakers": 3},
                                    "pilot": {"duels": 1, "race_coverage": .1,
                                              "timestamp_coverage": 1, "bookmakers": 1}})
    assert result["options"] == {"conservative": False, "pilot": True}
    assert result["decision"] == "MARKET_H2H_REQUIRES_HUMAN_DECISION"
    assert coverage_gate([record], scheduled_races=10,
                         options={"pilot": {"duels": 1, "race_coverage": .1,
                                            "timestamp_coverage": 1, "bookmakers": 1}},
                         selected_option="pilot")["decision"] == "MARKET_H2H_FEASIBLE"


@pytest.mark.parametrize("a,b,policy,expected", [
    ("WIN", "LOSS", "official_classification", "WIN_A"),
    ("DNF", "DNF", "void_if_both_dnf", "VOID"),
    ("DNS", "LOSS", "void_if_either_nonstarter", "VOID"),
    ("DSQ", "WIN", "official_classification", "BLOCKED"),
    ("CORRECTED_PENDING", "LOSS", "official_classification", "BLOCKED"),
])
def test_settlement_contract_handles_dnf_dns_dsq_and_corrections(a, b, policy, expected):
    assert settlement_outcome(official_a=a, official_b=b,
                              rule={"version": "v1", "dnf_dns_dsq": policy}) == expected


def fastf1_record(**changes):
    base = {"downloaded_at": "2026-07-20T10:00:00Z", "cache_version": "x",
            "fastf1_version": "exploratory-uninstalled", "event": "Hungarian GP",
            "session": "FP2", "session_start_at": "2026-07-20T08:00:00Z",
            "cutoff_at": "2026-07-20T09:30:00Z", "source_last_modified": "unknown",
            "laps_excluded": [], "compounds": [], "stints": [], "track_conditions": {},
            "weather_available_at": "2026-07-20T09:00:00Z",
            "penalties_available_at": "2026-07-20T09:20:00Z", "corrections": []}
    return {**base, **changes}


def test_fastf1_contract_marks_fuel_latent_and_hashes():
    out = validate_fastf1_snapshot(fastf1_record())
    assert out["fuel_load"] == "latent_not_observed"
    assert len(out["provenance_hash"]) == 64


@pytest.mark.parametrize("changes", [
    {"cutoff_at": "2026-07-20T11:00:00Z"},
    {"weather_available_at": "2026-07-20T10:30:00Z"},
    {"session": "Qualifying"}, {"laps_excluded": "future lap"},
])
def test_fastf1_contract_rejects_lookahead_and_schema_drift(changes):
    with pytest.raises(FastF1ContractError):
        validate_fastf1_snapshot(fastf1_record(**changes))
