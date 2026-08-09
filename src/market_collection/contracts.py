from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BatchState(StrEnum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class ZoneOneModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return value


class SourceFile(ZoneOneModel):
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("path")
    @classmethod
    def relative_safe_path(cls, value: str) -> str:
        if not value.strip() or "\0" in value:
            raise ValueError("source path is required")
        return value


class BatchManifest(ZoneOneModel):
    schema_version: str = Field(pattern=r"^market-raw-batch/1$")
    batch_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    provider: str = Field(min_length=1)
    received_at: datetime
    obtained_by: str = Field(min_length=1)
    licence_reference: str = Field(min_length=1)
    licence_allows_research_storage: bool
    licence_allows_derived_results: bool
    source_schema_version: str = Field(min_length=1)
    source_files: list[SourceFile] = Field(min_length=1)
    export_parameters: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

    @model_validator(mode="after")
    def unique_paths_and_licence(self) -> BatchManifest:
        paths = [item.path for item in self.source_files]
        if len(paths) != len(set(paths)):
            raise ValueError("source paths must be unique")
        if not self.licence_allows_research_storage or not self.licence_allows_derived_results:
            raise ValueError("licence does not permit the required research use")
        return self


class QuoteRecord(ZoneOneModel):
    selection_driver_id: str = Field(min_length=1)
    published_at_utc: datetime
    captured_at_utc: datetime
    available_at_utc: datetime
    decimal_odds: float = Field(gt=1)
    available_to_back: float | None = Field(default=None, ge=0)
    available_to_lay: float | None = Field(default=None, ge=0)
    traded_volume: float | None = Field(default=None, ge=0)
    currency: str | None = None
    is_in_play: bool = False
    source_sequence: str = Field(min_length=1)

    @model_validator(mode="after")
    def causal_order(self) -> QuoteRecord:
        if not self.published_at_utc <= self.captured_at_utc <= self.available_at_utc:
            raise ValueError("quote timestamps violate causal order")
        return self


class SettlementRecord(ZoneOneModel):
    settled_at_utc: datetime
    winner_driver_id: str | None = None
    outcome: str
    rule_version: str = Field(min_length=1)
    official_result_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    correction_of_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("outcome")
    @classmethod
    def valid_outcome(cls, value: str) -> str:
        if value not in {"WIN_LOW", "WIN_HIGH", "VOID", "BLOCKED"}:
            raise ValueError("invalid settlement outcome")
        return value


class MarketRecord(ZoneOneModel):
    provider: str = Field(min_length=1)
    source_market_id: str = Field(min_length=1)
    canonical_event_id: str = Field(pattern=r"^f1-[0-9]{4}-r[0-9]{2}-race$")
    season: int = Field(ge=1950)
    round: int = Field(ge=1)
    scheduled_start_utc: datetime
    source_event_id: str = Field(min_length=1)
    driver_a_id: str = Field(min_length=1)
    driver_b_id: str = Field(min_length=1)
    bookmaker: str = Field(min_length=1)
    market_type: str = "race_h2h"
    session: str = "race"
    currency: str | None = None
    commission_rate: float | None = Field(default=None, ge=0, lt=1)
    settlement_rule_version: str = Field(min_length=1)
    settlement_rule_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    quotes: list[QuoteRecord] = Field(min_length=1)
    settlement: SettlementRecord | None = None

    @model_validator(mode="after")
    def market_identity(self) -> MarketRecord:
        if self.provider.strip() == "" or self.driver_a_id == self.driver_b_id:
            raise ValueError("invalid market identity")
        if self.market_type != "race_h2h" or self.session != "race":
            raise ValueError("only race H2H markets are accepted")
        expected = f"f1-{self.season}-r{self.round:02d}-race"
        if self.canonical_event_id != expected:
            raise ValueError("canonical event identity mismatch")
        selections = {quote.selection_driver_id for quote in self.quotes}
        if not selections <= {self.driver_a_id, self.driver_b_id}:
            raise ValueError("quote selection is outside the H2H pair")
        return self


class IngestReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    state: BatchState
    imported_markets: int = 0
    imported_quotes: int = 0
    ineligible_quotes: int = 0
    reason: str | None = None
    idempotent: bool = False


class MarketQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archive_path: str
    batches: int
    markets: int
    eligible_quotes: int
    duels: int
    race_coverage: float
    timestamp_coverage: float
    both_sides_coverage: float
    settlement_coverage: float
    volume_coverage: float
    bookmakers: int
    ambiguous_identities: int
    selected_option: str | None = None
    option_results: dict[str, bool]
    decision: str
