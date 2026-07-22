"""Isolated, fail-closed contract for licensed Formula 1 race H2H markets.

This module neither fetches protected pages nor makes betting decisions. It only
accepts a lawfully obtained provider payload with point-in-time provenance.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_ACCEPTED = "SOURCE_ACCEPTED"
SOURCE_PARTIALLY_ACCEPTED = "SOURCE_PARTIALLY_ACCEPTED"
SOURCE_QUARANTINED = "SOURCE_QUARANTINED"
SOURCE_STALE = "SOURCE_STALE"
SOURCE_SCHEMA_DRIFT = "SOURCE_SCHEMA_DRIFT"
SOURCE_REJECTED = "SOURCE_REJECTED"
SOURCE_REQUIRES_HUMAN_DECISION = "SOURCE_REQUIRES_HUMAN_DECISION"
QUALITY_ACCEPTED = "ACCEPTED"
RACE_H2H, QUALIFYING_H2H = "race_h2h", "qualifying_h2h"
RACE_SESSION, SPRINT_SESSION = "race", "sprint"


class MarketContractError(ValueError):
    """A record cannot safely be used for economic validation."""


def _utc(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise MarketContractError(f"{field} must be UTC text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketContractError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketContractError(f"{field} requires timezone")
    return parsed.astimezone(timezone.utc)


def canonical_event_id(season: int, round_: int, session: str = RACE_SESSION) -> str:
    if not isinstance(season, int) or not isinstance(round_, int) or season < 1950 or round_ < 1:
        raise MarketContractError("invalid season/round")
    if session not in (RACE_SESSION, SPRINT_SESSION):
        raise MarketContractError("invalid session")
    return f"f1-{season}-r{round_:02d}-{session}"


def canonical_pair(driver_a_id: str, driver_b_id: str) -> tuple[str, str]:
    if not all(isinstance(value, str) and value.strip() for value in (driver_a_id, driver_b_id)):
        raise MarketContractError("missing driver identity")
    if driver_a_id == driver_b_id:
        raise MarketContractError("driver cannot oppose itself")
    return tuple(sorted((driver_a_id, driver_b_id)))


def _odds(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 1.0:
        raise MarketContractError(f"{field} must be finite decimal odds > 1")
    return float(value)


def normalized_probabilities(odds_a: Any, odds_b: Any) -> tuple[float, float, float]:
    a, b = _odds(odds_a, "odds_a"), _odds(odds_b, "odds_b")
    raw_a, raw_b = 1 / a, 1 / b
    overround = raw_a + raw_b
    if not math.isfinite(overround) or overround <= 1.0:
        raise MarketContractError("invalid market margin")
    return raw_a, raw_b, overround


def provenance_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "provenance_hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_h2h_quote(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a two-runner race H2H quote and reject ambiguous economics."""
    required = {"source_market_id", "provider", "canonical_event_id", "season", "race_id", "driver_a_id", "driver_b_id",
                "market_type", "selection", "captured_at", "bookmaker", "opening_odds", "closing_odds",
                "opponent_opening_odds", "opponent_closing_odds", "settlement_rule_version",
                "ingestion_batch_id", "session", "provenance", "opening_captured_at", "closing_captured_at", "decision_at"}
    missing = sorted(required - set(record))
    if missing:
        raise MarketContractError(f"missing fields: {missing}")
    if record["market_type"] != RACE_H2H or record["session"] != RACE_SESSION:
        raise MarketContractError("only race H2H is eligible; qualifying/sprint are distinct")
    textual = required - {"season", "race_id", "opening_odds", "closing_odds", "opponent_opening_odds", "opponent_closing_odds"}
    if not all(isinstance(record[key], str) and record[key].strip() for key in textual):
        raise MarketContractError("invalid required textual field")
    captured = _utc(record["captured_at"], "captured_at")
    opening_at = _utc(record["opening_captured_at"], "opening_captured_at")
    closing_at = _utc(record["closing_captured_at"], "closing_captured_at")
    decision_at = _utc(record["decision_at"], "decision_at")
    if not isinstance(record["season"], int) or not isinstance(record["race_id"], int):
        raise MarketContractError("season/race_id must be integers")
    if record["canonical_event_id"] != canonical_event_id(record["season"], record["race_id"]):
        raise MarketContractError("canonical_event_id does not match season/race_id")
    if not opening_at <= closing_at <= decision_at:
        raise MarketContractError("opening/closing timestamps violate decision cutoff")
    low, high = canonical_pair(record["driver_a_id"], record["driver_b_id"])
    if record["selection"] not in (record["driver_a_id"], record["driver_b_id"]):
        raise MarketContractError("selection must be one of the drivers")
    opening = _odds(record["opening_odds"], "opening_odds")
    closing = _odds(record["closing_odds"], "closing_odds")
    opponent_opening = _odds(record["opponent_opening_odds"], "opponent_opening_odds")
    raw_a, raw_b, overround = normalized_probabilities(closing, record["opponent_closing_odds"])
    raw = raw_a if record["selection"] == record["driver_a_id"] else raw_b
    out = {**record, "captured_at": captured.isoformat(timespec="seconds"),
           "opening_captured_at": opening_at.isoformat(timespec="seconds"),
           "closing_captured_at": closing_at.isoformat(timespec="seconds"),
           "decision_at": decision_at.isoformat(timespec="seconds"), "pair_driver_low_id": low,
           "pair_driver_high_id": high, "opening_odds": opening, "closing_odds": closing,
           "opponent_opening_odds": opponent_opening, "implied_probability_raw": raw,
           "implied_probability_normalized": raw / overround, "market_margin": overround - 1.0,
           "data_quality_status": QUALITY_ACCEPTED}
    out["provenance_hash"] = provenance_hash(out)
    return out


def settlement_outcome(*, official_a: str, official_b: str, rule: dict[str, Any]) -> str:
    """Return WIN_A/LOSS_A/VOID/BLOCKED; never invent bookmaker settlement."""
    if not isinstance(rule, dict) or not rule.get("version"):
        return "BLOCKED"
    policy = rule.get("dnf_dns_dsq")
    if policy not in {"official_classification", "void_if_either_nonstarter", "void_if_both_dnf"}:
        return "BLOCKED"
    statuses = {official_a, official_b}
    if "DNS" in statuses and policy != "official_classification":
        return "VOID"
    if statuses == {"DNF"} and policy == "void_if_both_dnf":
        return "VOID"
    if "UNKNOWN" in statuses or "CORRECTED_PENDING" in statuses or "DSQ" in statuses:
        return "BLOCKED"
    if official_a == "WIN" and official_b == "LOSS":
        return "WIN_A"
    if official_a == "LOSS" and official_b == "WIN":
        return "LOSS_A"
    return "BLOCKED"


SCHEMA = """
CREATE TABLE IF NOT EXISTS market_h2h_quotes (
 source_market_id TEXT NOT NULL, provider TEXT NOT NULL, canonical_event_id TEXT NOT NULL, season INTEGER NOT NULL, race_id INTEGER NOT NULL,
 driver_a_id TEXT NOT NULL, driver_b_id TEXT NOT NULL, market_type TEXT NOT NULL,
 selection TEXT NOT NULL, captured_at TEXT NOT NULL, opening_captured_at TEXT NOT NULL, closing_captured_at TEXT NOT NULL, decision_at TEXT NOT NULL, opening_odds REAL NOT NULL,
 closing_odds REAL NOT NULL, opponent_opening_odds REAL NOT NULL, opponent_closing_odds REAL NOT NULL,
 bookmaker TEXT NOT NULL, implied_probability_raw REAL NOT NULL, implied_probability_normalized REAL NOT NULL,
 settlement_rule_version TEXT NOT NULL, provenance_hash TEXT NOT NULL, ingestion_batch_id TEXT NOT NULL,
 data_quality_status TEXT NOT NULL, session TEXT NOT NULL, market_margin REAL NOT NULL, provenance TEXT NOT NULL,
 PRIMARY KEY(provider, source_market_id, selection, captured_at, bookmaker));
"""


class MarketH2HDatabase:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.executescript(SCHEMA)
        return conn

    def ingest(self, records: list[dict[str, Any]], *, source_status: str) -> int:
        if source_status != SOURCE_ACCEPTED:
            raise MarketContractError("source not accepted: economic ingestion blocked")
        normalized = [validate_h2h_quote(record) for record in records]
        conn = self.connect()
        try:
            for row in normalized:
                conn.execute("""INSERT INTO market_h2h_quotes VALUES
                    (:source_market_id,:provider,:canonical_event_id,:season,:race_id,:driver_a_id,:driver_b_id,:market_type,
                     :selection,:captured_at,:opening_captured_at,:closing_captured_at,:decision_at,:opening_odds,:closing_odds,:opponent_opening_odds,
                     :opponent_closing_odds,:bookmaker,:implied_probability_raw,:implied_probability_normalized,
                     :settlement_rule_version,:provenance_hash,:ingestion_batch_id,:data_quality_status,:session,
                     :market_margin,:provenance)""", row)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return len(normalized)


def coverage_gate(records: list[dict[str, Any]], *, scheduled_races: int,
                  options: dict[str, dict[str, float]], selected_option: str | None = None) -> dict[str, Any]:
    """Evaluate declared thresholds without silently choosing a policy."""
    if scheduled_races < 1:
        raise MarketContractError("scheduled_races must be positive")
    accepted = [record for record in records if record.get("data_quality_status") == QUALITY_ACCEPTED]
    metrics = {"duels": len(accepted),
               "race_coverage": len({record.get("canonical_event_id") for record in accepted}) / scheduled_races,
               "timestamp_coverage": sum(bool(record.get("captured_at")) for record in accepted) / len(accepted) if accepted else 0.0,
               "bookmakers": len({record.get("bookmaker") for record in accepted})}
    decisions = {name: all(metrics[key] >= value for key, value in threshold.items())
                 for name, threshold in options.items()}
    if selected_option is not None and selected_option not in decisions:
        raise MarketContractError("unknown gate option")
    if selected_option is None:
        decision = "MARKET_H2H_REQUIRES_HUMAN_DECISION" if any(decisions.values()) else "MARKET_H2H_NOT_FEASIBLE"
    else:
        decision = "MARKET_H2H_FEASIBLE" if decisions[selected_option] else "MARKET_H2H_NOT_FEASIBLE"
    return {"metrics": metrics, "options": decisions, "selected_option": selected_option, "decision": decision}
