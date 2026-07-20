from datetime import datetime, timezone

import pytest

from src.data.openf1_provider import OpenF1Provider


def test_openf1_sessions_are_temporal_shadow_records():
    payload = [{"session_key": 42, "meeting_key": 7,
                "meeting_name": "Brazilian Grand Prix",
                "date_start": "2026-11-08T17:00:00+00:00"}]
    provider = OpenF1Provider(get_json=lambda _url: payload)
    rows = provider.list_race_sessions(
        2026, observed_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert rows == [{"source": "openf1", "source_session_id": 42,
                     "meeting_key": 7, "name": "Brazilian Grand Prix",
                     "scheduled_start_utc": "2026-11-08T17:00:00+00:00",
                     "observed_at": "2026-07-20T00:00:00+00:00",
                     "shadow_only": True}]


def test_openf1_rejects_naive_observation_clock():
    with pytest.raises(ValueError, match="timezone"):
        OpenF1Provider(get_json=lambda _url: []).list_race_sessions(
            2026, observed_at=datetime(2026, 7, 20))
