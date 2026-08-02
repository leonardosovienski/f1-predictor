"""Fase 1 — fluxo de governança completo, NA ORDEM que a plataforma exige:

  1. Controle positivo (harness do core): o pipeline ordinal detecta edge
     sintético E rejeita ruído → atestado em data/trials.harness_attestation.json.
  2. PRÉ-REGISTRO das hipóteses em data/trials.json (versionado) — antes de
     olhar qualquer resultado real.
  3. Backtest prequential 2022-2026 (burn-in 2022) sobre data/f1.db.
  4. Resultados gravados nas trials + data/backtest_fase1.json +
     data/ratings.json (Elo vivido, só grid 2026 — contrato do serving).

Uso:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --n-sims 20000 --null-samples 1000
"""
import argparse
import json
import sys
from pathlib import Path


from src.config import ROOT, load_drivers                     # noqa: E402
from src.backtest import (evaluate_ordinal_pipeline,          # noqa: E402
                          run_backtest, synthetic_races,
                          verdict_h1, verdict_h2)
from src.data.db import load_races_with_results               # noqa: E402

from predictor_core.measurement.trials import (               # noqa: E402
    TrialRegistry, attestation_path_for)
from predictor_core.testing.harness import attest_pipeline_power  # noqa: E402

TRIALS = ROOT / "data" / "trials.json"

# Identidade EXATA das tentativas (mudar params = tentativa N+1)
H1_PARAMS = {
    "hipotese": "Elo/Plackett-Luce prequential tem RPS menor que o baseline "
                "de GRID DE LARGADA com DM p<0.05, e abaixo do percentil 5 "
                "do nulo de permutação",
    "modelo": "elo-plackett-luce", "semente_elo": 1400,
    "burn_in": 2022, "avaliacao": "2023-2026",
    "k_base": 24, "k_rookie": 40, "rookie_races": 22,
    "dnf": "classificação oficial (última posição do grupo); "
           "sensibilidade exclui DNF",
    "baseline": "grid de largada via escada 1750-1350 + Plackett-Luce",
    "nulo": "permutação da atribuição previsão-piloto, por corrida",
    "alpha": 0.05,
}
H2_PARAMS = {
    "hipotese": "H2H entre companheiros de equipe: acerto > 50% com IC "
                "Wilson 95% inteiro acima de 0.5",
    "modelo": "elo-h2h-fechado", "semente_elo": 1400,
    "burn_in": 2022, "avaliacao": "2023-2026",
    "selecao": "pares de mesma equipe com ambos classificados",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sims", type=int, default=10000)
    ap.add_argument("--null-samples", type=int, default=1000)
    args = ap.parse_args()

    print("[1/4] controle positivo (harness do core)...")
    att = attest_pipeline_power(
        evaluate_ordinal_pipeline,
        lambda: synthetic_races(informative=True),
        lambda: synthetic_races(informative=False),
        attestation_path=attestation_path_for(TRIALS),
        # `metric` virou obrigatória no predictor_core 2.0.0 e vai gravada no
        # atestado: toda trial nova registrada contra ele tem que declarar a
        # MESMA régua, senão o registry levanta MetricMismatchError. "rps" é o
        # que este domínio de fato mede — todos os vereditos desta fase são
        # comparações de RPS (ver src/backtest.py::verdict_*) — e é a string já
        # usada no ecossistema (H4 do brasileirao).
        metric="rps",
        note="critério ordinal H1 (DM vs grid + nulo de permutação): "
             "detecta forças sintéticas separadas, rejeita permutações "
             "uniformes", edge_verdict="COMPROVADA")
    print(f"      atestado emitido ({att['passed_at']})")

    print("[2/4] pré-registro das hipóteses em data/trials.json...")
    reg = TrialRegistry(TRIALS)
    reg.register("H1-F1-elo-pl-vs-grid-rps", params=H1_PARAMS,
                 notes="pré-registrada antes do backtest real",
                 test_period=["2023-01-01", "2026-07-12"])
    reg.register("H2-F1-h2h-companheiros", params=H2_PARAMS,
                 notes="pré-registrada antes do backtest real",
                 test_period=["2023-01-01", "2026-07-12"])
    assert reg.validate() == [], "trials.json fora do schema"
    print(f"      {len(reg.load())} tentativa(s) registradas")

    print("[3/4] backtest prequential 2022-2026 (burn-in 2022)...")
    races = load_races_with_results()
    result = run_backtest(races, n_sims=args.n_sims,
                          null_samples=args.null_samples)
    v1, v2 = verdict_h1(result), verdict_h2(result)
    agg, nr = result["aggregate"], result["nullref"]
    print(f"      {result['n_eval']} corridas avaliadas")
    print(f"      RPS  modelo {agg['rps_model']:.4f} | grid {agg['rps_grid']:.4f} "
          f"| standings {agg['rps_standings']:.4f} | uniforme {agg['rps_uniform']:.4f}")
    dm = result["dm"]["model_vs_grid"]
    print(f"      DM vs grid: {dm['dm']:.3f} (p={dm['p']:.4f}) | "
          f"nulo: obs {nr['observed']:.4f} vs p5 {nr['null_p5']:.4f} "
          f"(tail_p={nr['tail_p']:.4f})")
    h = result["h2h_teammates"]
    print(f"      H2H companheiros: {h['hits']}/{h['n']} = {h['acc']:.1%} "
          f"IC95 [{h['wilson95'][0]:.3f}, {h['wilson95'][1]:.3f}]")
    print(f"      H1-F1: {v1['verdict']} | H2-F1: {v2['verdict']}")

    print("[4/4] gravando resultados...")
    reg.register("H1-F1-elo-pl-vs-grid-rps", params=H1_PARAMS,
                 notes=f"RESULTADO: {v1['verdict']} — RPS modelo "
                       f"{agg['rps_model']:.4f} vs grid {agg['rps_grid']:.4f} "
                       f"(DM {dm['dm']:.3f}, p={dm['p']:.4f}); nulo tail_p="
                       f"{nr['tail_p']:.4f} ({result['n_eval']} corridas)",
                 test_period=["2023-01-01", "2026-07-12"])
    reg.register("H2-F1-h2h-companheiros", params=H2_PARAMS,
                 notes=f"RESULTADO: {v2['verdict']} — acerto {h['acc']:.4f} "
                       f"({h['hits']}/{h['n']}), Wilson95 "
                       f"[{h['wilson95'][0]:.4f}, {h['wilson95'][1]:.4f}]",
                 test_period=["2023-01-01", "2026-07-12"])

    out = ROOT / "data" / "backtest_fase1.json"
    slim = {k: v for k, v in result.items() if k != "per_race"}
    slim["per_race"] = result["per_race"]
    slim["verdicts"] = {"H1-F1": v1, "H2-F1": v2}
    out.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    # Elo vivido → serving: SÓ o grid 2026 (histórico completo fica no json
    # do backtest); piloto do grid sem histórico mantém a semente da Fase 0
    grid = {d["name"] for d in load_drivers()}
    vividos = {k: v for k, v in result["final_ratings"].items() if k in grid}
    faltando = sorted(grid - set(vividos))
    (ROOT / "data" / "ratings.json").write_text(
        json.dumps(vividos, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"      backtest_fase1.json + ratings.json ({len(vividos)}/22 "
          f"pilotos do grid com Elo vivido"
          + (f"; sem histórico: {faltando}" if faltando else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
