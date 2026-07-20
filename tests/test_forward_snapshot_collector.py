from datetime import datetime, timezone

from scripts.capture_next_forward_snapshot import eligible_race


def _race(round_: int, qualifying: str, start: str):
    return {"round": round_, "qualifying_start_utc": qualifying,
            "scheduled_start_utc": start}


def test_eligible_only_two_hours_after_qualifying_and_before_race():
    schedule = [_race(11, "2026-07-25T14:00:00Z", "2026-07-26T13:00:00Z")]
    assert eligible_race(schedule, datetime(2026, 7, 25, 15, 59, tzinfo=timezone.utc)) is None
    assert eligible_race(schedule, datetime(2026, 7, 25, 16, 0, tzinfo=timezone.utc))["round"] == 11
    assert eligible_race(schedule, datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc)) is None


def test_eligible_skips_past_and_incomplete_schedule_rows():
    schedule = [
        {"round": 10, "scheduled_start_utc": "2026-07-19T13:00:00Z"},
        _race(10, "2026-07-18T14:00:00Z", "2026-07-19T13:00:00Z"),
        _race(11, "2026-07-25T14:00:00Z", "2026-07-26T13:00:00Z"),
    ]
    assert eligible_race(schedule, datetime(2026, 7, 25, 18, tzinfo=timezone.utc))["round"] == 11
