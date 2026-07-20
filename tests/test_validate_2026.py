from datetime import datetime, timezone

import pytest

from scripts.validate_2026 import proxima_corrida


def test_proxima_corrida_exclui_evento_que_ja_largou_no_mesmo_dia():
    schedule = [
        {"round": 10, "date": "2026-07-20",
         "scheduled_start_utc": "2026-07-20T13:00:00Z"},
        {"round": 11, "date": "2026-07-27",
         "scheduled_start_utc": "2026-07-27T14:00:00Z"},
    ]
    now = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)
    assert proxima_corrida(schedule, now=now)["round"] == 11


def test_proxima_corrida_preserva_evento_do_dia_antes_da_largada():
    schedule = [{"round": 10, "date": "2026-07-20",
                 "scheduled_start_utc": "2026-07-20T13:00:00Z"}]
    now = datetime(2026, 7, 20, 12, 59, tzinfo=timezone.utc)
    assert proxima_corrida(schedule, now=now)["round"] == 10


def test_proxima_corrida_rejeita_relogio_sem_timezone():
    with pytest.raises(ValueError, match="timezone"):
        proxima_corrida([], now=datetime(2026, 7, 20, 12, 0))
