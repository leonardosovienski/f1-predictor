"""Fase 5 — H8-F1: choque estrutural de transição de regulamento.

Fluxo pedido explicitamente pelo usuário, com uma adaptação honesta: o
protocolo original pedia calibrar na transição real 2021->2022 e aplicar
cegamente em 2026. Nosso histórico começa em 2022 (burn-in) — não há
Elo acumulado de 2021 pra chocar, então essa transição não existe no
nosso dado. A calibração cega usa um cenário SINTÉTICO (reembaralhamento
de força do campo inteiro numa fronteira de temporada conhecida) em vez
disso; o fator resultante é aplicado às cegas ao histórico real —
2026 nunca influencia a escolha do fator.

Uso:
    python scripts/run_fase5.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ROOT                                     # noqa: E402
from src.backtest import (calibrate_shrink_factor_sintetico,     # noqa: E402
                          evaluate_h8_pipeline, run_h8,
                          synthetic_races_transition, verdict_h8)
from src.data.db import load_races_with_results                 # noqa: E402

from predictor_core.measurement.trials import (                 # noqa: E402
    TrialRegistry, attestation_path_for)
from predictor_core.testing.harness import attest_pipeline_power  # noqa: E402

TRIALS = ROOT / "data" / "trials.json"

H8_PARAMS = {
    "hipotese": "Choque estrutural (encolhimento de TODOS os ratings em "
                "direcao a semente 1400, no 1o round de temporada com "
                "regulamento novo) reduz o RPS de 2026 vs Elo comum, DM p<0.05",
    "mecanismo": "BacktestElo.shrink_to_mean(factor)",
    "transition_seasons": [2022, 2026],
    "calibracao": "CEGA — fator escolhido SO em cenario sintetico "
                  "(reembaralhamento de campo inteiro numa fronteira "
                  "conhecida); 2026 real NUNCA influencia a escolha do fator",
    "baseline_de_sucesso": "grid de largada (H0) — RPS vs grid tambem reportado",
}


def main() -> int:
    print("[1/4] controle positivo (harness do core, H8)...")
    att = attest_pipeline_power(
        evaluate_h8_pipeline,
        lambda: synthetic_races_transition(reshuffle=True),
        lambda: synthetic_races_transition(reshuffle=False),
        attestation_path=attestation_path_for(TRIALS),
        note="H8-F1 (choque estrutural de transicao): reembaralhamento "
             "real de campo -> choque ajuda (edge); forca estavel -> "
             "choque atrapalha ou neutro (noise)",
        edge_verdict="COMPROVADA")
    print(f"      atestado emitido ({att['passed_at']})")

    print("[2/4] calibracao CEGA do fator de encolhimento (so sintetico)...")
    cal = calibrate_shrink_factor_sintetico()
    print(f"      fator escolhido: {cal['factor']} "
         f"(RPS por candidato: {cal['losses_por_candidato']})")

    print("[3/4] pre-registro H8-F1 em data/trials.json...")
    reg = TrialRegistry(TRIALS)
    params = {**H8_PARAMS, "shrink_factor_calibrado": cal["factor"]}
    reg.register("H8-F1-choque-transicao-regulamento", params=params,
                notes="pre-registrada antes do backtest real; fator "
                      "calibrado as cegas em sintetico",
                test_period=["2023-01-01", "2026-07-12"])
    assert reg.validate() == [], "trials.json fora do schema"
    print(f"      {len(reg.load())} tentativa(s) no registro")

    print("[4/4] aplicando o fator (cego) ao historico real 2022-2026...")
    races = load_races_with_results()
    r = run_h8(races, shrink_factor=cal["factor"], n_sims=10000, null_samples=500)
    v8 = verdict_h8(r)
    print("      RPS por temporada (com choque vs sem choque):")
    for s, row in sorted(r["por_temporada"].items()):
        marca = " <- transicao" if s in (2022, 2026) else ""
        print(f"        {s}: com={row['rps_com_choque']:.4f} "
             f"sem={row['rps_sem_choque']:.4f} (n={row['n']}){marca}")
    print(f"      H8-F1 (2026): {v8['verdict']} — DM {r['dm_2026']}")

    reg.register("H8-F1-choque-transicao-regulamento", params=params,
                notes=f"RESULTADO: {v8['verdict']} — fator={cal['factor']}, "
                      f"RPS 2026 com_choque={r['por_temporada'][2026]['rps_com_choque']:.4f} "
                      f"vs sem_choque={r['por_temporada'][2026]['rps_sem_choque']:.4f} "
                      f"(DM {r['dm_2026']['dm']:.3f}, p={r['dm_2026']['p']:.4f})",
                test_period=["2023-01-01", "2026-07-12"])

    out = ROOT / "data" / "backtest_fase5.json"
    out.write_text(json.dumps({**r, "calibracao_sintetica": cal,
                              "verdict": v8}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"      backtest_fase5.json gravado")

    (ROOT / "data" / "fase5_params.json").write_text(json.dumps({
        "shrink_factor": cal["factor"] if v8["verdict"] == "COMPROVADA" else 0.0,
        "usar_choque_transicao": v8["verdict"] == "COMPROVADA",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
