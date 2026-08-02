"""Validação viva — Passos 1-3 do docs/PROMPT_VALIDACAO_2026.md.

Retrodiz TODAS as corridas de 2026 já disputadas (sem lookahead: o Elo
usado em cada previsão é o estado ANTES daquela corrida) comparando
Elo puro, grid (H0) e o blend Elo+grid (w=0.5, comprovado na Fase 2);
prevê a próxima corrida do calendário; roda testes de estresse
adicionais (determinismo, H2H de companheiros, erros esperados, gate).

NÃO é um backtest de pesquisa nova — não grava trials.json. É
acompanhamento operacional do que as Fases 1/2/4 já comprovaram.

Uso:
    python scripts/validate_2026.py
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


from src.backtest import (BacktestElo, _grid_elos, _race_seed,   # noqa: E402
                          blend_elos, position_probs)
from src.config import ROOT, load_circuits, load_drivers         # noqa: E402
from src.context_factors import match_circuit_metadata            # noqa: E402
from src.data.db import load_races_with_results                  # noqa: E402
from src.data.f1_provider import F1Provider                      # noqa: E402
from src.model import F1EloModel, _load_fase2_params              # noqa: E402
from src import operate                                          # noqa: E402
from src import predict                                          # noqa: E402

from predictor_core.measurement.metrics import rps                # noqa: E402

N_SIMS = 10000
SIM_SEED = 13


class ValidationFailed(RuntimeError):
    """An operational sanity invariant failed; callers must not ignore it."""


def _ordem_prevista(names: list, elos: list) -> list:
    """Ordem de chegada prevista: pilotos ordenados por força decrescente
    (estimativa pontual — não precisa de simulação, é o mesmo critério que
    já decide o vencedor previsto em expectativa)."""
    idx = sorted(range(len(names)), key=lambda i: -elos[i])
    return [names[i] for i in idx]


def _erro_medio_posicao(ordem_prevista: list, ordem_real: list) -> float:
    """Erro médio |posição prevista - posição real| por piloto, comparando
    as DUAS ordens completas (não só o vencedor) — mede o quanto a previsão
    inteira erra o grid de chegada, não só quem ficou em 1º."""
    prev_rank = {nm: i for i, nm in enumerate(ordem_prevista)}
    real_rank = {nm: i for i, nm in enumerate(ordem_real)}
    erros = [abs(prev_rank[nm] - real_rank[nm]) for nm in ordem_real]
    return sum(erros) / len(erros)


def retrodicao_2026(races: list, *, fase2_params: dict) -> list:
    """Elo contínuo 2022→hoje; para cada corrida de 2026 JÁ disputada,
    previsão ANTES do update (sem lookahead), três candidatos: Elo puro,
    grid (H0), blend Elo+grid."""
    elo = BacktestElo()
    linhas = []
    for race in races:
        results = race["results"]
        n = len(results)
        if n < 2:
            continue
        names = [r["driver"] for r in results]
        actual_pos = [r["position"] - 1 for r in results]
        ordem_real = [nm for nm, _ in sorted(zip(names, actual_pos), key=lambda t: t[1])]

        if race["season"] == 2026:
            elos_model = [elo.rating(nm) for nm in names]
            elos_grid = _grid_elos(results, n).tolist()
            elos_blend = blend_elos(__import__("numpy").array(elos_model),
                                    __import__("numpy").array(elos_grid),
                                    float(fase2_params["w_grid"])).tolist()
            row = {"round": race["round"], "name": race["name"],
                  "circuit": race["circuit"], "date": race["date"],
                  "n_drivers": n, "ordem_real": ordem_real}
            for tag, elos in (("model", elos_model), ("grid", elos_grid),
                             ("blend", elos_blend)):
                import numpy as np
                p = position_probs(np.array(elos), N_SIMS,
                                   _race_seed(SIM_SEED, race["season"],
                                             race["round"], 70))
                row[f"rps_{tag}"] = rps([r.tolist() for r in p], actual_pos)
                pred_winner_idx = int(p[:, 0].argmax())
                row[f"vencedor_previsto_{tag}"] = names[pred_winner_idx]
                top3_idx = set(p[:, :3].sum(axis=1).argsort()[::-1][:3].tolist())
                real_top3_idx = {i for i, pos in enumerate(actual_pos) if pos < 3}
                row[f"podio_acertos_{tag}"] = len(top3_idx & real_top3_idx)
                ordem_prevista = _ordem_prevista(names, elos)
                row[f"ordem_prevista_{tag}"] = ordem_prevista
                row[f"erro_medio_posicao_{tag}"] = round(
                    _erro_medio_posicao(ordem_prevista, ordem_real), 3)
            row["vencedor_real"] = names[actual_pos.index(0)]
            linhas.append(row)

        finish_order = [r["driver"] for r in results if not r["dnf"]]
        elo.update(finish_order)
    return linhas


def proxima_corrida(schedule: list, now: datetime | None = None) -> dict | None:
    """Primeira corrida cuja largada ainda não ocorreu.

    Caches legados sem horário mantêm o comportamento conservador por data;
    calendários atuais usam o instante UTC oficial e não chamam uma corrida
    já iniciada de futura.
    """
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now deve conter timezone")
    instant = instant.astimezone(timezone.utc)
    futuras = []
    for race in schedule:
        scheduled = race.get("scheduled_start_utc")
        if scheduled:
            start = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
            if start.tzinfo is None or start.utcoffset() is None:
                raise ValueError("scheduled_start_utc deve conter timezone")
            if start.astimezone(timezone.utc) > instant:
                futuras.append(race)
        elif race["date"] >= instant.date().isoformat():
            futuras.append(race)
    return futuras[0] if futuras else None


def testes_estresse() -> dict:
    out = {}
    # determinismo
    # Call the pure model directly: validation must not append serving logs.
    r1 = F1EloModel().predict_race("Monza")
    r2 = F1EloModel().predict_race("Monza")
    out["determinismo_ok"] = (r1["ranking"] == r2["ranking"])

    # H2H is explicitly human-closed. Do not bypass its gate just to make a
    # diagnostic report; record that this check was intentionally skipped.
    drivers = load_drivers()
    by_team = defaultdict(list)
    for d in drivers:
        by_team[d["team"]].append(d["name"])
    h2h = []
    for team, names in by_team.items():
        if len(names) == 2:
            h2h.append({"team": team, "a": names[0], "b": names[1],
                        "status": "SKIPPED_CLOSED_BY_HUMAN_DECISION"})
    out["h2h_companheiros"] = h2h

    # erros esperados
    out["erro_circuito_invalido_exit"] = predict.main(
        ["--circuit", "CircuitoQueNaoExiste", "--json"])
    out["erro_piloto_invalido_exit"] = predict.main(
        ["--head-to-head", "PilotoFantasma", "Hamilton", "--circuit", "Monza"])

    # gate de operação
    out["gate"] = operate_status()
    out["invariants_ok"] = (
        out["determinismo_ok"]
        and out["erro_circuito_invalido_exit"] == 2
        and out["erro_piloto_invalido_exit"] == 2
        and out["gate"]["decision"] == "NO-GO"
    )
    return out


def operate_status() -> dict:
    from src.betting import go_gate
    return go_gate()


def main() -> int:
    print("[1/3] retrodição de 2026 (sem lookahead)...")
    fase2_params = _load_fase2_params(ROOT / "data" / "fase2_params.json")
    if not fase2_params["usar_blend"]:
        raise ValidationFailed("Fase 2 sem blend comprovado; validação viva não representa o serving")
    races = load_races_with_results()
    linhas = retrodicao_2026(races, fase2_params=fase2_params)
    if not linhas:
        print("      nenhuma corrida de 2026 com resultado ainda.")
    else:
        print(f"      {'corrida':<24}{'RPS elo':>9}{'RPS grid':>10}{'RPS blend':>11}"
             f"{'erro pos.':>11}  vencedor real / previsto (blend)")
        for row in linhas:
            print(f"      {row['name'][:22]:<24}{row['rps_model']:>9.4f}"
                  f"{row['rps_grid']:>10.4f}{row['rps_blend']:>11.4f}"
                  f"{row['erro_medio_posicao_blend']:>11.2f}  "
                  f"{row['vencedor_real']} / {row['vencedor_previsto_blend']}")
        n = len(linhas)
        acertos_blend = sum(1 for r in linhas
                           if r["vencedor_previsto_blend"] == r["vencedor_real"])
        print(f"      acerto de vencedor (blend): {acertos_blend}/{n}")
        print(f"      RPS medio 2026: elo={sum(r['rps_model'] for r in linhas)/n:.4f} "
              f"grid={sum(r['rps_grid'] for r in linhas)/n:.4f} "
              f"blend={sum(r['rps_blend'] for r in linhas)/n:.4f}")
        print(f"      erro medio de posicao (blend, 22 pilotos): "
              f"{sum(r['erro_medio_posicao_blend'] for r in linhas)/n:.2f}")

        ultima = linhas[-1]
        print(f"\n      Ordem completa prevista x real — {ultima['name']} "
             f"(corrida mais recente, erro medio {ultima['erro_medio_posicao_blend']:.2f}):")
        print(f"      {'pos':>4}  {'real':<24}{'previsto (blend)':<24}")
        for i, (real_nm, prev_nm) in enumerate(
                zip(ultima["ordem_real"], ultima["ordem_prevista_blend"]), start=1):
            print(f"      {i:>4}  {real_nm:<24}{prev_nm:<24}")

    print("[2/3] próxima corrida do calendário...")
    provider = F1Provider()
    schedule = provider.fetch_schedule(2026)
    prox = proxima_corrida(schedule)
    prox_pred = None
    if prox is None:
        print("      temporada 2026 sem corridas futuras no calendário.")
    else:
        print(f"      Rodada {prox['round']}: {prox['name']} ({prox['circuit']}, {prox['date']})")
        meta = match_circuit_metadata(prox["circuit"], load_circuits())
        circuito_curto = meta["name"] if meta else prox["circuit"]

        quali = provider.fetch_qualifying(2026, prox["round"])
        if quali:
            grid = {q["driver"]: q["position"] for q in quali}
            model = F1EloModel()
            r = model.predict_race_with_grid(circuito_curto, grid)
            modo = f"PÓS-QUALI (blend Elo+grid, w={r['w_grid']})"
        else:
            r = predict.run_race(circuito_curto)
            modo = "PRÉ-QUALI (Elo puro vivido — quali ainda não saiu)"
        ordem = list(r["ranking"])
        print(f"      Top-5 previsto [{modo}]:")
        for nm in ordem[:5]:
            v = r["ranking"][nm]
            print(f"        {nm:<24}{v['win']:>7.1%} win  {v['podium']:>7.1%} podio")
        prox_pred = {"round": prox["round"], "name": prox["name"],
                    "circuit": prox["circuit"], "date": prox["date"],
                    "modo": modo,
                    "top5": {nm: r["ranking"][nm] for nm in ordem[:5]}}

    print("[3/3] testes de estresse...")
    estresse = testes_estresse()
    print(f"      determinismo: {'OK' if estresse['determinismo_ok'] else 'FALHOU'}")
    print(f"      H2H companheiros ({len(estresse['h2h_companheiros'])} pares):")
    for h in estresse["h2h_companheiros"]:
        print(f"        {h['a']} vs {h['b']} ({h['team']}): {h['status']}")
    print(f"      erro circuito invalido -> exit {estresse['erro_circuito_invalido_exit']} "
         f"(esperado 2)")
    print(f"      erro piloto invalido -> exit {estresse['erro_piloto_invalido_exit']} "
         f"(esperado 2)")
    print(f"      gate de operacao: {estresse['gate']['decision']} — {estresse['gate']['reason']}")

    if not estresse["invariants_ok"]:
        raise ValidationFailed("sanity check falhou; relatório não foi publicado")

    out = ROOT / "data" / "validacao_2026_ultima.json"
    out.write_text(json.dumps({
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fase2_parameters": fase2_params,
        "retrodicao_2026": linhas, "proxima_corrida": prox_pred,
        "estresse": estresse,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nRelatorio salvo em {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationFailed as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(3)
