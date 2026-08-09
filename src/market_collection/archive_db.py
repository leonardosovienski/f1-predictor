from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS acquisition_batches (
 batch_id TEXT PRIMARY KEY, provider TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
 licence_reference TEXT NOT NULL, received_at_utc TEXT NOT NULL, obtained_by TEXT NOT NULL,
 source_schema_version TEXT NOT NULL, lifecycle_state TEXT NOT NULL, rejection_reason TEXT,
 created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS acquisition_files (
 batch_id TEXT NOT NULL, relative_path TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 sha256 TEXT NOT NULL, PRIMARY KEY(batch_id, relative_path),
 FOREIGN KEY(batch_id) REFERENCES acquisition_batches(batch_id)
);
CREATE TABLE IF NOT EXISTS market_events (
 canonical_event_id TEXT PRIMARY KEY, season INTEGER NOT NULL, round INTEGER NOT NULL,
 session TEXT NOT NULL CHECK(session='race'), scheduled_start_utc TEXT NOT NULL,
 source_event_id TEXT NOT NULL, identity_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_definitions (
 provider TEXT NOT NULL, source_market_id TEXT NOT NULL, canonical_event_id TEXT NOT NULL,
 market_type TEXT NOT NULL CHECK(market_type='race_h2h'), driver_low_id TEXT NOT NULL,
 driver_high_id TEXT NOT NULL, bookmaker TEXT NOT NULL, currency TEXT, commission_rate REAL,
 settlement_rule_version TEXT NOT NULL, settlement_rule_sha256 TEXT NOT NULL, batch_id TEXT NOT NULL,
 PRIMARY KEY(provider, source_market_id, bookmaker),
 FOREIGN KEY(batch_id) REFERENCES acquisition_batches(batch_id),
 FOREIGN KEY(canonical_event_id) REFERENCES market_events(canonical_event_id)
);
CREATE TABLE IF NOT EXISTS market_quotes (
 provider TEXT NOT NULL, source_market_id TEXT NOT NULL, bookmaker TEXT NOT NULL,
 selection_driver_id TEXT NOT NULL, published_at_utc TEXT NOT NULL, captured_at_utc TEXT NOT NULL,
 available_at_utc TEXT NOT NULL, decimal_odds REAL NOT NULL CHECK(decimal_odds>1),
 available_to_back REAL, available_to_lay REAL, traded_volume REAL, currency TEXT,
 is_in_play INTEGER NOT NULL CHECK(is_in_play IN (0,1)), source_sequence TEXT NOT NULL,
 content_sha256 TEXT NOT NULL, batch_id TEXT NOT NULL, eligible_for_decision INTEGER NOT NULL,
 ineligibility_reason TEXT,
 PRIMARY KEY(provider,source_market_id,bookmaker,selection_driver_id,published_at_utc,source_sequence),
 FOREIGN KEY(batch_id) REFERENCES acquisition_batches(batch_id)
);
CREATE TABLE IF NOT EXISTS market_settlements (
 provider TEXT NOT NULL, source_market_id TEXT NOT NULL, bookmaker TEXT NOT NULL,
 settled_at_utc TEXT NOT NULL, winner_driver_id TEXT, outcome TEXT NOT NULL,
 rule_version TEXT NOT NULL, official_result_sha256 TEXT NOT NULL,
 correction_of_sha256 TEXT, batch_id TEXT NOT NULL,
 PRIMARY KEY(provider,source_market_id,bookmaker,settled_at_utc),
 CHECK(outcome IN ('WIN_LOW','WIN_HIGH','VOID','BLOCKED')),
 FOREIGN KEY(batch_id) REFERENCES acquisition_batches(batch_id)
);
"""


class MarketArchive:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            conn = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path)
            conn.executescript(SCHEMA)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def existing_batch(self, batch_id: str) -> sqlite3.Row | None:
        if not self.path.exists():
            return None
        conn = self.connect(readonly=True)
        try:
            return conn.execute(
                "SELECT batch_id,manifest_sha256,lifecycle_state FROM acquisition_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
        finally:
            conn.close()
