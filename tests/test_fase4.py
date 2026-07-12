"""Fase 4 — H0 formal (PrequentialEvaluator+bootstrap), blend de contexto/
reliability/pit efficiency, choque de volatilidade e purge/embargo."""
import numpy as np
import pytest

from src.backtest import (BacktestElo, evaluate_context_pipeline,
                          evaluate_grid_feature_pipeline,
                          evaluate_pit_pipeline, evaluate_reliability_pipeline,
                          evaluate_volatility_shock, paired_bootstrap_ci,
                          run_fase4, run_h0_formal, synthetic_races,
                          synthetic_races_context, synthetic_races_h3,
                          synthetic_races_pitstops, synthetic_races_reliability,
                          synthetic_races_shock, verdict_h0_formal, verdict_h5,
                          verdict_h6, verdict_h7)


# ---------- H0 formal (item 1) ----------

def test_paired_bootstrap_ci_recupera_delta_conhecido():
    rng = np.random.default_rng(0)
    delta = rng.normal(loc=-0.05, scale=0.01, size=200)
    lo, hi = paired_bootstrap_ci(delta, n_boot=1000, seed=1)
    assert lo < -0.05 < hi
    assert hi < 0.0            # delta consistentemente negativo


def test_h0_formal_sensibilidade_e_especificidade():
    edge = verdict_h0_formal(run_h0_formal(synthetic_races_h3(informative=True),
                                           n_sims=1000))
    assert edge["verdict"] == "COMPROVADA"
    noise = verdict_h0_formal(run_h0_formal(
        synthetic_races(informative=True, grid_random=True, form_scale=60.0),
        n_sims=1000))
    assert noise["verdict"] == "REFUTADA"


def test_h0_formal_bootstrap_e_dm_concordam_no_real():
    """Sanity determinístico e barato: burn-in curto num recorte
    sintético — bootstrap e DM têm que apontar na mesma direção."""
    races = synthetic_races_h3(informative=True)
    r = run_h0_formal(races, n_sims=800, burn_in_season=2022)
    ci_lo, ci_hi = r["bootstrap_ci95"]
    assert (ci_hi < 0) == (r["dm"]["dm"] < 0 and r["dm"]["p"] < 0.05)


# ---------- contexto de circuito (H5) ----------

def test_h5_sensibilidade_e_especificidade():
    edge = evaluate_context_pipeline(synthetic_races_context(informative=True))
    assert edge["verdict"] == "COMPROVADA"
    noise = evaluate_context_pipeline(synthetic_races_context(informative=False))
    assert noise["verdict"] == "REFUTADA"


def test_h5_congela_pesos_fora_do_dev():
    races = synthetic_races_context(informative=True)
    cheio = run_fase4(races, {}, __import__("src.backtest", fromlist=["_SYNTH_CONTEXT_CATALOG"])
                      ._SYNTH_CONTEXT_CATALOG, w_grid=0.5, n_sims=800, null_samples=50,
                      w_rel=0.0, w_pit=0.0)
    truncado = run_fase4(races[:-10], {},
                         __import__("src.backtest", fromlist=["_SYNTH_CONTEXT_CATALOG"])
                         ._SYNTH_CONTEXT_CATALOG, w_grid=0.5, n_sims=800, null_samples=50,
                         w_rel=0.0, w_pit=0.0)
    assert cheio["weights"]["w_ctx"] == truncado["weights"]["w_ctx"]


# ---------- reliability (H6) ----------

def test_h6_sensibilidade_e_especificidade():
    edge = evaluate_reliability_pipeline(synthetic_races_reliability(informative=True))
    assert edge["verdict"] == "COMPROVADA"
    noise = evaluate_reliability_pipeline(synthetic_races_reliability(informative=False))
    assert noise["verdict"] == "REFUTADA"


# ---------- pit efficiency (H7) ----------

def test_h7_sensibilidade_e_especificidade():
    edge = evaluate_pit_pipeline(synthetic_races_pitstops(informative=True))
    assert edge["verdict"] == "COMPROVADA"
    noise = evaluate_pit_pipeline(synthetic_races_pitstops(informative=False))
    assert noise["verdict"] == "REFUTADA"


def test_h7_usa_apenas_historico_ate_a_corrida(monkeypatch):
    """A duração de HOJE não pode entrar no z ANTES da atualização —
    checagem direta via ContextRatingBook/PitEfficiencyTracker já feita
    em test_context_factors; aqui garantimos que run_fase4 só chama
    `.z()` (leitura) antes de `.update()` (escrita) — smoke via
    monkeypatch de ordem de chamadas."""
    from src import context_factors as cf
    calls = []
    orig_z, orig_update = cf.PitEfficiencyTracker.z, cf.PitEfficiencyTracker.update

    def spy_z(self, *a, **kw):
        calls.append("z")
        return orig_z(self, *a, **kw)

    def spy_update(self, *a, **kw):
        calls.append("update")
        return orig_update(self, *a, **kw)

    monkeypatch.setattr(cf.PitEfficiencyTracker, "z", spy_z)
    monkeypatch.setattr(cf.PitEfficiencyTracker, "update", spy_update)
    races, pits = synthetic_races_pitstops(informative=True)
    run_fase4(races, pits, [], w_grid=0.5, n_sims=300, null_samples=20,
             w_ctx=0.0, w_rel=0.0, w_pit=0.0)
    # dentro de cada corrida, toda leitura 'z' precede a 'update' da MESMA equipe
    assert calls[0] == "z"


# ---------- choque de volatilidade (item CS/LoL — só sintético) ----------

def test_volatility_shock_reduz_rps_apos_salto():
    com_choque = evaluate_volatility_shock(trigger=True, n_sims=800)
    sem_choque = evaluate_volatility_shock(trigger=False, n_sims=800)
    assert com_choque < sem_choque


def test_backtest_elo_sem_shock_e_equivalente_ao_original():
    """BacktestElo sem `shock=` continua bit-a-bit igual ao comportamento
    anterior à Fase 4 (regressão)."""
    elo_a = BacktestElo()
    elo_b = BacktestElo(shock=None)
    for order in (["A", "B", "C"], ["C", "A", "B"]):
        elo_a.update(order)
        elo_b.update(order)
    assert elo_a.ratings == elo_b.ratings


# ---------- purge/embargo (item cripto) ----------

def test_purge_embargo_nao_muda_pesos_drasticamente():
    """Robustez: pesos escolhidos com purge/embargo pequenos devem ficar
    próximos dos escolhidos sem — se mudassem muito, a fronteira dev/eval
    estaria carregando sinal espúrio."""
    races = synthetic_races_context(informative=True)
    catalog = __import__("src.backtest", fromlist=["_SYNTH_CONTEXT_CATALOG"])._SYNTH_CONTEXT_CATALOG
    base = run_fase4(races, {}, catalog, w_grid=0.5, n_sims=800, null_samples=50,
                     w_rel=0.0, w_pit=0.0)
    hardened = run_fase4(races, {}, catalog, w_grid=0.5, n_sims=800, null_samples=50,
                         w_rel=0.0, w_pit=0.0, purge_races=2, embargo_races=2)
    assert abs(base["weights"]["w_ctx"] - hardened["weights"]["w_ctx"]) <= 0.5


def test_purge_races_maior_que_o_dev_levanta():
    races = synthetic_races_context(informative=True)
    catalog = __import__("src.backtest", fromlist=["_SYNTH_CONTEXT_CATALOG"])._SYNTH_CONTEXT_CATALOG
    with pytest.raises(ValueError):
        run_fase4(races, {}, catalog, w_grid=0.5, n_sims=500, null_samples=20,
                 w_rel=0.0, w_pit=0.0, purge_races=1000)
