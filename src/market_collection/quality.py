from __future__ import annotations

from pathlib import Path

from .archive_db import MarketArchive
from .contracts import MarketQualityReport

DEFAULT_OPTIONS: dict[str, dict[str, float]] = {
    "pilot_diagnostic_not_stage1": {
        "duels": 100,
        "race_coverage": 0.60,
        "timestamp_coverage": 0.95,
        "bookmakers": 2,
    },
    "intermediate_descriptive_only": {
        "duels": 250,
        "race_coverage": 0.70,
        "timestamp_coverage": 0.97,
        "bookmakers": 2,
    },
    "stage1_authorization_candidate": {
        "duels": 500,
        "race_coverage": 0.80,
        "timestamp_coverage": 0.98,
        "bookmakers": 3,
    },
}


def assess_market_quality(
    archive_path: Path | str,
    *,
    scheduled_races: int,
    options: dict[str, dict[str, float]] | None = None,
    selected_option: str | None = None,
) -> MarketQualityReport:
    if scheduled_races < 1:
        raise ValueError("scheduled_races must be positive")
    thresholds = options or DEFAULT_OPTIONS
    if selected_option is not None and selected_option not in thresholds:
        raise ValueError("unknown selected option")
    archive = MarketArchive(archive_path)
    conn = archive.connect(readonly=True)
    try:
        batches = conn.execute(
            "SELECT count(*) FROM acquisition_batches WHERE lifecycle_state='NORMALIZED'"
        ).fetchone()[0]
        markets = conn.execute("SELECT count(*) FROM market_definitions").fetchone()[0]
        eligible = conn.execute(
            "SELECT count(*) FROM market_quotes WHERE eligible_for_decision=1"
        ).fetchone()[0]
        duels = conn.execute("SELECT count(*) FROM market_definitions").fetchone()[0]
        event_count = conn.execute(
            "SELECT count(DISTINCT canonical_event_id) FROM market_definitions"
        ).fetchone()[0]
        bookmakers = conn.execute("SELECT count(DISTINCT bookmaker) FROM market_definitions").fetchone()[0]
        timestamp_ok = conn.execute(
            "SELECT count(*) FROM market_quotes WHERE eligible_for_decision=1 AND published_at_utc IS NOT NULL AND captured_at_utc IS NOT NULL"
        ).fetchone()[0]
        both_sides = conn.execute(
            """SELECT count(*) FROM (
                 SELECT q.provider,q.source_market_id,q.bookmaker
                 FROM market_quotes q WHERE q.eligible_for_decision=1
                 GROUP BY q.provider,q.source_market_id,q.bookmaker
                 HAVING count(DISTINCT q.selection_driver_id)=2
               )"""
        ).fetchone()[0]
        settlements = conn.execute("SELECT count(*) FROM market_settlements").fetchone()[0]
        volume = conn.execute(
            "SELECT count(*) FROM market_quotes WHERE eligible_for_decision=1 AND traded_volume IS NOT NULL"
        ).fetchone()[0]
        ambiguous = conn.execute(
            "SELECT count(*) FROM market_events WHERE identity_status!='CANONICAL'"
        ).fetchone()[0]
    finally:
        conn.close()
    metrics: dict[str, float] = {
        "duels": float(duels),
        "race_coverage": event_count / scheduled_races,
        "timestamp_coverage": timestamp_ok / eligible if eligible else 0.0,
        "bookmakers": float(bookmakers),
    }
    option_results = {
        name: all(metrics[key] >= minimum for key, minimum in limits.items())
        for name, limits in thresholds.items()
    }
    if selected_option is None:
        decision = (
            "MARKET_H2H_REQUIRES_HUMAN_DECISION"
            if any(option_results.values())
            else "MARKET_H2H_NOT_FEASIBLE"
        )
    else:
        decision = (
            "MARKET_H2H_FEASIBLE_FOR_PROTOCOL_DESIGN"
            if option_results[selected_option]
            else "MARKET_H2H_NOT_FEASIBLE"
        )
    return MarketQualityReport(
        archive_path=str(Path(archive_path)),
        batches=batches,
        markets=markets,
        eligible_quotes=eligible,
        duels=duels,
        race_coverage=metrics["race_coverage"],
        timestamp_coverage=metrics["timestamp_coverage"],
        both_sides_coverage=both_sides / markets if markets else 0.0,
        settlement_coverage=settlements / markets if markets else 0.0,
        volume_coverage=volume / eligible if eligible else 0.0,
        bookmakers=bookmakers,
        ambiguous_identities=ambiguous,
        selected_option=selected_option,
        option_results=option_results,
        decision=decision,
    )
