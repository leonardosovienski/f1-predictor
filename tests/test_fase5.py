"""Fase 5 — H8-F1: choque estrutural de transição de regulamento."""
import json
from pathlib import Path

import pytest

from src.backtest import (BacktestElo, calibrate_shrink_factor_sintetico,
                          evaluate_h8_pipeline, evaluate_transition_shock_pipeline,
                          run_h8, run_h8_historical_windows,
                          synthetic_races_transition, verdict_h8)


# ---------- shrink_to_mean ----------

def test_shrink_to_mean_zero_e_no_op():
    elo = BacktestElo()
    elo.update(["A", "B", "C"])
    antes = dict(elo.ratings)
    elo.shrink_to_mean(0.0)
    assert elo.ratings == antes


def test_shrink_to_mean_um_reseta_pra_semente():
    elo = BacktestElo()
    elo.update(["A", "B", "C"])
    elo.shrink_to_mean(1.0)
    assert all(abs(v - elo.seed_elo) < 1e-9 for v in elo.ratings.values())


def test_shrink_to_mean_parcial():
    elo = BacktestElo()
    elo.ratings["A"] = 1600.0
    elo.shrink_to_mean(0.5)
    assert abs(elo.ratings["A"] - 1500.0) < 1e-9    # meio caminho ate 1400


def test_shrink_to_mean_valida_fator():
    elo = BacktestElo()
    with pytest.raises(ValueError):
        elo.shrink_to_mean(1.5)
    with pytest.raises(ValueError):
        elo.shrink_to_mean(-0.1)


def _historical_fixture():
    races, _ = synthetic_races_transition(
        n_drivers=8, n_seasons_before=2, races_per_season=8)
    # generator starts at 2022; relabel to an arbitrary historical window
    return [{**race, "season": race["season"] - 8} for race in races[:24]]


def test_h8_historical_is_separate_and_uses_frozen_window():
    result = run_h8_historical_windows(
        _historical_fixture(), transitions=(2016,), burn_in_seasons=2,
        window=8, n_sims=200)
    assert result["n"] == 8
    assert result["forward_h8_unchanged"] is True
    assert len(result["races"]) == 8
    assert result["protocol"]["shrink_factor"] == 0.8
    assert result["classification"] in {
        "SUPPORTED_HISTORICALLY", "NOT_SUPPORTED_HISTORICALLY",
        "INCONCLUSIVE_HISTORICALLY"}


def test_h8_historical_rejects_missing_burn_in():
    with pytest.raises(ValueError, match="temporadas ausentes"):
        run_h8_historical_windows(
            [race for race in _historical_fixture() if race["season"] != 2014],
            transitions=(2016,), burn_in_seasons=2, window=8, n_sims=100)


def test_h8_historical_artifact_is_retrospective_and_complete():
    artifact = Path(__file__).parents[1] / "data" / "backtest_h8_historical.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["artifact_kind"] == "H8_RETROSPECTIVE_AUXILIARY"
    assert payload["classification"] == "NOT_SUPPORTED_HISTORICALLY"
    assert payload["n"] == len(payload["races"]) == 24
    assert payload["forward_h8_unchanged"] is True
    assert payload["mean_delta"] > 0
    assert payload["dm"]["p_value"] < 0.05
    assert len(payload["input_hashes"]) == 188


# ---------- calibração cega + harness ----------

def test_calibracao_cega_so_usa_sintetico():
    """A calibração não recebe nem pode receber dado real — só produz
    um fator a partir do gerador sintético."""
    cal = calibrate_shrink_factor_sintetico()
    assert 0.0 <= cal["factor"] <= 1.0
    assert len(cal["losses_por_candidato"]) >= 5


def test_h8_sensibilidade_e_especificidade():
    cal = calibrate_shrink_factor_sintetico()
    edge = evaluate_transition_shock_pipeline(reshuffle=True,
                                              shrink_factor=cal["factor"])
    assert edge["ajuda"] is True
    noise = evaluate_transition_shock_pipeline(reshuffle=False,
                                               shrink_factor=cal["factor"])
    assert noise["ajuda"] is False


def test_evaluate_h8_pipeline_contrato_do_harness():
    edge = evaluate_h8_pipeline(synthetic_races_transition(reshuffle=True))
    assert edge["verdict"] == "COMPROVADA"
    noise = evaluate_h8_pipeline(synthetic_races_transition(reshuffle=False))
    assert noise["verdict"] == "REFUTADA"


# ---------- run_h8 (aplicação real) ----------

def _mini_races_com_transicao():
    races, _ = synthetic_races_transition(n_seasons_before=1, races_per_season=15,
                                          reshuffle=True)
    return races


def test_run_h8_nao_afeta_temporadas_sem_transicao():
    races = _mini_races_com_transicao()
    r = run_h8(races, shrink_factor=0.8, n_sims=500, transition_seasons=(2099,))
    for s, row in r["por_temporada"].items():
        assert abs(row["rps_com_choque"] - row["rps_sem_choque"]) < 1e-9


def test_run_h8_aplica_na_temporada_de_transicao():
    races = _mini_races_com_transicao()
    fronteira = 2022 + 1     # synthetic_races_transition com n_seasons_before=1
    r = run_h8(races, shrink_factor=0.8, n_sims=800,
              transition_seasons=(fronteira,), burn_in_season=2021)
    row = r["por_temporada"][fronteira]
    assert row["rps_com_choque"] != row["rps_sem_choque"]
    assert "dm" in row


def test_verdict_h8_logica():
    bom = {"dm_2026": {"dm": -2.0, "p": 0.01, "com_choque_melhor": True},
          "shrink_factor": 0.8}
    assert verdict_h8(bom)["verdict"] == "COMPROVADA"
    fraco = {"dm_2026": {"dm": -0.1, "p": 0.9, "com_choque_melhor": True},
            "shrink_factor": 0.8}
    assert verdict_h8(fraco)["verdict"] == "REFUTADA"
    sem_dados = {"dm_2026": None, "shrink_factor": 0.8}
    assert verdict_h8(sem_dados)["verdict"] == "REFUTADA"
