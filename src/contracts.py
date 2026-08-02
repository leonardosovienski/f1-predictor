"""Temporal and persistence contracts at the F1 domain boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TemporalKind(StrEnum):
    MUTABLE_SCHEDULE = "MUTABLE_SCHEDULE"
    PRE_EVENT_QUALIFYING = "PRE_EVENT_QUALIFYING"
    OFFICIAL_RESULT = "OFFICIAL_RESULT"
    RESULT_CORRECTION = "RESULT_CORRECTION"
    PIT_STOPS = "PIT_STOPS"


class Capability(StrEnum):
    PREDICTION = "PREDICTION"
    JOLPICA_COLLECTION = "JOLPICA_COLLECTION"
    ARCHIVAL_COLLECTION = "ARCHIVAL_COLLECTION"
    ODDS_UNAVAILABLE_FOR_F1 = "ODDS_UNAVAILABLE_FOR_F1"
    H8_CLOSED_BY_HUMAN_DECISION = "H8_CLOSED_BY_HUMAN_DECISION"
    H2H_CLOSED_BY_HUMAN_DECISION = "H2H_CLOSED_BY_HUMAN_DECISION"


class UTCModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def aware_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return value


class SourceEnvelope(UTCModel):
    schema_version: str = "f1-source/1"
    kind: TemporalKind
    event_id: str
    observed_at: datetime
    available_at: datetime
    data_as_of: datetime
    source: str
    source_record_id: str
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: dict[str, Any]
    payload: dict[str, Any] | list[dict[str, Any]]
    supersedes_hash: str | None = None


class PredictionRequest(UTCModel):
    circuit: str
    weather: str = "dry"
    predicted_at: datetime
    data_as_of: datetime
    grid: dict[str, int] | None = None


class PredictionResult(UTCModel):
    prediction_id: str
    model_name: str
    model_version: str
    predicted_at: datetime
    data_as_of: datetime
    output: dict[str, Any]
    degraded: bool = False
    degraded_reasons: list[str] = []


class CollectionRequest(UTCModel):
    season: int
    observed_at: datetime


class SettlementRequest(UTCModel):
    prediction_id: str
    event_id: str
    settled_at: datetime


class HealthStatus(UTCModel):
    checked_at: datetime
    status: str
    capabilities: list[Capability]
    providers: dict[str, Any]


@runtime_checkable
class PredictorPlugin(Protocol):
    def predict(self, request: PredictionRequest) -> PredictionResult: ...


@runtime_checkable
class CollectorPlugin(Protocol):
    def collect(self, request: CollectionRequest) -> dict[str, Any]: ...


@runtime_checkable
class SettlementPlugin(Protocol):
    def settle(self, request: SettlementRequest) -> dict[str, Any]: ...


@runtime_checkable
class HealthProvider(Protocol):
    def health(self) -> HealthStatus: ...


@runtime_checkable
class SnapshotRepository(Protocol):
    def put_if_absent(self, key: str, payload: bytes, sha256: str) -> bool: ...
    def get(self, key: str) -> bytes | None: ...


@runtime_checkable
class OperationalRepository(Protocol):
    def save_envelope(self, envelope: SourceEnvelope) -> None: ...
    def latest(self, event_id: str, kind: TemporalKind) -> SourceEnvelope | None: ...
