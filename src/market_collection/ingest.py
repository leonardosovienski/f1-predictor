from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .archive_db import MarketArchive
from .contracts import BatchState, IngestReport, MarketRecord
from .manifest import ManifestError, canonical_sha256, load_and_verify_manifest


class MarketCollectionError(RuntimeError):
    pass


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_records(paths: list[Path]) -> list[MarketRecord]:
    records: list[MarketRecord] = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketCollectionError(f"invalid source JSON {path.name}: {exc}") from exc
        if not isinstance(raw, list):
            raise MarketCollectionError(f"source JSON must contain a list: {path.name}")
        try:
            records.extend(MarketRecord.model_validate(item) for item in raw)
        except ValueError as exc:
            raise MarketCollectionError(f"source contract violation in {path.name}: {exc}") from exc
    return records


def ingest_batch(manifest_path: Path | str, archive_path: Path | str) -> IngestReport:
    try:
        manifest, manifest_hash, source_paths = load_and_verify_manifest(Path(manifest_path))
    except ManifestError as exc:
        raise MarketCollectionError(str(exc)) from exc
    archive = MarketArchive(archive_path)
    existing = archive.existing_batch(manifest.batch_id)
    if existing is not None:
        if (
            existing["manifest_sha256"] == manifest_hash
            and existing["lifecycle_state"] == BatchState.NORMALIZED
        ):
            return IngestReport(batch_id=manifest.batch_id, state=BatchState.NORMALIZED, idempotent=True)
        raise MarketCollectionError("batch id already exists with different content or terminal state")
    records = _load_records(source_paths)
    conn = archive.connect()
    markets = quotes = ineligible = 0
    now = _utc_text(datetime.now(UTC))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO acquisition_batches VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                manifest.batch_id,
                manifest.provider,
                manifest_hash,
                manifest.licence_reference,
                _utc_text(manifest.received_at),
                manifest.obtained_by,
                manifest.source_schema_version,
                BatchState.RECEIVED,
                None,
                now,
            ),
        )
        for item in manifest.source_files:
            conn.execute(
                "INSERT INTO acquisition_files VALUES (?,?,?,?)",
                (manifest.batch_id, item.path, item.size_bytes, item.sha256.lower()),
            )
        for record in records:
            if record.provider != manifest.provider:
                raise MarketCollectionError("record provider differs from manifest provider")
            low, high = sorted((record.driver_a_id, record.driver_b_id))
            conn.execute(
                "INSERT OR IGNORE INTO market_events VALUES (?,?,?,?,?,?,?)",
                (
                    record.canonical_event_id,
                    record.season,
                    record.round,
                    record.session,
                    _utc_text(record.scheduled_start_utc),
                    record.source_event_id,
                    "CANONICAL",
                ),
            )
            conn.execute(
                "INSERT INTO market_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.provider,
                    record.source_market_id,
                    record.canonical_event_id,
                    record.market_type,
                    low,
                    high,
                    record.bookmaker,
                    record.currency,
                    record.commission_rate,
                    record.settlement_rule_version,
                    record.settlement_rule_sha256.lower(),
                    manifest.batch_id,
                ),
            )
            markets += 1
            for quote in record.quotes:
                eligible = not quote.is_in_play and quote.published_at_utc < record.scheduled_start_utc
                reason = None if eligible else "IN_PLAY_OR_POST_EVENT"
                content = quote.model_dump(mode="json")
                conn.execute(
                    "INSERT INTO market_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.provider,
                        record.source_market_id,
                        record.bookmaker,
                        quote.selection_driver_id,
                        _utc_text(quote.published_at_utc),
                        _utc_text(quote.captured_at_utc),
                        _utc_text(quote.available_at_utc),
                        quote.decimal_odds,
                        quote.available_to_back,
                        quote.available_to_lay,
                        quote.traded_volume,
                        quote.currency,
                        int(quote.is_in_play),
                        quote.source_sequence,
                        canonical_sha256(content),
                        manifest.batch_id,
                        int(eligible),
                        reason,
                    ),
                )
                quotes += 1
                ineligible += int(not eligible)
            if record.settlement is not None:
                settlement = record.settlement
                conn.execute(
                    "INSERT INTO market_settlements VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.provider,
                        record.source_market_id,
                        record.bookmaker,
                        _utc_text(settlement.settled_at_utc),
                        settlement.winner_driver_id,
                        settlement.outcome,
                        settlement.rule_version,
                        settlement.official_result_sha256.lower(),
                        settlement.correction_of_sha256,
                        manifest.batch_id,
                    ),
                )
        conn.execute(
            "UPDATE acquisition_batches SET lifecycle_state=? WHERE batch_id=?",
            (BatchState.NORMALIZED, manifest.batch_id),
        )
        conn.commit()
    except (sqlite3.Error, MarketCollectionError, ValueError) as exc:
        conn.rollback()
        raise MarketCollectionError(f"batch ingestion failed atomically: {exc}") from exc
    finally:
        conn.close()
    return IngestReport(
        batch_id=manifest.batch_id,
        state=BatchState.NORMALIZED,
        imported_markets=markets,
        imported_quotes=quotes,
        ineligible_quotes=ineligible,
    )
