"""Fase 4 — grid como H0 formal (PrequentialEvaluator+bootstrap), rating
por CONTEXTO de circuito (RatingBook do core), Reliability e Pit
Efficiency (Four Factors com dado real). Mesmo fluxo de governança:
harness → pré-registro → backtest (dev 2023, avaliação CEGA 2024-2026) →
resultados.

Uso:
    python scripts/run_fase4.py
"""
import json
import sys
from pathlib import Path


from src.config import ROOT, load_circuits                     # noqa: E402
from src.backtest import (evaluate_context_pipeline,            # noqa: E402
                          evaluate_grid_feature_pipeline,
                          evaluate_pit_pipeline,
                          evaluate_reliability_pipeline, run_fase4,
                          run_h0_formal, synthetic_races,
                          synthetic_races_context, synthetic_races_h3,
                          synthetic_races_pitstops,
                          synthetic_races_reliability, verdict_h0_formal,
                          verdict_h5, verdict_h6, verdict_h7)
from src.data.db import load_pitstops_by_race, load_races_with_results  # noqa: E402

from predictor_core.measurement.trials import (                 # noqa: E402
    TrialRegistry, attestation_path_for)
from predictor_core.testing.harness import attest_pipeline_power  # noqa: E402

TRIALS = ROOT / "data" / "trials.json"

H0_PARAMS = {
    "hipotese": "Grid de largada (H0) bate o Elo puro no RPS — mesma "
                "pergunta de H1-F1, respondida por caminho INDEPENDENTE "
                "(PrequentialEvaluator do core + bootstrap pareado)",
    "avaliador": "GridBaselineEvaluator vs EloPlackettLuceEvaluator",
    "burn_in": 2022, "avaliacao": "2023-2026", "criterio": "bootstrap IC95 + DM",
}
H5_PARAMS = {
    "hipotese": "Bônus de contexto de circuito (RatingBook do core por "
                "tipo power/downforce/balanced) bate o blend Elo+grid "
                "puro no RPS, avaliação cega 2024-2026",
    "modelo": "elo-grid-blend + contexto (RatingBook)", "dev": 2023,
    "avaliacao": "2024-2026", "w_grid_fixo": 0.5,
}
H6_PARAMS = {
    "hipotese": "Penalidade de Reliability (taxa de DNF rolling, janela "
                "12) bate o blend anterior (Elo+grid+contexto) no RPS, "
                "avaliação cega 2024-2026",
    "dev": 2023, "avaliacao": "2024-2026",
}
H7_PARAMS = {
    "hipotese": "Penalidade de Pit Efficiency (duração rolling por "
                "equipe, z-score histórico) bate o blend anterior "
                "(Elo+grid+contexto+reliability) no RPS, avaliação cega "
                "2024-2026",
    "dev": 2023, "avaliacao": "2024-2026",
}

PERIOD = ["2023-01-01", "2026-07-12"]


def main() -> int:
    print("[1/5] controle positivo (harness do core, H0/H5/H6/H7)...")
    att = attest_pipeline_power(
        evaluate_grid_feature_pipeline,   # reaproveita o atestado da Fase 2
        lambda: synthetic_races_h3(informative=True),
        lambda: synthetic_races_h3(informative=False),
        attestation_path=attestation_path_for(TRIALS),
        # `metric` virou obrigatória no predictor_core 2.0.0 e vai gravada no
        # atestado: toda trial nova registrada contra ele tem que declarar a
        # MESMA régua, senão o registry levanta MetricMismatchError. "rps" é o
        # que este domínio de fato mede — todos os vereditos desta fase são
        # comparações de RPS (ver src/backtest.py::verdict_*) — e é a string já
        # usada no ecossistema (H4 do brasileirao).
        metric="rps",
        note="Fase 4: H0-formal, H5 (contexto), H6 (reliability) e H7 "
             "(pit) validados individualmente em harness próprio antes "
             "deste atestado consolidado",
        edge_verdict="COMPROVADA")
    # cada hipótese nova tem seu PRÓPRIO controle positivo (sensibilidade
    # + especificidade) — já rodado/testado na suíte; aqui só confirmamos
    # de novo, ao vivo, antes de gravar as trials.
    h0_edge = verdict_h0_formal(run_h0_formal(synthetic_races_h3(informative=True), n_sims=1000))
    h0_noise = verdict_h0_formal(run_h0_formal(
        synthetic_races(informative=True, grid_random=True, form_scale=60.0), n_sims=1000))
    h5_edge = evaluate_context_pipeline(synthetic_races_context(informative=True))
    h5_noise = evaluate_context_pipeline(synthetic_races_context(informative=False))
    h6_edge = evaluate_reliability_pipeline(synthetic_races_reliability(informative=True))
    h6_noise = evaluate_reliability_pipeline(synthetic_races_reliability(informative=False))
    h7_edge = evaluate_pit_pipeline(synthetic_races_pitstops(informative=True))
    h7_noise = evaluate_pit_pipeline(synthetic_races_pitstops(informative=False))
    for tag, edge, noise in (("H0", h0_edge, h0_noise), ("H5", h5_edge, h5_noise),
                             ("H6", h6_edge, h6_noise), ("H7", h7_edge, h7_noise)):
        assert edge["verdict"] == "COMPROVADA", f"{tag}: harness falhou sensibilidade"
        assert noise["verdict"] == "REFUTADA", f"{tag}: harness falhou especificidade"
    print(f"      atestado consolidado emitido ({att['passed_at']}); "
          "H0/H5/H6/H7 passaram sensibilidade+especificidade individualmente")

    print("[2/5] pré-registro H0/H5/H6/H7 em data/trials.json...")
    reg = TrialRegistry(TRIALS)
    for name, params in (("H0-F1-formal-grid-vs-elo", H0_PARAMS),
                        ("H5-F1c-contexto-circuito", H5_PARAMS),
                        ("H6-F1c-reliability-dnf", H6_PARAMS),
                        ("H7-F1c-pit-efficiency", H7_PARAMS)):
        reg.register(name, params=params,
                    notes="pré-registrada antes do backtest real (Fase 4)",
                    test_period=PERIOD)
    assert reg.validate() == [], "trials.json fora do schema"
    print(f"      {len(reg.load())} tentativa(s) no registro")

    print("[3/5] H0 formal (PrequentialEvaluator + bootstrap) no histórico real...")
    races = load_races_with_results()
    h0 = run_h0_formal(races, n_sims=8000)
    v0 = verdict_h0_formal(h0)
    print(f"      RPS grid {h0['rps_grid_h0']:.4f} vs Elo {h0['rps_elo']:.4f} | "
          f"bootstrap IC95 {[round(x,4) for x in h0['bootstrap_ci95']]} | "
          f"DM p={h0['dm']['p']:.5f} | veredito: {v0['verdict']}")

    print("[4/5] backtest Fase 4 — contexto+reliability+pit (dev 2023, avaliação cega 2024-2026)...")
    pitstops = load_pitstops_by_race()
    catalog = load_circuits()
    r4 = run_fase4(races, pitstops, catalog, w_grid=0.5, n_sims=10000, null_samples=1000)
    v5, v6, v7 = verdict_h5(r4), verdict_h6(r4), verdict_h7(r4)
    w = r4["weights"]
    print(f"      pesos: w_ctx={w['w_ctx']} w_rel={w['w_rel']} w_pit={w['w_pit']}")
    print(f"      RPS: elo_grid {r4['aggregate']['elo_grid']:.4f} -> "
          f"+ctx {r4['aggregate']['plus_ctx']:.4f} -> "
          f"+rel {r4['aggregate']['plus_ctx_rel']:.4f} -> "
          f"+pit {r4['aggregate']['full']:.4f}")
    print(f"      H5-F1c: {v5['verdict']} (p={v5['dm']['p']:.4f}) | "
          f"H6-F1c: {v6['verdict']} (p={v6['dm']['p']:.4f}) | "
          f"H7-F1c: {v7['verdict']} (p={v7['dm']['p']:.4f})")

    print("[5/5] gravando resultados...")
    reg.register("H0-F1-formal-grid-vs-elo", params=H0_PARAMS,
                notes=f"RESULTADO: {v0['verdict']} — RPS grid "
                      f"{h0['rps_grid_h0']:.4f} vs elo {h0['rps_elo']:.4f}; "
                      f"bootstrap IC95 {[round(x,4) for x in h0['bootstrap_ci95']]}; "
                      f"DM p={h0['dm']['p']:.5f} ({h0['n_eval']} corridas) — "
                      "consistente com H1-F1 REFUTADA da Fase 1",
                test_period=PERIOD)
    reg.register("H5-F1c-contexto-circuito", params=H5_PARAMS,
                notes=f"RESULTADO: {v5['verdict']} — w_ctx={w['w_ctx']}, RPS "
                      f"{r4['aggregate']['plus_ctx']:.4f} vs "
                      f"{r4['aggregate']['elo_grid']:.4f} (p={v5['dm']['p']:.4f})",
                test_period=PERIOD)
    reg.register("H6-F1c-reliability-dnf", params=H6_PARAMS,
                notes=f"RESULTADO: {v6['verdict']} — w_rel={w['w_rel']}, RPS "
                      f"{r4['aggregate']['plus_ctx_rel']:.4f} vs "
                      f"{r4['aggregate']['plus_ctx']:.4f} (p={v6['dm']['p']:.4f})",
                test_period=PERIOD)
    reg.register("H7-F1c-pit-efficiency", params=H7_PARAMS,
                notes=f"RESULTADO: {v7['verdict']} — w_pit={w['w_pit']}, RPS "
                      f"{r4['aggregate']['full']:.4f} vs "
                      f"{r4['aggregate']['plus_ctx_rel']:.4f} (p={v7['dm']['p']:.4f})",
                test_period=PERIOD)

    out = ROOT / "data" / "backtest_fase4.json"
    slim = {k: v for k, v in r4.items()}
    slim["h0_formal"] = {k: v for k, v in h0.items()}
    slim["verdicts"] = {"H0-F1-formal": v0, "H5-F1c": v5, "H6-F1c": v6, "H7-F1c": v7}
    out.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    # Só grava parâmetros vividos para o serving se a hipótese correspondente
    # foi comprovada — nenhuma feature sem comprovação entra em produção
    (ROOT / "data" / "fase4_params.json").write_text(json.dumps({
        "w_ctx": w["w_ctx"] if v5["verdict"] == "COMPROVADA" else 0.0,
        "w_rel": w["w_rel"] if v6["verdict"] == "COMPROVADA" else 0.0,
        "w_pit": w["w_pit"] if v7["verdict"] == "COMPROVADA" else 0.0,
        "usar_contexto": v5["verdict"] == "COMPROVADA",
        "usar_reliability": v6["verdict"] == "COMPROVADA",
        "usar_pit": v7["verdict"] == "COMPROVADA",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("      backtest_fase4.json + fase4_params.json gravados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
