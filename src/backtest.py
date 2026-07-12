"""Backtest prequential ORDINAL — Fase 1. Estreia do RPS e do nullref do core.

Protocolo (pré-registrado em data/trials.json antes da execução real):
- Corrida a corrida em ordem cronológica: PREVER (distribuição de posição
  por piloto via Plackett-Luce/Gumbel com os Elos correntes) e só DEPOIS
  atualizar com a ordem real. Sem lookahead.
- **Semente do backtest: TODOS os pilotos partem de 1400** — a semente do
  campeonato 2025 usada no serving da Fase 0 seria LOOKAHEAD dentro de
  2022-2025. Burn-in: temporada 2022 (fora da avaliação).
- K: novato = piloto com menos de 22 corridas VISTAS na janela (uma
  temporada) → K=40; depois K=24. Mesma matemática pareada do model.py.
- DNF: a classificação oficial já ordena abandonos no fim do grupo (por
  voltas completadas) — "DNF = última posição do grupo" é a leitura
  primária; sensibilidade EXCLUI as observações de DNF.
- Update de Elo: só pilotos classificados (contrato da Fase 0 — DNF não
  pontua nem perde).

Baselines (mesma máquina probabilística, só muda a fonte de informação):
- as ordenações-baseline (grid de largada; standings correntes) viram
  forças pela MESMA escada declarada na Fase 0 (1º → 1750, linear → 1350)
  e passam pelo MESMO Plackett-Luce — comparação justa, zero tuning;
- "aleatório" para o Diebold-Mariano = previsor UNIFORME (sem informação);
- **nullref = teste de PERMUTAÇÃO**: as distribuições de posição do
  PRÓPRIO modelo, com a atribuição previsão→piloto sorteada por corrida.
  Preserva a assertividade do previsor e destrói só a informação — um
  modelo sem informação fica no MEIO da sua nula (não é rejeitável por ser
  não-assertivo), um modelo informado fica na cauda. (Um nulo de
  ordenações one-hot seria batível por qualquer previsor flat — pega no
  controle positivo do harness.)

Métricas: RPS por corrida (média sobre pilotos; `metrics.rps` do core),
Brier/log-loss do VENCEDOR (multiclasse sobre inscritos), Brier binário e
calibração do PÓDIO, Diebold-Mariano (HLN) modelo vs cada baseline, e
percentil do modelo na distribuição nula (`nullref.tail_probability`).
"""
import math
from collections import defaultdict

import numpy as np

from .model import win_probability            # injeta vendor/ no sys.path

from predictor_core.measurement.metrics import (brier, calibration_table,
                                                diebold_mariano, log_loss, rps)
from predictor_core.measurement.nullref import percentile_of, tail_probability

_LN10_400 = math.log(10.0) / 400.0

# Escada declarada na Fase 0 (campeonato → Elo): 1º lugar 1750, linear até
# 1350 no último. Reutilizada para transformar ordenações-baseline em forças.
LADDER_TOP, LADDER_BOTTOM = 1750.0, 1350.0
SEED_ELO = 1400.0
ROOKIE_RACES = 22          # "novato" = menos de uma temporada vista na janela


def ladder(n: int) -> np.ndarray:
    """Elos da escada 1750→1350 para uma ordenação de n itens."""
    if n == 1:
        return np.array([LADDER_TOP])
    return np.linspace(LADDER_TOP, LADDER_BOTTOM, n)


def position_probs(elos: np.ndarray, n_sims: int, seed: int) -> np.ndarray:
    """Matriz (n_pilotos, n_posições) de P(piloto i termina na posição k),
    simulando a ordenação Plackett-Luce via truque de Gumbel (determinístico
    por seed). Mesma matemática do predict_race da Fase 0."""
    n = len(elos)
    skill = elos * _LN10_400
    rng = np.random.default_rng(seed)
    noise = rng.gumbel(size=(n_sims, n))
    order = np.argsort(-(skill[None, :] + noise), axis=1)
    pos = np.empty_like(order)
    rows = np.arange(n_sims)[:, None]
    pos[rows, order] = np.arange(n)[None, :]
    probs = np.zeros((n, n))
    for k in range(n):
        probs[:, k] = (pos == k).mean(axis=0)
    return probs


class BacktestElo:
    """Estado Elo do backtest: semente única 1400, K por corridas vistas.
    Mesma atualização PAREADA do F1EloModel (K/(n-1) por par, média dos K
    do par, soma zero) — a equivalência é testada na suíte."""

    def __init__(self, k_base: float = 24.0, k_rookie: float = 40.0,
                 seed_elo: float = SEED_ELO):
        self.ratings: dict[str, float] = {}
        self.races_seen: dict[str, int] = defaultdict(int)
        self.k_base, self.k_rookie, self.seed_elo = k_base, k_rookie, seed_elo

    def rating(self, name: str) -> float:
        return self.ratings.get(name, self.seed_elo)

    def _k(self, name: str) -> float:
        return (self.k_rookie if self.races_seen[name] < ROOKIE_RACES
                else self.k_base)

    def update(self, finish_order: list[str]) -> None:
        """finish_order: pilotos CLASSIFICADOS, do 1º ao último."""
        n = len(finish_order)
        if n < 2:
            return
        for m in finish_order:
            self.ratings.setdefault(m, self.seed_elo)
        delta = {m: 0.0 for m in finish_order}
        for i in range(n):
            for j in range(i + 1, n):
                a, b = finish_order[i], finish_order[j]
                e_a = win_probability(self.ratings[a], self.ratings[b])
                k = (self._k(a) + self._k(b)) / 2.0 / (n - 1)
                d = k * (1.0 - e_a)              # a chegou à frente de b
                delta[a] += d
                delta[b] -= d
        for m in finish_order:
            self.ratings[m] += delta[m]
            self.races_seen[m] += 1


def _race_seed(base: int, season: int, round_: int, salt: int = 0) -> int:
    return base * 1_000_000 + season * 100 + round_ + salt * 7_919


def _rps_cost_matrix(probs: np.ndarray) -> np.ndarray:
    """c[i, k] = RPS da linha de probabilidade i se a posição real for k.
    Com isso, o RPS de QUALQUER atribuição previsão→piloto é uma média de
    lookups — é o que torna o teste de permutação barato. Equivalência com
    metrics.rps do core verificada na suíte."""
    n, k = probs.shape
    cdf = np.cumsum(probs[:, :-1], axis=1)              # (n, K-1)
    step = (np.arange(k - 1)[None, :, None]
            >= np.arange(k)[None, None, :])             # (1, K-1, K)
    return ((cdf[:, :, None] - step) ** 2).sum(axis=1) / (k - 1)


def run_backtest(races: list[dict], *, n_sims: int = 10000, sim_seed: int = 13,
                 burn_in_season: int = 2022, k_base: float = 24.0,
                 k_rookie: float = 40.0, null_samples: int = 500) -> dict:
    """Passada prequential completa. `races` no formato de
    db.load_races_with_results (ordem cronológica; posição = classificação
    oficial). Retorna métricas agregadas + por corrida + ratings finais."""
    elo = BacktestElo(k_base=k_base, k_rookie=k_rookie)
    season_points: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    per_race: list[dict] = []
    winner_probs: dict[str, list] = {"model": [], "grid": [], "standings": []}
    winner_outcomes: list[int] = []
    podium_pairs: list[tuple[float, int]] = []   # (p_podium prevista, realizado)
    h2h_hits = h2h_total = 0
    null_race_perm_rps: list[list[float]] = []   # por corrida: RPS de cada permutação nula

    for race in races:
        season, round_ = race["season"], race["round"]
        results = race["results"]
        n = len(results)
        if n < 2:
            continue
        names = [r["driver"] for r in results]
        actual_pos = np.array([r["position"] - 1 for r in results])  # 0-based
        dnf_mask = np.array([bool(r["dnf"]) for r in results])
        is_eval = season > burn_in_season

        if is_eval:
            # --- previsões (ANTES do update) ---
            elos_model = np.array([elo.rating(nm) for nm in names])
            # grid: 0 = pit lane → fim da fila (declarado)
            grid_raw = np.array([r["grid"] if r["grid"] > 0 else n + 1
                                 for r in results], dtype=float)
            grid_rank = grid_raw.argsort(kind="stable").argsort()
            elos_grid = ladder(n)[grid_rank]
            # standings: pontos da temporada corrente; rodada 1 usa o ano
            # anterior (novato no grid → 0 pontos → fim da fila, estável)
            table = (season_points[season] if season_points[season]
                     else season_points[season - 1])
            pts = np.array([-table.get(nm, 0.0) for nm in names])
            st_rank = pts.argsort(kind="stable").argsort()
            elos_standings = ladder(n)[st_rank]

            probs = {
                "model": position_probs(elos_model, n_sims,
                                        _race_seed(sim_seed, season, round_, 1)),
                "grid": position_probs(elos_grid, n_sims,
                                       _race_seed(sim_seed, season, round_, 2)),
                "standings": position_probs(elos_standings, n_sims,
                                            _race_seed(sim_seed, season, round_, 3)),
            }
            uniform = np.full((n, n), 1.0 / n)

            rec = {"season": season, "round": round_, "name": race["name"],
                   "n_drivers": n, "n_dnf": int(dnf_mask.sum())}
            outcomes = actual_pos.tolist()
            for key, p in {**probs, "uniform": uniform}.items():
                rec[f"rps_{key}"] = rps([row.tolist() for row in p], outcomes)
            # sensibilidade: só classificados (posições oficiais mantidas)
            fin = ~dnf_mask
            if fin.sum() >= 2:
                rec["rps_model_no_dnf"] = rps(
                    [probs["model"][i].tolist() for i in range(n) if fin[i]],
                    actual_pos[fin].tolist())

            # vencedor (multiclasse sobre inscritos) e pódio (binário)
            win_idx = int(np.argmin(actual_pos))
            winner_outcomes.append(win_idx)
            for key in winner_probs:
                winner_probs[key].append(probs[key][:, 0].tolist())
            for i in range(n):
                p_podium = float(probs["model"][i, :3].sum())
                podium_pairs.append((p_podium, int(actual_pos[i] < 3)))

            # H2H entre companheiros de equipe (só pares 100% classificados)
            teams: dict[str, list[int]] = defaultdict(list)
            for i, r in enumerate(results):
                teams[r["constructor"]].append(i)
            for idx in teams.values():
                if len(idx) == 2 and not dnf_mask[idx].any():
                    a, b = idx
                    ra, rb = elos_model[a], elos_model[b]
                    if ra == rb:
                        continue
                    pred_a = ra > rb
                    real_a = actual_pos[a] < actual_pos[b]
                    h2h_hits += int(pred_a == real_a)
                    h2h_total += 1

            # nulo de permutação: previsões do modelo, atribuição sorteada
            rng = np.random.default_rng(_race_seed(sim_seed, season, round_, 4))
            cost = _rps_cost_matrix(probs["model"])
            drv = np.arange(n)
            null_race_perm_rps.append(
                [float(cost[rng.permutation(n), actual_pos[drv]].mean())
                 for _ in range(null_samples)])
            per_race.append(rec)

        # --- update (DEPOIS de prever): só classificados, ordem real ---
        finish_order = [r["driver"] for r in results if not r["dnf"]]
        elo.update(finish_order)
        for r in results:
            season_points[season][r["driver"]] += r["points"]

    if not per_race:
        raise ValueError("nenhuma corrida no período de avaliação")

    # --- agregação ---
    agg = {}
    for key in ("rps_model", "rps_grid", "rps_standings", "rps_uniform"):
        agg[key] = float(np.mean([r[key] for r in per_race]))
    no_dnf = [r["rps_model_no_dnf"] for r in per_race if "rps_model_no_dnf" in r]
    agg["rps_model_no_dnf"] = float(np.mean(no_dnf)) if no_dnf else None

    dm = {}
    losses_model = [r["rps_model"] for r in per_race]
    for base in ("grid", "standings", "uniform"):
        stat, p = diebold_mariano(losses_model,
                                  [r[f"rps_{base}"] for r in per_race], h=1)
        dm[f"model_vs_{base}"] = {"dm": stat, "p": p,
                                  "modelo_melhor": bool(stat < 0)}

    # nulo: cada amostra m é UMA passada (permutação por corrida), média
    # sobre as corridas → distribuição do RPS médio de seletores aleatórios
    null_matrix = np.array(null_race_perm_rps)          # (corridas, amostras)
    null_dist = sorted(null_matrix.mean(axis=0).tolist())
    observed = agg["rps_model"]
    nullref = {
        "observed": observed,
        "null_mean": float(np.mean(null_dist)),
        "null_p5": float(np.percentile(null_dist, 5)),
        "tail_p": tail_probability(observed, null_dist, side="lower"),
        "percentile": percentile_of(observed, null_dist),
        "n_samples": len(null_dist),
    }

    winner = {}
    for key in winner_probs:
        winner[f"brier_{key}"] = brier(winner_probs[key], winner_outcomes)
        winner[f"logloss_{key}"] = log_loss(winner_probs[key], winner_outcomes)

    p_pod = [p for p, _ in podium_pairs]
    y_pod = [y for _, y in podium_pairs]
    podium = {
        "brier": float(np.mean([(p - y) ** 2 for p, y in podium_pairs])),
        "base_rate": float(np.mean(y_pod)),
        "calibration": calibration_table(p_pod, y_pod, bins=10),
    }

    h2h = {"n": h2h_total, "hits": h2h_hits,
           "acc": h2h_hits / h2h_total if h2h_total else float("nan")}
    h2h["wilson95"] = _wilson(h2h_hits, h2h_total) if h2h_total else None

    strata = _stratify(per_race)

    return {"n_eval": len(per_race), "per_race": per_race, "aggregate": agg,
            "dm": dm, "nullref": nullref, "winner": winner, "podium": podium,
            "h2h_teammates": h2h, "strata": strata,
            "final_ratings": {k: round(v, 2) for k, v in elo.ratings.items()},
            "params": {"n_sims": n_sims, "sim_seed": sim_seed,
                       "burn_in_season": burn_in_season, "k_base": k_base,
                       "k_rookie": k_rookie, "seed_elo": SEED_ELO,
                       "rookie_races": ROOKIE_RACES,
                       "null_samples": null_samples}}


def _wilson(hits: int, n: int, z: float = 1.959963984540054) -> list[float]:
    """IC 95% de Wilson para proporção binomial."""
    if n == 0:
        return [float("nan"), float("nan")]
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [center - half, center + half]


def _stratify(per_race: list[dict]) -> dict:
    """Estratos: por temporada e por era de regulamento (2023-2025 antigo,
    2026 novo)."""
    out = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in per_race:
        groups[str(r["season"])].append(r)
        groups["era_antiga" if r["season"] <= 2025 else "era_2026"].append(r)
    for tag, rows in sorted(groups.items()):
        losses_m = [r["rps_model"] for r in rows]
        losses_g = [r["rps_grid"] for r in rows]
        stat, p = diebold_mariano(losses_m, losses_g, h=1)
        out[tag] = {"n": len(rows),
                    "rps_model": float(np.mean(losses_m)),
                    "rps_grid": float(np.mean(losses_g)),
                    "dm_vs_grid": stat, "p": p}
    return out


# ---------- critério ordinal (verdicts pré-registrados) ----------

def verdict_h1(result: dict, alpha: float = 0.05) -> dict:
    """H1-F1: RPS do modelo < baseline de GRID com DM p<alpha (e o modelo
    precisa estar abaixo do percentil 5 do nulo — piso de significância)."""
    dm = result["dm"]["model_vs_grid"]
    nr = result["nullref"]
    beats_null = nr["tail_p"] < alpha and nr["observed"] < nr["null_p5"]
    beats_grid = dm["modelo_melhor"] and dm["p"] < alpha
    verdict = "COMPROVADA" if (beats_grid and beats_null) else "REFUTADA"
    return {"verdict": verdict, "beats_grid": beats_grid,
            "beats_null": beats_null, "dm": dm, "nullref": {
                k: nr[k] for k in ("observed", "null_p5", "tail_p")}}


def verdict_h2(result: dict) -> dict:
    """H2-F1: acerto H2H entre companheiros > 50% com IC de Wilson 95%
    inteiro acima de 0.5."""
    h = result["h2h_teammates"]
    if not h["n"]:
        return {"verdict": "REFUTADA", "motivo": "sem pares avaliáveis"}
    lo, hi = h["wilson95"]
    verdict = "COMPROVADA" if lo > 0.5 else "REFUTADA"
    return {"verdict": verdict, "acc": h["acc"], "n": h["n"],
            "wilson95": [lo, hi]}


# ---------- campo sintético (controle positivo do harness) ----------

def synthetic_races(n_drivers: int = 20, n_seasons: int = 3,
                    races_per_season: int = 20, elo_spread: float = 400.0,
                    seed: int = 7, informative: bool = True) -> list[dict]:
    """Gera corridas sintéticas no MESMO schema do db: forças verdadeiras
    conhecidas (escada de largura `elo_spread`), classificação sorteada por
    Plackett-Luce e grid = outra amostra PL das MESMAS forças (o
    'qualifying' — um baseline forte, como na F1 real). `informative=False`
    zera o spread: resultados viram permutações uniformes (ruído puro)."""
    rng = np.random.default_rng(seed)
    spread = elo_spread if informative else 0.0
    true_elos = np.linspace(1400 + spread / 2, 1400 - spread / 2, n_drivers)
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    skill = true_elos * _LN10_400

    races = []
    for s in range(n_seasons):
        season = 2022 + s
        for rnd in range(1, races_per_season + 1):
            order = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            quali = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            grid_of = np.empty(n_drivers, dtype=int)
            grid_of[quali] = np.arange(1, n_drivers + 1)
            results = []
            for pos0, i in enumerate(order):
                results.append({"driver": names[i], "constructor": f"Eq{i // 2}",
                                "grid": int(grid_of[i]), "position": pos0 + 1,
                                "status": "Finished", "dnf": 0,
                                "points": float(max(0, 10 - pos0))})
            races.append({"season": season, "round": rnd,
                          "name": f"GP Sintético {season}-{rnd}",
                          "circuit": "synth", "date": f"{season}-01-01",
                          "results": results})
    return races


def evaluate_ordinal_pipeline(races: list[dict], *, n_sims: int = 2000,
                              null_samples: int = 200) -> dict:
    """O pipeline COMPLETO (backtest prequential + critério H1) como função
    série→veredito, no contrato do harness do core (controle positivo)."""
    result = run_backtest(races, n_sims=n_sims, null_samples=null_samples)
    return verdict_h1(result)
