from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.capture_next_forward_snapshot import eligible_race
from src.closure import ResearchClosedError, require_open
from src.config import Settings
from src.contracts import Capability, SourceEnvelope, TemporalKind
from src.data.f1_provider import F1Provider
from src.model import F1EloModel, win_probability


def test_closures_cannot_be_reopened_by_environment(monkeypatch):
    monkeypatch.setenv("F1_H8_ENABLED", "true")
    monkeypatch.setenv("F1_H2H_ENABLED", "true")
    for track in ("H8", "H2H"):
        with pytest.raises(ResearchClosedError):
            require_open(track)


def test_temporal_contract_rejects_naive_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        SourceEnvelope(
            kind=TemporalKind.MUTABLE_SCHEDULE,
            event_id="f1-2026-r01",
            observed_at=datetime(2026, 1, 1),
            available_at=datetime.now(UTC),
            data_as_of=datetime.now(UTC),
            source="Jolpica",
            source_record_id="x",
            payload_hash="0" * 64,
            provenance={},
            payload={},
        )


def test_capture_window_exact_boundaries():
    quali = datetime(2026, 8, 1, 10, tzinfo=UTC)
    start = datetime(2026, 8, 2, 10, tzinfo=UTC)
    race = {"round": 1, "qualifying_start_utc": quali.isoformat(), "scheduled_start_utc": start.isoformat()}
    assert eligible_race([race], quali + timedelta(hours=2) - timedelta(microseconds=1)) is None
    assert eligible_race([race], quali + timedelta(hours=2)) == race
    assert eligible_race([race], start - timedelta(microseconds=1)) == race
    assert eligible_race([race], start) is None


def test_explicit_odds_capability():
    caps = F1Provider(offline=True).capabilities()
    assert caps["odds"] is False
    assert caps["odds_reason"] == Capability.ODDS_UNAVAILABLE_FOR_F1


def test_api_sports_aliases(monkeypatch):
    monkeypatch.setenv("API_SPORTS_F1_KEY", "alias")
    assert Settings().api_sports_key == "alias"


def test_bradley_terry_golden():
    assert win_probability(1600, 1600) == pytest.approx(0.5)
    assert win_probability(1800, 1600) == pytest.approx(0.7597469266)


def test_gumbel_plackett_luce_golden(tmp_path):
    model = F1EloModel(root=Path(__file__).parents[1])
    output = model.predict_race("Monza")
    assert output["model"] == "elo-plackett-luce-fase0"
    assert output["ranking"]["Lando Norris"]["win"] == pytest.approx(0.1149)
