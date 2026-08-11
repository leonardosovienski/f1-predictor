"""P4-A experimental temporal adapter for synthetic contract tests only."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from predictor_core.data.contracts import PredictionPoint
from predictor_core.measurement.replay import replay

from src import snapshots


class ExperimentalTemporalError(ValueError):
    """A synthetic P4 temporal invariant was violated."""


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ExperimentalTemporalError(f"{field} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExperimentalTemporalError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExperimentalTemporalError("value must be finite canonical JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class ExperimentalF1TemporalRecord:
    """Private test representation; deliberately not a domain/Core contract."""

    schema_version: str
    event_id: str
    predicted_at: str
    cutoff_at: str
    event_start_at: str
    matures_at: str
    result_available_at: str
    matured_at: str
    prediction_payload_hash: str
    result_payload_hash: str
    metric_name: str
    metric_scale: str
    metric_value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def adapt_f1_snapshot(
    pre: dict[str, Any],
    matured: dict[str, Any],
    *,
    cutoff_at: datetime,
    result_available_at: datetime,
    expected_result_payload_hash: str | None = None,
) -> ExperimentalF1TemporalRecord:
    """Validate and map canonical F1 artifacts without changing their schemas."""
    if snapshots._payload_hash(pre) != pre.get("payload_hash"):
        raise ExperimentalTemporalError("prediction payload hash mismatch")
    if snapshots._payload_hash(matured) != matured.get("payload_hash"):
        raise ExperimentalTemporalError("matured payload hash mismatch")
    if matured.get("pre_event_payload_hash") != pre.get("payload_hash"):
        raise ExperimentalTemporalError("PRE_EVENT to MATURED link mismatch")
    if matured.get("event_id") != pre.get("event_id"):
        raise ExperimentalTemporalError("event identity mismatch")

    predicted = snapshots._parse_utc(pre["generated_at_utc"], "predicted_at")
    event_start = snapshots._parse_utc(pre["scheduled_start_utc"], "event_start_at")
    matured_at = snapshots._parse_utc(matured["matured_at_utc"], "matured_at")
    cutoff = _aware(cutoff_at, "cutoff_at")
    available = _aware(result_available_at, "result_available_at")
    if not predicted < cutoff < event_start:
        raise ExperimentalTemporalError("requires predicted_at < cutoff_at < event_start_at")
    if available < event_start:
        raise ExperimentalTemporalError("result_available_at must be at or after event_start_at")
    if available <= predicted:
        raise ExperimentalTemporalError("result must not be available at prediction time")
    if matured_at < available:
        raise ExperimentalTemporalError("matured_at must be at or after result_available_at")

    # Reuse the current public Core boundary, but keep event/cutoff semantics local.
    point = PredictionPoint(predicted_at=predicted, matures_at=available, value=pre["model_output"])
    if not point.is_mature(matured_at):
        raise ExperimentalTemporalError("premature maturation")

    metric = matured.get("metrics", {}).get("winner_brier")
    if not isinstance(metric, (int, float)) or not math.isfinite(float(metric)):
        raise ExperimentalTemporalError("native metric must be finite")
    official_results = matured.get("official_results")
    if not isinstance(official_results, list) or not official_results:
        raise ExperimentalTemporalError("official results are required")

    result_payload_hash = _hash(official_results)
    if expected_result_payload_hash is not None and result_payload_hash != expected_result_payload_hash:
        raise ExperimentalTemporalError("result payload hash mismatch")

    return ExperimentalF1TemporalRecord(
        schema_version="p4-f1-temporal-experiment/1",
        event_id=pre["event_id"],
        predicted_at=predicted.isoformat().replace("+00:00", "Z"),
        cutoff_at=cutoff.isoformat().replace("+00:00", "Z"),
        event_start_at=event_start.isoformat().replace("+00:00", "Z"),
        matures_at=point.matures_at.isoformat().replace("+00:00", "Z"),
        result_available_at=available.isoformat().replace("+00:00", "Z"),
        matured_at=matured_at.isoformat().replace("+00:00", "Z"),
        prediction_payload_hash=pre["payload_hash"],
        result_payload_hash=result_payload_hash,
        metric_name="winner_brier",
        metric_scale="f1-native-single-winner-squared-error",
        metric_value=float(metric),
    )


def replay_record(
    record: ExperimentalF1TemporalRecord,
    *,
    input_hash: str,
    expected_input_hash: str | None = None,
) -> dict[str, Any]:
    """Replay a frozen record and bind the output to its exact input hash."""
    if expected_input_hash is not None and input_hash != expected_input_hash:
        raise ExperimentalTemporalError("replay input hash mismatch")
    event = {"input_hash": input_hash, "record": record.to_dict()}
    ledger = replay([event], lambda past: past.latest, key=lambda row: row["record"]["predicted_at"])
    return ledger[0]


def write_immutable_golden(path: Path, value: dict[str, Any]) -> None:
    """Publish a golden once; an unequal retry is an explicit error."""
    encoded = _canonical(value) + b"\n"
    if path.exists():
        if path.read_bytes() != encoded:
            raise ExperimentalTemporalError("immutable golden overwrite rejected")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
