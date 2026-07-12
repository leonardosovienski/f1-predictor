"""Governança da Fase 1 — trials VERSIONADAS, atestado do harness e
consistência dos artefatos do backtest.

trials.json, o atestado e backtest_fase1.json são versionados (o
denominador do data-snooping tem que sobreviver ao esquecimento seletivo).
ratings.json e f1.db são runtime (gitignored) — testes que dependem deles
pulam quando ausentes em clone fresco.
"""
import json

import pytest

from src.backtest import verdict_h1
from src.config import ROOT, load_drivers

from predictor_core.measurement.trials import (attestation_path_for,
                                               validate_trials)

TRIALS = ROOT / "data" / "trials.json"
BACKTEST = ROOT / "data" / "backtest_fase1.json"
RATINGS = ROOT / "data" / "ratings.json"


def test_trials_versionadas_e_conformes():
    assert TRIALS.exists(), "data/trials.json é VERSIONADO — não pode sumir"
    trials = json.loads(TRIALS.read_text(encoding="utf-8"))
    assert validate_trials(trials) == []
    nomes = {t["name"] for t in trials}
    assert {"H1-F1-elo-pl-vs-grid-rps", "H2-F1-h2h-companheiros"} <= nomes


def test_atestado_do_harness_presente():
    att = attestation_path_for(TRIALS)
    assert att.exists(), ("trials sem atestado de controle positivo — rode "
                          "scripts/run_backtest.py")
    record = json.loads(att.read_text(encoding="utf-8"))
    assert record.get("passed_at")
    assert record.get("edge_verdict") == "COMPROVADA"


def test_backtest_resultados_consistentes():
    assert BACKTEST.exists(), "rode scripts/run_backtest.py"
    r = json.loads(BACKTEST.read_text(encoding="utf-8"))
    assert r["n_eval"] == len(r["per_race"]) >= 70     # 2023-2026
    assert all(rec["season"] >= 2023 for rec in r["per_race"])
    # o veredito gravado tem que ser REPRODUTÍVEL a partir das métricas
    assert r["verdicts"]["H1-F1"]["verdict"] == verdict_h1(r)["verdict"]
    # o modelo carrega informação (nulo de permutação), bata ou não o grid
    assert r["nullref"]["observed"] < r["nullref"]["null_p5"]
    # trilha das trials: notas de RESULTADO preenchidas
    trials = {t["name"]: t for t in
              json.loads(TRIALS.read_text(encoding="utf-8"))}
    assert "RESULTADO" in trials["H1-F1-elo-pl-vs-grid-rps"]["notes"]
    assert (r["verdicts"]["H1-F1"]["verdict"]
            in trials["H1-F1-elo-pl-vs-grid-rps"]["notes"])


@pytest.mark.skipif(not RATINGS.exists(),
                    reason="ratings.json é runtime (gerado pelo backtest)")
def test_ratings_vividos_sao_do_grid_2026():
    ratings = json.loads(RATINGS.read_text(encoding="utf-8"))
    grid = {d["name"] for d in load_drivers()}
    assert set(ratings) <= grid
    assert len(ratings) == 22                      # todos correram em 2026
    assert all(1000 < v < 2000 for v in ratings.values())
