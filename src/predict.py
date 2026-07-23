"""Serving de previsão de F1 — Fase 0 (Elo puro) e Fase 2 (Elo+grid, pós-quali).

Uso:
    python -m src.predict --circuit Monza --weather dry --json
    python -m src.predict --head-to-head Verstappen Hamilton --circuit Monaco
    python -m src.predict --circuit Monza --market podium
    python -m src.predict --circuit Monza --grid Verstappen:1 Norris:2 ...

Contratos do core desde o dia zero: PredictionPoint (matures_at = largada
estimada + 2h30 de corrida; sem schedule na Fase 0, largada = agora),
emit_event (domínio "f1") e log append-only com override por env. Para o
ranking completo, o value do PredictionPoint é a ORDENAÇÃO — o formato que
o RPS (metrics.py) e o nullref.py do core consomem desde a Fase 1.

`--grid` usa o modelo PÓS-QUALI da Fase 2 (Elo misturado ao grid de
largada — H3-F1b COMPROVADA no backtest) só quando `data/fase2_params.json`
existir com o veredito comprovado; senão cai no Elo puro (nenhuma feature
sem comprovação entra no serving).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, load_config           # injeta vendor/ no sys.path
from .closure import require_open
from .model import F1EloModel

from predictor_core.data.contracts import PredictionPoint
from predictor_core.kernel.obs import emit_event

_DOMAIN = "f1"
RACE_DURATION = timedelta(hours=2, minutes=30)


def _log_path() -> Path:
    return Path(os.environ.get("PREDICTIONS_LOG_PATH",
                               ROOT / "data" / "predictions.jsonl"))


def _stamp_and_log(r: dict, value: dict, metadata: dict,
                   now: datetime | None) -> dict:
    now = now or datetime.now(timezone.utc)
    point = PredictionPoint(predicted_at=now, matures_at=now + RACE_DURATION,
                            value=value, metadata=metadata)
    r["predicted_at"] = point.predicted_at.isoformat(timespec="seconds")
    r["matures_at"] = point.matures_at.isoformat(timespec="seconds")
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        emit_event(_DOMAIN, "prediction", metrics=metadata.pop("_metrics", {}),
                   metadata=metadata)
    except Exception:
        pass    # telemetria nunca derruba o serving
    return r


def run_race(circuit: str, weather: str = "dry",
             now: datetime | None = None) -> dict:
    model = F1EloModel()
    r = model.predict_race(circuit, weather)
    ordem = list(r["ranking"])
    return _stamp_and_log(
        r,
        value={"ranking": ordem,
               "win_probs": {n: r["ranking"][n]["win"] for n in ordem[:5]}},
        metadata={"market": "race", "circuit": r["circuit"],
                  "weather": weather, "model": r["model"],
                  "_metrics": {"p_win_favorito": r["ranking"][ordem[0]]["win"],
                               "n_drivers": r["n_drivers"]}},
        now=now)


def _parse_grid(pairs: list) -> dict:
    """['Verstappen:1', 'Norris:2', ...] → {'Verstappen': 1, 'Norris': 2}."""
    grid = {}
    for item in pairs:
        if ":" not in item:
            raise ValueError(f"formato de --grid inválido: {item!r} "
                             "(use PILOTO:POSICAO)")
        name, pos = item.rsplit(":", 1)
        try:
            grid[name.strip()] = int(pos)
        except ValueError:
            raise ValueError(f"posição de grid não-numérica em {item!r}")
    return grid


def run_race_grid(circuit: str, grid_pairs: list, weather: str = "dry",
                  now: datetime | None = None) -> dict:
    model = F1EloModel()
    r = model.predict_race_with_grid(circuit, _parse_grid(grid_pairs), weather)
    ordem = list(r["ranking"])
    return _stamp_and_log(
        r,
        value={"ranking": ordem,
               "win_probs": {n: r["ranking"][n]["win"] for n in ordem[:5]}},
        metadata={"market": "race_grid", "circuit": r["circuit"],
                  "weather": weather, "model": r["model"],
                  "w_grid": r["w_grid"],
                  "podium_calibrado": r["podium_calibrado"],
                  "_metrics": {"p_win_favorito": r["ranking"][ordem[0]]["win"],
                               "n_drivers": r["n_drivers"]}},
        now=now)


def run_h2h(driver_a: str, driver_b: str, circuit: str,
            now: datetime | None = None) -> dict:
    require_open("H2H")
    model = F1EloModel()
    r = model.predict_head_to_head(driver_a, driver_b, circuit)
    return _stamp_and_log(
        r,
        value={"prob_a_beats_b": r["prob_a_beats_b"]},
        metadata={"market": "h2h", "driver_a": r["driver_a"],
                  "driver_b": r["driver_b"], "circuit": r["circuit"],
                  "model": r["model"],
                  "_metrics": {"prob_a_beats_b": r["prob_a_beats_b"]}},
        now=now)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Previsão de corrida de F1 (Elo ordinal, Fase 0)")
    ap.add_argument("--circuit", required=True,
                    help="circuito (nome oficial ou substring, ex.: Monza)")
    ap.add_argument("--weather", default="dry", choices=["dry", "wet"],
                    help="validado; NÃO ajusta na Fase 0 (declarado)")
    ap.add_argument("--head-to-head", nargs=2, metavar=("PILOTO_A", "PILOTO_B"),
                    dest="h2h", default=None)
    ap.add_argument("--grid", nargs="+", metavar="PILOTO:POSICAO",
                    default=None,
                    help="grid de largada pós-quali (Fase 2, Elo+grid)")
    ap.add_argument("--market", default="winner",
                    choices=["winner", "podium", "top6", "h2h"],
                    help="coluna destacada na exibição do ranking")
    ap.add_argument("--json", action="store_true", help="saída estruturada")
    args = ap.parse_args(argv)

    try:
        if args.h2h:
            r = run_h2h(args.h2h[0], args.h2h[1], args.circuit)
        elif args.grid:
            r = run_race_grid(args.circuit, args.grid, args.weather)
        else:
            r = run_race(args.circuit, args.weather)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    cfg = load_config()
    if args.h2h:
        print(f"{cfg['sport']} {cfg['season']} — {r['circuit']}: "
              f"{r['driver_a']} vs {r['driver_b']}")
        print(f"  {r['driver_a']} à frente: {r['prob_a_beats_b']:.1%} "
              f"(Elo {r['elo_a']:.0f})")
        print(f"  {r['driver_b']} à frente: {r['prob_b_beats_a']:.1%} "
              f"(Elo {r['elo_b']:.0f})")
    else:
        key = {"winner": "win", "podium": "podium", "top6": "top6",
               "h2h": "win"}[args.market]
        print(f"{cfg['sport']} {cfg['season']} — {r['circuit']} "
              f"({r['weather']}, {r['n_sims']} sims; ordenado por {key})")
        print(f"  {'piloto':<24}{'equipe':<18}{'win':>7}{'pódio':>8}{'top6':>7}")
        ordenado = sorted(r["ranking"].items(), key=lambda kv: -kv[1][key])
        for n, v in ordenado[:10]:
            print(f"  {n:<24}{v['team'][:16]:<18}{v['win']:>7.1%}"
                  f"{v['podium']:>8.1%}{v['top6']:>7.1%}")
        if r["model"] == "elo-grid-blend-fase2":
            print(f"  [Fase 2: Elo+grid (w={r['w_grid']}), pódio "
                  f"{'calibrado (Platt)' if r['podium_calibrado'] else 'cru'} "
                  "— H3-F1b comprovada]")
        else:
            print("  [Elo puro — circuito/clima ainda não ajustam "
                  "(use --grid pós-quali para a Fase 2)]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
