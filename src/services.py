"""Application services; scientific code remains pure in model.py."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from predictor_ops import OperationalState

from .archival_collection import collect as collect_archive
from .clock import Clock, SystemClock
from .closure import require_open
from .contracts import (
    Capability,
    CollectionRequest,
    HealthStatus,
    PredictionRequest,
    PredictionResult,
    SettlementRequest,
)
from .data.f1_provider import F1Provider
from .model import F1EloModel
from .snapshots import mature_snapshot


class PredictionService:
    def __init__(self, *, root: Path, clock: Clock | None = None):
        self.root, self.clock = root, clock or SystemClock()

    def predict(self, request: PredictionRequest) -> PredictionResult:
        model = F1EloModel(root=self.root)
        output = (
            model.predict_race_with_grid(request.circuit, request.grid, request.weather)
            if request.grid
            else model.predict_race(request.circuit, request.weather)
        )
        identity = json.dumps(
            {"request": request.model_dump(mode="json"), "output": output},
            sort_keys=True,
            separators=(",", ":"),
        )
        return PredictionResult(
            prediction_id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
            model_name=str(output["model"]),
            model_version="scientific-baseline-2026-07-20",
            predicted_at=request.predicted_at,
            data_as_of=request.data_as_of,
            output=output,
        )


class CollectionService:
    def __init__(self, *, root: Path, provider: F1Provider | None = None):
        self.root, self.provider = root, provider

    def collect(self, request: CollectionRequest) -> dict[str, Any]:
        return collect_archive(
            season=request.season, now=request.observed_at, provider=self.provider, root=self.root
        )


class SettlementService:
    def __init__(self, *, root: Path):
        self.root = root

    def settle(self, request: SettlementRequest) -> dict[str, Any]:
        season, round_ = request.event_id.split("-r", 1)
        path = mature_snapshot(
            season=int(season.rsplit("-", 1)[-1]),
            round_=int(round_.split("-", 1)[0]),
            snapshots_root=self.root / "snapshots",
            root=self.root,
            now=request.settled_at,
        )
        return {"status": OperationalState.SUCCEEDED, "artifact": str(path)}


class F1Plugin:
    """Canonical composite plugin."""

    def __init__(self, root: Path, *, provider: F1Provider | None = None):
        self.root, self.provider = root, provider or F1Provider()
        self.predictions = PredictionService(root=root)
        self.collections = CollectionService(root=root, provider=self.provider)
        self.settlements = SettlementService(root=root)

    def predict(self, request: PredictionRequest) -> PredictionResult:
        return self.predictions.predict(request)

    def collect(self, request: CollectionRequest) -> dict[str, Any]:
        return self.collections.collect(request)

    def settle(self, request: SettlementRequest) -> dict[str, Any]:
        return self.settlements.settle(request)

    def health(self) -> HealthStatus:
        closures = []
        for track in ("H8", "H2H"):
            try:
                require_open(track, root=self.root)
            except RuntimeError:
                closures.append(f"{track}_CLOSED_BY_HUMAN_DECISION")
        caps = [
            Capability.PREDICTION,
            Capability.JOLPICA_COLLECTION,
            Capability.ARCHIVAL_COLLECTION,
            Capability.ODDS_UNAVAILABLE_FOR_F1,
            Capability.H8_CLOSED_BY_HUMAN_DECISION,
            Capability.H2H_CLOSED_BY_HUMAN_DECISION,
        ]
        return HealthStatus(
            checked_at=datetime.now(UTC),
            status="DEGRADED" if not self.provider.health_check() else "SUCCEEDED",
            capabilities=caps,
            providers={
                "jolpica": self.provider.capabilities(),
                "closures": closures,
                "core_version": version("predictor-core"),
            },
        )
