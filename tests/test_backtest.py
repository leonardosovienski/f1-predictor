"""Backtest prequential ordinal — plumbing do RPS, sem lookahead, DNF,
equivalência com o modelo da Fase 0 e poder do critério (harness)."""
import numpy as np
import pytest

from src.backtest import (BacktestElo, _rps_cost_matrix, _wilson,
                          evaluate_ordinal_pipeline, ladder, position_probs,
                          run_backtest, synthetic_races, verdict_h1,
                          verdict_h2)
from src.model import F1EloModel

from predictor_core.measurement.metrics import rps


# ---------- plumbing do RPS ----------

def test_cost_matrix_equivale_ao_rps_do_core():
    """A matriz de custo (atalho vetorizado do teste de permutação) tem que
    reproduzir EXATAMENTE o metrics.rps do core na atribuição identidade."""
    rng = np.random.default_rng(42)
    probs = rng.dirichlet(np.ones(8), size=8)
    outcomes = rng.permutation(8)
    cost = _rps_cost_matrix(probs)
    atalho = float(cost[np.arange(8), outcomes].mean())
    core = rps([p.tolist() for p in probs], outcomes.tolist())
    assert abs(atalho - core) < 1e-12


def test_position_probs_duplamente_estocastica():
    elos = np.array([1700.0, 1550.0, 1400.0, 1400.0])
    p = position_probs(elos, n_sims=20000, seed=13)
    assert np.allclose(p.sum(axis=1), 1.0)         # cada piloto: uma posição
    assert np.allclose(p.sum(axis=0), 1.0)         # cada posição: um piloto
    assert p[0, 0] > p[1, 0] > p[2, 0]             # Elo maior → mais P(win)
    p2 = position_probs(elos, n_sims=20000, seed=13)
    assert np.array_equal(p, p2)                   # determinístico por seed


def test_ladder():
    l3 = ladder(3)
    assert l3[0] == 1750.0 and l3[-1] == 1350.0 and l3[1] == 1550.0


def test_wilson_conhecido():
    lo, hi = _wilson(253, 404)
    assert 0.577 < lo < 0.579 and 0.671 < hi < 0.673


# ---------- equivalência com o modelo da Fase 0 ----------

def test_backtest_elo_equivale_ao_update_da_fase0(tmp_path):
    """Mesma matemática pareada: com K idênticos, o BacktestElo e o
    F1EloModel produzem os MESMOS deltas para a mesma ordem de chegada."""
    model = F1EloModel(ratings_file=tmp_path / "r.json")
    trio = ["Max Verstappen", "Lewis Hamilton", "Fernando Alonso"]
    assert all(not model.drivers[n].get("rookie") for n in trio)  # K base
    antes = {n: model.ratings[n] for n in trio}
    model.update_ratings({trio[0]: 1, trio[1]: 2, trio[2]: 3})
    deltas_fase0 = {n: model.ratings[n] - antes[n] for n in trio}

    bt = BacktestElo(k_base=24.0, k_rookie=40.0)
    for n in trio:
        bt.ratings[n] = antes[n]
        bt.races_seen[n] = 100                     # veterano → K base
    bt.update(trio)
    for n in trio:
        assert abs((bt.ratings[n] - antes[n]) - deltas_fase0[n]) < 1e-9


def test_rookie_k_maior_converge_mais_rapido():
    novato, veterano = BacktestElo(), BacktestElo()
    veterano.races_seen["A"] = veterano.races_seen["B"] = 100
    novato.update(["A", "B"])
    veterano.update(["A", "B"])
    assert novato.ratings["A"] - 1400 > veterano.ratings["A"] - 1400


# ---------- protocolo prequential ----------

def _mini_races():
    return synthetic_races(n_drivers=8, n_seasons=2, races_per_season=6,
                           seed=3)


def test_sem_lookahead():
    """A previsão da corrida r não pode depender de corridas futuras:
    rodar o backtest truncado tem que reproduzir os mesmos registros."""
    races = _mini_races()
    cheio = run_backtest(races, n_sims=500, null_samples=20)
    truncado = run_backtest(races[:-3], n_sims=500, null_samples=20)
    n = len(truncado["per_race"])
    assert cheio["per_race"][:n] == truncado["per_race"]


def test_burn_in_fora_da_avaliacao():
    races = _mini_races()                          # temporadas 2022 e 2023
    r = run_backtest(races, n_sims=500, null_samples=20)
    assert all(rec["season"] > 2022 for rec in r["per_race"])
    assert r["n_eval"] == 6


def test_dnf_ultima_posicao_e_fora_do_update():
    """DNF entra na avaliação (classificação oficial) mas não no update."""
    races = _mini_races()
    alvo = races[-1]
    dnf_nome = alvo["results"][-1]["driver"]       # último colocado abandona
    alvo["results"][-1]["dnf"] = 1
    alvo["results"][-1]["status"] = "Accident"

    com_dnf = run_backtest(races, n_sims=500, null_samples=20)
    rec = com_dnf["per_race"][-1]
    assert rec["n_dnf"] == 1
    assert "rps_model_no_dnf" in rec               # sensibilidade presente

    # rating do piloto DNF não muda na última corrida: comparar com a
    # passada em que ele TERMINA a corrida
    alvo["results"][-1]["dnf"] = 0
    alvo["results"][-1]["status"] = "Finished"
    com_fim = run_backtest(races, n_sims=500, null_samples=20)
    assert (com_dnf["final_ratings"][dnf_nome]
            != com_fim["final_ratings"][dnf_nome])


# ---------- critério ordinal e controle positivo ----------

def test_verdict_h1_logica():
    base = {"dm": {"model_vs_grid": {"dm": -3.0, "p": 0.001,
                                     "modelo_melhor": True}},
            "nullref": {"observed": 0.10, "null_p5": 0.15, "tail_p": 0.0}}
    assert verdict_h1(base)["verdict"] == "COMPROVADA"
    pior = {"dm": {"model_vs_grid": {"dm": 2.0, "p": 0.001,
                                     "modelo_melhor": False}},
            "nullref": base["nullref"]}
    assert verdict_h1(pior)["verdict"] == "REFUTADA"
    sem_info = {"dm": base["dm"],
                "nullref": {"observed": 0.15, "null_p5": 0.12, "tail_p": 0.4}}
    assert verdict_h1(sem_info)["verdict"] == "REFUTADA"


def test_verdict_h2_logica():
    ok = {"h2h_teammates": {"n": 400, "hits": 253, "acc": 0.6325,
                            "wilson95": [0.58, 0.68]}}
    assert verdict_h2(ok)["verdict"] == "COMPROVADA"
    ruim = {"h2h_teammates": {"n": 400, "hits": 210, "acc": 0.525,
                              "wilson95": [0.48, 0.57]}}
    assert verdict_h2(ruim)["verdict"] == "REFUTADA"


def test_controle_positivo_sensibilidade():
    """Forças sintéticas separadas → o critério TEM que detectar."""
    v = evaluate_ordinal_pipeline(synthetic_races(informative=True))
    assert v["verdict"] == "COMPROVADA"


def test_controle_positivo_especificidade():
    """Ruído puro (forças iguais) → o critério NÃO pode confirmar. Pega a
    armadilha do previsor flat: sem o nulo de permutação, um modelo sem
    informação 'venceria' os baselines assertivos."""
    v = evaluate_ordinal_pipeline(synthetic_races(informative=False))
    assert v["verdict"] == "REFUTADA"
    assert not v["beats_null"]
