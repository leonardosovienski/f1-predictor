"""Fase 2 — grid como FEATURE do modelo (blend Elo+grid) e calibração de
Platt no P(pódio). Mesmo fluxo de governança da Fase 1, tentativas NOVAS
(N+1): harness → pré-registro → backtest (dev 2023, avaliação 2024-2026
CEGA) → resultados gravados.

Uso:
    python scripts/run_fase2.py
"""
import json
import sys
from pathlib import Path


from src.config import ROOT                                    # noqa: E402
from src.backtest import (evaluate_grid_feature_pipeline,      # noqa: E402
                          run_fase2, synthetic_races_h3,
                          verdict_h3, verdict_h4)
from src.data.db import load_races_with_results                # noqa: E402

from predictor_core.measurement.trials import (                # noqa: E402
    TrialRegistry, attestation_path_for)
from predictor_core.testing.harness import attest_pipeline_power  # noqa: E402

TRIALS = ROOT / "data" / "trials.json"

H3_PARAMS = {
    "hipotese": "Elo+grid (peso escolhido SO no periodo de desenvolvimento "
                "2023) tem RPS menor que o Elo PURO no periodo de "
                "avaliacao CEGO 2024-2026, DM p<0.05",
    "modelo": "elo-grid-blend", "semente_elo": 1400,
    "burn_in": 2022, "dev": 2023, "avaliacao": "2024-2026",
    "w_candidates": "0.0 a 1.0 passo 0.1, RPS minimo no dev",
    "k_base": 24, "k_rookie": 40, "alpha": 0.05,
}
H4_PARAMS = {
    "hipotese": "Calibracao de Platt no P(podio) do blend (ajustada no "
                "dev 2023) reduz o Brier binario no periodo de avaliacao "
                "CEGO 2024-2026 frente ao valor cru",
    "modelo": "platt-podium-blend", "burn_in": 2022, "dev": 2023,
    "avaliacao": "2024-2026",
}


def main() -> int:
    print("[1/4] controle positivo (harness do core, H3)...")
    att = attest_pipeline_power(
        evaluate_grid_feature_pipeline,
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
        note="H3-F1b (grid como feature): choque de forma do dia "
             "compartilhado quali/largada -> grid informativo detectado; "
             "grid embaralhado (mesma forma) -> nao confirmado",
        edge_verdict="COMPROVADA")
    print(f"      atestado emitido ({att['passed_at']})")

    print("[2/4] pré-registro H3-F1b e H4-F1b em data/trials.json...")
    reg = TrialRegistry(TRIALS)
    reg.register("H3-F1b-elo-grid-blend-vs-elo-puro", params=H3_PARAMS,
                 notes="pré-registrada antes do backtest real (N+1 da Fase 1)",
                 test_period=["2024-01-01", "2026-07-12"])
    reg.register("H4-F1b-platt-podium", params=H4_PARAMS,
                 notes="pré-registrada antes do backtest real (N+1 da Fase 1)",
                 test_period=["2024-01-01", "2026-07-12"])
    assert reg.validate() == [], "trials.json fora do schema"
    print(f"      {len(reg.load())} tentativa(s) no registro")

    print("[3/4] backtest Fase 2 — dev 2023, avaliação CEGA 2024-2026...")
    races = load_races_with_results()
    result = run_fase2(races, n_sims=10000, null_samples=1000)
    v3, v4 = verdict_h3(result), verdict_h4(result)
    agg = result["aggregate"]
    print(f"      w_grid escolhido no dev: {result['w_grid']} "
          f"(RPS dev {result['w_dev_rps']:.4f})")
    print(f"      {result['n_eval']} corridas avaliadas (2024-2026)")
    print(f"      RPS  blend {agg['rps_blend']:.4f} | elo puro "
          f"{agg['rps_elo_puro']:.4f} | grid {agg['rps_grid']:.4f} | "
          f"standings {agg['rps_standings']:.4f}")
    dm = result["dm"]["blend_vs_elo_puro"]
    print(f"      DM blend vs elo puro: {dm['dm']:.3f} (p={dm['p']:.4f})")
    pod = result["podium"]
    print(f"      Brier pódio: cru {pod['brier_raw']:.4f} vs calibrado "
          f"{pod['brier_calibrated']:.4f} (Platt a={result['platt']['a']:.3f} "
          f"b={result['platt']['b']:.3f})")
    print(f"      H3-F1b: {v3['verdict']} | H4-F1b: {v4['verdict']}")

    print("[4/4] gravando resultados...")
    reg.register("H3-F1b-elo-grid-blend-vs-elo-puro", params=H3_PARAMS,
                 notes=f"RESULTADO: {v3['verdict']} — w={result['w_grid']}, "
                       f"RPS blend {agg['rps_blend']:.4f} vs elo puro "
                       f"{agg['rps_elo_puro']:.4f} (DM {dm['dm']:.3f}, "
                       f"p={dm['p']:.4f}); {result['n_eval']} corridas",
                 test_period=["2024-01-01", "2026-07-12"])
    reg.register("H4-F1b-platt-podium", params=H4_PARAMS,
                 notes=f"RESULTADO: {v4['verdict']} — Brier cru "
                       f"{pod['brier_raw']:.4f} vs calibrado "
                       f"{pod['brier_calibrated']:.4f}",
                 test_period=["2024-01-01", "2026-07-12"])

    out = ROOT / "data" / "backtest_fase2.json"
    slim = {k: v for k, v in result.items() if k != "final_ratings"}
    slim["verdicts"] = {"H3-F1b": v3, "H4-F1b": v4}
    out.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    # Grava o w e o Platt vividos — o serving pós-quali (Fase 2) usa isto
    (ROOT / "data" / "fase2_params.json").write_text(json.dumps({
        "w_grid": result["w_grid"], "platt_a": result["platt"]["a"],
        "platt_b": result["platt"]["b"],
        "usar_calibracao": v4["verdict"] == "COMPROVADA",
        "usar_blend": v3["verdict"] == "COMPROVADA",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("      backtest_fase2.json + fase2_params.json gravados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
