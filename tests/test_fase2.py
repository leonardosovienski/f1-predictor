"""Fase 2 — blend Elo+grid, Platt e serving pós-quali."""
import numpy as np
import pytest

from src.backtest import (apply_platt, blend_elos, fit_platt,
                          run_fase2, synthetic_races_h3,
                          verdict_h3, verdict_h4)
from src.model import F1EloModel, _load_fase2_params


# ---------- Platt ----------

def test_platt_recupera_relacao_conhecida():
    """Verdade: y = Bernoulli(sigmoid(2·logit(x) + 1)). O fit deve
    recuperar a e b próximos dos verdadeiros com amostra grande."""
    rng = np.random.default_rng(0)
    x = rng.uniform(0.05, 0.95, 4000)
    true_a, true_b = 2.0, 1.0
    from src.backtest import _logit, _sigmoid
    p_true = _sigmoid(true_a * _logit(x) + true_b)
    y = (rng.uniform(size=4000) < p_true).astype(int)
    a, b = fit_platt(x, y)
    assert abs(a - true_a) < 0.3
    assert abs(b - true_b) < 0.3


def test_platt_identidade_aproximada_quando_ja_calibrado():
    """Se x JÁ é a probabilidade real (y ~ Bernoulli(x)), o fit deve
    convergir perto de a=1, b=0 (não distorce o que já está calibrado)."""
    rng = np.random.default_rng(1)
    x = rng.uniform(0.05, 0.95, 5000)
    y = (rng.uniform(size=5000) < x).astype(int)
    a, b = fit_platt(x, y)
    assert abs(a - 1.0) < 0.25
    assert abs(b) < 0.15


def test_apply_platt_preserva_ordem():
    """Calibração é monotônica: não pode inverter o ranking do modelo."""
    x = np.array([0.05, 0.2, 0.4, 0.6, 0.9])
    cal = apply_platt(x, a=1.7, b=0.3)
    assert np.all(np.diff(cal) > 0)


# ---------- blend ----------

def test_blend_elos_extremos():
    elo = np.array([1700.0, 1400.0])
    grid = np.array([1350.0, 1750.0])
    assert np.allclose(blend_elos(elo, grid, 0.0), elo)
    assert np.allclose(blend_elos(elo, grid, 1.0), grid)
    meio = blend_elos(elo, grid, 0.5)
    assert np.allclose(meio, [1525.0, 1575.0])


# ---------- protocolo dev/eval sem lookahead ----------

def _mini_races():
    return synthetic_races_h3(informative=True)


def test_w_e_platt_sao_escolhidos_so_no_dev():
    """Truncar a avaliação (2024+) não pode mudar w nem Platt — são
    ajustados inteiramente dentro do período de dev (2023)."""
    races = _mini_races()
    cheio = run_fase2(races, n_sims=1000, null_samples=50)
    truncado = run_fase2(races[:-5], n_sims=1000, null_samples=50)
    assert cheio["w_grid"] == truncado["w_grid"]
    assert cheio["platt"] == truncado["platt"]


def test_avaliacao_comeca_no_eval_start():
    races = _mini_races()
    r = run_fase2(races, n_sims=1000, null_samples=50)
    assert all(rec["season"] >= 2024 for rec in r["per_race"])


def test_sem_dev_levanta():
    races = [r for r in _mini_races() if r["season"] != 2023]
    with pytest.raises(ValueError):
        run_fase2(races, n_sims=500, null_samples=50)


# ---------- controle positivo do harness (H3) ----------

def test_h3_sensibilidade_grid_informativo():
    r = run_fase2(synthetic_races_h3(informative=True),
                  n_sims=2000, null_samples=200)
    assert verdict_h3(r)["verdict"] == "COMPROVADA"
    assert r["w_grid"] > 0.0


def test_h3_especificidade_grid_ruido():
    """Mesma 'forma do dia' na corrida, mas grid embaralhado (sem
    informação): o critério NÃO pode confirmar que o grid ajuda."""
    r = run_fase2(synthetic_races_h3(informative=False),
                  n_sims=2000, null_samples=200)
    assert verdict_h3(r)["verdict"] == "REFUTADA"


def test_verdict_h4_logica():
    melhor = {"podium": {"brier_raw": 0.10, "brier_calibrated": 0.08}}
    assert verdict_h4(melhor)["verdict"] == "COMPROVADA"
    pior = {"podium": {"brier_raw": 0.08, "brier_calibrated": 0.10}}
    assert verdict_h4(pior)["verdict"] == "REFUTADA"


# ---------- serving pós-quali ----------

def test_predict_race_with_grid_sem_fase2_params_cai_no_elo_puro(tmp_path, monkeypatch):
    monkeypatch.setattr("src.model.ROOT", tmp_path)
    model = F1EloModel(ratings_file=tmp_path / "ratings.json")
    grid = {n: i + 1 for i, n in enumerate(model.ratings)}
    r = model.predict_race_with_grid("Monza", grid)
    assert r["model"] == "elo-plackett-luce-fase0"
    assert r["w_grid"] == 0.0


def test_predict_race_with_grid_usa_blend_quando_params_existem(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fase2_params.json").write_text(
        '{"w_grid": 1.0, "platt_a": 1.0, "platt_b": 0.0, '
        '"usar_blend": true, "usar_calibracao": false}', encoding="utf-8")
    monkeypatch.setattr("src.model.ROOT", tmp_path)
    model = F1EloModel(ratings_file=tmp_path / "ratings.json")
    names = list(model.ratings)
    # inverte o grid em relação ao Elo: com w=1 (grid puro), o pole vira
    # favorito mesmo tendo o pior Elo
    grid = {n: (len(names) - i) for i, n in enumerate(names)}
    r = model.predict_race_with_grid("Monza", grid)
    assert r["model"] == "elo-grid-blend-fase2"
    pole = next(n for n, p in grid.items() if p == 1)
    assert next(iter(r["ranking"])) == pole


def test_predict_race_with_grid_valida_posicoes_repetidas(tmp_path, monkeypatch):
    monkeypatch.setattr("src.model.ROOT", tmp_path)
    model = F1EloModel(ratings_file=tmp_path / "ratings.json")
    names = list(model.ratings)[:3]
    with pytest.raises(ValueError):
        model.predict_race_with_grid("Monza", {n: 1 for n in names})


def test_load_fase2_params_default_sem_arquivo(tmp_path):
    p = _load_fase2_params(tmp_path / "nao_existe.json")
    assert p["usar_blend"] is False and p["w_grid"] == 0.0
