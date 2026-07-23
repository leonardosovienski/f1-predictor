"""Serving (src/predict.py) — ranking, H2H, PredictionPoint, log isolado."""
import json
from datetime import datetime, timezone

import pytest

from src import predict


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("PREDICTIONS_LOG_PATH", str(tmp_path / "pred.jsonl"))
    monkeypatch.setenv("PREDICTOR_EVENTS_PATH", str(tmp_path / "events.jsonl"))
    yield


def test_run_race_ranking_completo():
    r = predict.run_race("Monza", "dry")
    assert r["n_drivers"] == 22
    assert abs(sum(v["win"] for v in r["ranking"].values()) - 1.0) < 0.01


def test_carimbo_prediction_point():
    now = datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc)
    r = predict.run_race("Monza", now=now)
    assert r["predicted_at"] == "2026-07-11T14:00:00+00:00"
    assert r["matures_at"] == "2026-07-11T16:30:00+00:00"     # +2h30


def test_cli_race_json(capsys):
    rc = predict.main(["--circuit", "Monza", "--weather", "dry", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["ranking"]) == 22
    fav = next(iter(out["ranking"]))
    assert {"win", "podium", "top6"} <= set(out["ranking"][fav])


def test_cli_h2h_json(capsys):
    rc = predict.main(["--head-to-head", "Verstappen", "Hamilton",
                       "--circuit", "Monaco", "--json"])
    assert rc == 2
    assert "CLOSED_BY_HUMAN_DECISION" in capsys.readouterr().err


def test_cli_market_podium(capsys):
    rc = predict.main(["--circuit", "Monza", "--market", "podium"])
    assert rc == 0
    assert "ordenado por podium" in capsys.readouterr().out


def test_cli_erros():
    assert predict.main(["--circuit", "Circuito Fantasma", "--json"]) == 2
    assert predict.main(["--head-to-head", "Fantasma", "Hamilton",
                         "--circuit", "Monza", "--json"]) == 2
