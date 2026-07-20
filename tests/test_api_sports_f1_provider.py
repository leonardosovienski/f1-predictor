from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from src.data.api_sports_f1_provider import ApiSportsF1Provider
from predictor_core.data.contracts import DataUnavailableError


def test_lists_only_races_as_shadow_records():
    seen = {}
    payload = {"errors": {}, "response": [{
        "id": 1857, "competition": {"name": "Bahrain Grand Prix",
            "location": {"country": "Bahrain"}},
        "circuit": {"name": "Bahrain International Circuit"},
        "season": 2024, "type": "Race", "date": "2024-03-02T15:00:00+00:00",
        "status": "Completed", "laps": {"total": 57},
    }]}

    def fake(url, headers):
        seen["headers"] = headers
        seen["query"] = parse_qs(urlparse(url).query)
        return payload

    rows = ApiSportsF1Provider(api_key="synthetic-key", get_json=fake,
                              request_interval=0).list_races(
        season=2024, observed_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert seen["headers"]["x-apisports-key"] == "synthetic-key"
    assert seen["query"] == {"season": ["2024"], "type": ["Race"]}
    assert rows[0]["source_event_id"] == "1857"
    assert rows[0]["scheduled_start_utc"] == "2024-03-02T15:00:00+00:00"
    assert rows[0]["shadow_only"] is True
    assert "synthetic-key" not in repr(rows)


def test_normalizes_race_results():
    payload = {"errors": {}, "response": [{
        "race": {"id": 1857},
        "driver": {"id": 25, "name": "Max Verstappen", "abbr": "VER"},
        "team": {"id": 1, "name": "Red Bull Racing"},
        "position": 1, "time": "1:31:44.742", "laps": 57, "grid": "1", "pits": 2,
    }]}
    rows = ApiSportsF1Provider(
        api_key="synthetic", get_json=lambda *_: payload,
        request_interval=0).race_results(race_id=1857)
    assert rows == [{
        "source": "api_sports_f1", "source_event_id": "1857",
        "driver_source_id": 25, "driver": "Max Verstappen", "driver_code": "VER",
        "team": "Red Bull Racing", "position": 1, "grid": "1", "laps": 57,
        "pits": 2, "elapsed_or_gap": "1:31:44.742", "shadow_only": True,
    }]


def test_rejects_season_outside_free_plan_without_request():
    provider = ApiSportsF1Provider(
        api_key="synthetic", get_json=lambda *_: pytest.fail("não deveria consultar"),
        request_interval=0)
    with pytest.raises(DataUnavailableError, match="2022-2024"):
        provider.list_races(season=2026)


def test_requires_secret(monkeypatch):
    monkeypatch.delenv("API_SPORTS_F1_KEY", raising=False)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with pytest.raises(DataUnavailableError, match="API_SPORTS_F1_KEY"):
        ApiSportsF1Provider(get_json=lambda *_: {}, request_interval=0).list_races(season=2024)


def test_rate_limit_spaces_consecutive_requests():
    now = [100.0]
    sleeps = []
    def clock(): return now[0]
    def sleeper(seconds): sleeps.append(seconds); now[0] += seconds
    provider = ApiSportsF1Provider(
        api_key="synthetic", request_interval=6.1, clock=clock, sleeper=sleeper,
        get_json=lambda *_: {"errors": {}, "response": []})
    provider.race_results(race_id=1)
    provider.race_results(race_id=2)
    assert sleeps == [6.1]
