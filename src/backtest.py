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
from .context_factors import (CIRCUIT_TYPES, ContextRatingBook,
                              PitEfficiencyTracker, ReliabilityTracker,
                              VolatilityShock, circuit_type,
                              match_circuit_metadata, race_pitstop_summary)

from predictor_core.measurement.metrics import (brier, calibration_table,
                                                diebold_mariano, log_loss, rps)
from predictor_core.measurement.nullref import percentile_of, tail_probability
from predictor_core.testing.prequential import PrequentialEvaluator

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
                 seed_elo: float = SEED_ELO,
                 shock: "VolatilityShock | None" = None):
        self.ratings: dict[str, float] = {}
        self.races_seen: dict[str, int] = defaultdict(int)
        self.k_base, self.k_rookie, self.seed_elo = k_base, k_rookie, seed_elo
        self.shock = shock

    def rating(self, name: str) -> float:
        return self.ratings.get(name, self.seed_elo)

    def shrink_to_mean(self, factor: float) -> None:
        """Choque estrutural de transição de regulamento (H8-F1): encolhe
        TODOS os ratings vistos em direção à semente (1400), na proporção
        `factor` ∈ [0, 1] — 0 é no-op, 1 reseta todo mundo. Aplicado UMA
        VEZ na virada de uma temporada de regulamento novo (2022, 2026):
        `new = seed + (1-factor)·(rating-seed)`. Afeta o campo INTEIRO
        (regulamento muda o jogo pra todos), diferente do
        `VolatilityShock` da Fase 4 (K temporário, um piloto/equipe só)."""
        if not (0.0 <= factor <= 1.0):
            raise ValueError("factor precisa estar em [0, 1]")
        if factor == 0.0:
            return
        for m in self.ratings:
            self.ratings[m] = self.seed_elo + (1.0 - factor) * (self.ratings[m] - self.seed_elo)

    def _k(self, name: str) -> float:
        base = (self.k_rookie if self.races_seen[name] < ROOKIE_RACES
                else self.k_base)
        return base * (self.shock.k_multiplier(name) if self.shock else 1.0)

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
            if self.shock:
                self.shock.tick(m)


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


def _grid_elos(results: list[dict], n: int) -> np.ndarray:
    """Elos da escada 1750→1350 aplicados à ORDEM DE LARGADA (0 = pit
    lane → fim da fila, declarado). Compartilhado entre Fase 1 (baseline)
    e Fase 2 (feature do blend)."""
    grid_raw = np.array([r["grid"] if r["grid"] > 0 else n + 1
                         for r in results], dtype=float)
    return ladder(n)[grid_raw.argsort(kind="stable").argsort()]


def _standings_elos(results: list[dict], table: dict, n: int) -> np.ndarray:
    """Elos da escada aplicados aos pontos da temporada corrente (ou do
    ano anterior na rodada 1 — novato no grid fica em 0 pontos, fim da
    fila, ordem estável)."""
    pts = np.array([-table.get(r["driver"], 0.0) for r in results])
    return ladder(n)[pts.argsort(kind="stable").argsort()]


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
            elos_grid = _grid_elos(results, n)
            table = (season_points[season] if season_points[season]
                     else season_points[season - 1])
            elos_standings = _standings_elos(results, table, n)

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
                    seed: int = 7, informative: bool = True,
                    grid_random: bool = False,
                    form_scale: float = 0.0) -> list[dict]:
    """Gera corridas sintéticas no MESMO schema do db: forças verdadeiras
    conhecidas (escada de largura `elo_spread`), classificação sorteada por
    Plackett-Luce e grid = outra amostra PL das MESMAS forças (o
    'qualifying' — um baseline forte, como na F1 real). `informative=False`
    zera o spread: resultados viram permutações uniformes (ruído puro).
    `grid_random=True` (harness H3, especificidade): a corrida continua
    informativa mas o GRID vira permutação independente do skill — um
    grid sem informação não pode ajudar o blend.

    `form_scale>0` (harness H3, sensibilidade): soma um choque de "forma
    do dia" ~Gumbel(0, form_scale) POR CORRIDA, compartilhado entre quali
    e largada — algo que o Elo (que só aprende a força de LONGO PRAZO,
    médias entre corridas) não vê, mas que o grid dessa corrida específica
    CARREGA. É o mecanismo que torna "grid como feature" genuinamente
    informativo além do Elo estático, e não apenas outro estimador
    ruidoso da mesma força de sempre."""
    rng = np.random.default_rng(seed)
    spread = elo_spread if informative else 0.0
    true_elos = np.linspace(1400 + spread / 2, 1400 - spread / 2, n_drivers)
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    skill = true_elos * _LN10_400

    races = []
    for s in range(n_seasons):
        season = 2022 + s
        for rnd in range(1, races_per_season + 1):
            form = (rng.gumbel(scale=form_scale, size=n_drivers)
                    if form_scale > 0 else 0.0)
            order = np.argsort(-(skill + form + rng.gumbel(size=n_drivers)))
            if grid_random:
                grid_of = rng.permutation(n_drivers) + 1
            else:
                quali = np.argsort(-(skill + form + rng.gumbel(size=n_drivers)))
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


# =====================================================================
# FASE 2 — grid como FEATURE do modelo (blend Elo+grid) e calibração
# =====================================================================
#
# O relatório da Fase 1 apontou dois alvos: (H3) o grid de largada só
# ajuda como BASELINE separado — o teste real é se ele ajuda DENTRO do
# modelo, misturado ao Elo; (H4) o P(pódio) é subconfiante nas faixas
# altas — Platt é candidata de calibração.
#
# Protocolo SEM lookahead adicional: o peso do blend (w) e os parâmetros
# de Platt são escolhidos SÓ no período de DESENVOLVIMENTO (2023, após o
# burn-in de 2022) — nunca olhando 2024-2026, que é o período de
# avaliação genuinamente cego. w e Platt ficam CONGELADOS ao entrar em
# 2024. O Elo em si continua a mesma passada contínua (2022→2026); só a
# escolha de hiperparâmetro é que fica confinada ao "treino".


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500.0, 500.0)))


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


def fit_platt(scores: np.ndarray, outcomes: np.ndarray,
             iters: int = 50, ridge: float = 1e-6) -> tuple[float, float]:
    """Platt scaling: ajusta (a, b) em sigmoid(a·logit(p) + b) ~ outcome
    por Newton-Raphson (regressão logística 1-D, 2 parâmetros). `ridge` no
    Hessiano evita singularidade quando os scores são quase-degenerados."""
    x = _logit(np.asarray(scores, dtype=float))
    y = np.asarray(outcomes, dtype=float)
    a, b = 1.0, 0.0
    for _ in range(iters):
        z = a * x + b
        pi = _sigmoid(z)
        w = np.maximum(pi * (1.0 - pi), 1e-9)
        grad = np.array([np.sum((y - pi) * x), np.sum(y - pi)])
        h = np.array([[np.sum(w * x * x) + ridge, np.sum(w * x)],
                     [np.sum(w * x), np.sum(w) + ridge]])
        delta = np.linalg.solve(h, grad)
        a += delta[0]
        b += delta[1]
        if np.abs(delta).max() < 1e-10:
            break
    return float(a), float(b)


def apply_platt(scores: np.ndarray, a: float, b: float) -> np.ndarray:
    return _sigmoid(a * _logit(np.asarray(scores, dtype=float)) + b)


def blend_elos(elos_model: np.ndarray, elos_grid: np.ndarray,
               w: float) -> np.ndarray:
    """Mistura LINEAR no espaço Elo: (1-w)·Elo + w·escada(grid). w=0 é o
    Elo puro da Fase 1; w=1 é o baseline de grid puro."""
    return (1.0 - w) * elos_model + w * elos_grid


def run_fase2(races: list[dict], *, n_sims: int = 10000, sim_seed: int = 13,
             burn_in_season: int = 2022, dev_season: int = 2023,
             eval_start_season: int = 2024, k_base: float = 24.0,
             k_rookie: float = 40.0, null_samples: int = 500,
             w_grid: float | None = None,
             w_candidates: tuple = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6,
                                    0.7, 0.8, 0.9, 1.0)) -> dict:
    """Passada prequential contínua 2022→fim, com um estágio de
    DESENVOLVIMENTO (`dev_season`) onde: (a) escolhe-se w minimizando o
    RPS médio do blend nas corridas de 2023, e (b) ajusta-se Platt no
    P(pódio) do blend vencedor sobre as mesmas corridas de 2023. A partir
    de `eval_start_season`, w e Platt ficam CONGELADOS — é aí que as
    métricas reportadas (RPS, DM, nulo, calibração) são calculadas, cegas
    ao ajuste de hiperparâmetro. `w_grid` explícito pula a seleção (usado
    pelo harness sintético, onde 1 temporada de dev não teria poder)."""
    elo = BacktestElo(k_base=k_base, k_rookie=k_rookie)
    season_points: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    dev_records: list[dict] = []     # p/ seleção de w e ajuste de Platt

    def _predict_bundle(race, season, round_):
        results = race["results"]
        n = len(results)
        names = [r["driver"] for r in results]
        elos_model = np.array([elo.rating(nm) for nm in names])
        elos_grid = _grid_elos(results, n)
        actual_pos = np.array([r["position"] - 1 for r in results])
        return {"n": n, "names": names, "elos_model": elos_model,
                "elos_grid": elos_grid, "actual_pos": actual_pos,
                "dnf": np.array([bool(r["dnf"]) for r in results]),
                "season": season, "round": round_, "name": race["name"]}

    for race in races:
        season, round_ = race["season"], race["round"]
        if len(race["results"]) < 2:
            continue
        if season == dev_season:
            dev_records.append(_predict_bundle(race, season, round_))
        finish_order = [r["driver"] for r in race["results"] if not r["dnf"]]
        elo.update(finish_order)
        for r in race["results"]:
            season_points[season][r["driver"]] += r["points"]

    if w_grid is None:
        if not dev_records:
            raise ValueError(f"nenhuma corrida em {dev_season} para "
                             "seleção de w (período de desenvolvimento vazio)")
        best_w, best_rps = w_candidates[0], float("inf")
        for w in w_candidates:
            losses = []
            for rec in dev_records:
                blended = blend_elos(rec["elos_model"], rec["elos_grid"], w)
                p = position_probs(blended, n_sims,
                                   _race_seed(sim_seed, rec["season"],
                                              rec["round"], 10))
                losses.append(rps([row.tolist() for row in p],
                                  rec["actual_pos"].tolist()))
            mean_rps = float(np.mean(losses))
            if mean_rps < best_rps:
                best_rps, best_w = mean_rps, w
        w_grid = best_w
    else:
        best_rps = None

    # Platt: ajusta no P(pódio) do blend VENCEDOR sobre as corridas de dev
    dev_podium_p, dev_podium_y = [], []
    for rec in dev_records:
        blended = blend_elos(rec["elos_model"], rec["elos_grid"], w_grid)
        p = position_probs(blended, n_sims,
                           _race_seed(sim_seed, rec["season"], rec["round"], 11))
        for i in range(rec["n"]):
            dev_podium_p.append(float(p[i, :3].sum()))
            dev_podium_y.append(int(rec["actual_pos"][i] < 3))
    platt_a, platt_b = fit_platt(np.array(dev_podium_p), np.array(dev_podium_y))

    # --- segunda passada: reconstrói o Elo do zero para avaliar 2ª metade
    # (o estado do Elo em run_fase2 já avançou até o fim no loop acima;
    # refazemos com um Elo NOVO para reproduzir o estado exatamente como
    # estava ANTES de cada corrida da avaliação, sem custo extra de rede) --
    elo2 = BacktestElo(k_base=k_base, k_rookie=k_rookie)
    season_points2: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    per_race: list[dict] = []
    podium_raw_pairs: list[tuple[float, int]] = []
    podium_cal_pairs: list[tuple[float, int]] = []
    h2h_hits = h2h_total = 0
    null_race_perm_rps: list[list[float]] = []

    for race in races:
        season, round_ = race["season"], race["round"]
        results = race["results"]
        n = len(results)
        if n < 2:
            continue
        names = [r["driver"] for r in results]
        actual_pos = np.array([r["position"] - 1 for r in results])
        dnf_mask = np.array([bool(r["dnf"]) for r in results])
        is_eval = season >= eval_start_season

        if is_eval:
            elos_model = np.array([elo2.rating(nm) for nm in names])
            elos_grid = _grid_elos(results, n)
            elos_blend = blend_elos(elos_model, elos_grid, w_grid)
            table = (season_points2[season] if season_points2[season]
                     else season_points2[season - 1])
            elos_standings = _standings_elos(results, table, n)

            probs = {
                "blend": position_probs(elos_blend, n_sims,
                                        _race_seed(sim_seed, season, round_, 20)),
                "elo_puro": position_probs(elos_model, n_sims,
                                          _race_seed(sim_seed, season, round_, 21)),
                "grid": position_probs(elos_grid, n_sims,
                                       _race_seed(sim_seed, season, round_, 22)),
                "standings": position_probs(elos_standings, n_sims,
                                            _race_seed(sim_seed, season, round_, 23)),
            }
            outcomes = actual_pos.tolist()
            rec = {"season": season, "round": round_, "name": race["name"],
                  "n_drivers": n, "n_dnf": int(dnf_mask.sum())}
            for key, p in probs.items():
                rec[f"rps_{key}"] = rps([row.tolist() for row in p], outcomes)

            for i in range(n):
                p_raw = float(probs["blend"][i, :3].sum())
                p_cal = float(apply_platt(np.array([p_raw]), platt_a, platt_b)[0])
                y = int(actual_pos[i] < 3)
                podium_raw_pairs.append((p_raw, y))
                podium_cal_pairs.append((p_cal, y))

            teams: dict[str, list[int]] = defaultdict(list)
            for i, r in enumerate(results):
                teams[r["constructor"]].append(i)
            for idx in teams.values():
                if len(idx) == 2 and not dnf_mask[idx].any():
                    a_i, b_i = idx
                    ra, rb = elos_blend[a_i], elos_blend[b_i]
                    if ra == rb:
                        continue
                    pred_a = ra > rb
                    real_a = actual_pos[a_i] < actual_pos[b_i]
                    h2h_hits += int(pred_a == real_a)
                    h2h_total += 1

            rng = np.random.default_rng(_race_seed(sim_seed, season, round_, 24))
            cost = _rps_cost_matrix(probs["blend"])
            null_race_perm_rps.append(
                [float(cost[rng.permutation(n), actual_pos].mean())
                 for _ in range(null_samples)])
            per_race.append(rec)

        finish_order = [r["driver"] for r in results if not r["dnf"]]
        elo2.update(finish_order)
        for r in results:
            season_points2[season][r["driver"]] += r["points"]

    if not per_race:
        raise ValueError(f"nenhuma corrida a partir de {eval_start_season} "
                         "para avaliação")

    agg = {}
    for key in ("rps_blend", "rps_elo_puro", "rps_grid", "rps_standings"):
        agg[key] = float(np.mean([r[key] for r in per_race]))

    dm = {}
    losses_blend = [r["rps_blend"] for r in per_race]
    for base in ("elo_puro", "grid", "standings"):
        stat, p = diebold_mariano(losses_blend,
                                  [r[f"rps_{base}"] for r in per_race], h=1)
        dm[f"blend_vs_{base}"] = {"dm": stat, "p": p,
                                  "blend_melhor": bool(stat < 0)}

    null_matrix = np.array(null_race_perm_rps)
    null_dist = sorted(null_matrix.mean(axis=0).tolist())
    nullref = {"observed": agg["rps_blend"],
              "null_mean": float(np.mean(null_dist)),
              "null_p5": float(np.percentile(null_dist, 5)),
              "tail_p": tail_probability(agg["rps_blend"], null_dist, side="lower"),
              "percentile": percentile_of(agg["rps_blend"], null_dist),
              "n_samples": len(null_dist)}

    podium = {
        "brier_raw": float(np.mean([(p - y) ** 2 for p, y in podium_raw_pairs])),
        "brier_calibrated": float(np.mean([(p - y) ** 2 for p, y in podium_cal_pairs])),
        "calibration_raw": calibration_table(
            [p for p, _ in podium_raw_pairs], [y for _, y in podium_raw_pairs]),
        "calibration_calibrated": calibration_table(
            [p for p, _ in podium_cal_pairs], [y for _, y in podium_cal_pairs]),
    }

    h2h = {"n": h2h_total, "hits": h2h_hits,
          "acc": h2h_hits / h2h_total if h2h_total else float("nan")}
    h2h["wilson95"] = _wilson(h2h_hits, h2h_total) if h2h_total else None

    return {"n_eval": len(per_race), "per_race": per_race, "aggregate": agg,
            "dm": dm, "nullref": nullref, "podium": podium,
            "h2h_teammates": h2h,
            "w_grid": w_grid, "w_dev_rps": best_rps,
            "platt": {"a": platt_a, "b": platt_b},
            "final_ratings": {k: round(v, 2) for k, v in elo2.ratings.items()},
            "params": {"n_sims": n_sims, "sim_seed": sim_seed,
                      "burn_in_season": burn_in_season,
                      "dev_season": dev_season,
                      "eval_start_season": eval_start_season,
                      "k_base": k_base, "k_rookie": k_rookie,
                      "null_samples": null_samples}}


def verdict_h3(result: dict, alpha: float = 0.05) -> dict:
    """H3-F1b: o blend Elo+grid (peso escolhido SÓ no dev/2023) tem RPS
    menor que o Elo PURO no período de avaliação cego, DM p<alpha."""
    dm = result["dm"]["blend_vs_elo_puro"]
    verdict = "COMPROVADA" if (dm["blend_melhor"] and dm["p"] < alpha) else "REFUTADA"
    return {"verdict": verdict, "dm": dm, "w_grid": result["w_grid"]}


def verdict_h4(result: dict) -> dict:
    """H4-F1b: a calibração de Platt (ajustada em 2023) reduz o Brier
    binário do P(pódio) no período de avaliação cego frente ao valor cru."""
    pod = result["podium"]
    melhora = pod["brier_calibrated"] < pod["brier_raw"]
    return {"verdict": "COMPROVADA" if melhora else "REFUTADA",
           "brier_raw": pod["brier_raw"],
           "brier_calibrated": pod["brier_calibrated"]}


def synthetic_races_h3(informative: bool, seed: int = 7) -> list[dict]:
    """Cenários canônicos do harness de H3 (grid como feature).
    `informative=True`: choque de "forma do dia" (form_scale=60)
    compartilhado entre quali e largada — o grid CARREGA informação que
    o Elo estático não vê (sensibilidade: o critério tem que confirmar).
    `informative=False`: mesmo choque de forma, mas grid embaralhado
    independente do skill — sem informação incremental nenhuma
    (especificidade: o critério NÃO pode confirmar)."""
    return synthetic_races(informative=True, grid_random=not informative,
                           form_scale=60.0, seed=seed)


def evaluate_grid_feature_pipeline(races: list[dict], *, n_sims: int = 2000,
                                   null_samples: int = 200) -> dict:
    """Pipeline completo da Fase 2 (dev→seleção de w→blend→critério H3)
    como função série→veredito — contrato do harness do core. Roda a
    seleção de w de verdade (não fixa) para validar a MECÂNICA completa,
    não só a lógica do veredito."""
    result = run_fase2(races, n_sims=n_sims, null_samples=null_samples,
                       dev_season=2023, eval_start_season=2024)
    return verdict_h3(result)


# =====================================================================
# FASE 4a — o grid de largada como PISO OFICIAL (H0), formalizado via
# PrequentialEvaluator + bootstrap pareado (padrão do brasileirao-predictor)
# =====================================================================
#
# A Fase 1 já mediu isso com um loop manual (run_backtest + Diebold-Mariano).
# Aqui a MESMA pergunta é respondida por um caminho INDEPENDENTE: o motor
# ABC do core (`predictor_core.testing.prequential.PrequentialEvaluator`)
# controla o fatiamento temporal (anti-leakage por CONSTRUÇÃO, não por
# disciplina) e o veredito usa bootstrap pareado (IC95 do delta de RPS por
# corrida) em vez de só Diebold-Mariano — duas réguas, uma pergunta. Se os
# dois caminhos concordam, a conclusão da Fase 1 fica mais dura de derrubar.

def _build_h0_observations(races: list[dict]) -> list[dict]:
    """Uma observação por corrida: `entries` (grid, visível ANTES da
    largada) e `results` (posição final — o `target_key` que o
    PrequentialEvaluator blinda de vazamento)."""
    obs = []
    for race in races:
        results = race["results"]
        if len(results) < 2:
            continue
        obs.append({
            "season": race["season"], "round": race["round"],
            "entries": [{"driver": r["driver"], "grid": r["grid"]}
                       for r in results],
            "results": [{"driver": r["driver"], "position": r["position"],
                        "dnf": r["dnf"]} for r in results],
        })
    return obs


class GridBaselineEvaluator(PrequentialEvaluator):
    """H0 formal: grid de largada → escada 1750-1350 → Plackett-Luce.
    MEMORYLESS por design (mesma disciplina do EloBaselineEvaluator do
    brasileirao: H0 não tem parâmetro ajustado nos dados)."""

    def __init__(self, *, n_sims: int = 5000, sim_seed: int = 13):
        super().__init__(target_key="results")
        self.n_sims, self.sim_seed = n_sims, sim_seed

    def train_step(self, history: list) -> None:
        pass   # sem estado — o grid de HOJE não depende do passado

    def predict_step(self, features: dict) -> np.ndarray:
        entries = features["entries"]
        n = len(entries)
        elos = _grid_elos([{"grid": e["grid"]} for e in entries], n)
        return position_probs(elos, self.n_sims,
                              _race_seed(self.sim_seed, features["season"],
                                        features["round"], 90))


class EloPlackettLuceEvaluator(PrequentialEvaluator):
    """Elo puro (Fase 1) no contrato do PrequentialEvaluator do core.
    `train_step` reconstrói o Elo do ZERO a cada chamada — determinístico
    (mesma história → mesmos ratings), mesma disciplina do brasileirao."""

    def __init__(self, *, k_base: float = 24.0, k_rookie: float = 40.0,
                n_sims: int = 5000, sim_seed: int = 13):
        super().__init__(target_key="results")
        self.k_base, self.k_rookie = k_base, k_rookie
        self.n_sims, self.sim_seed = n_sims, sim_seed
        self.elo = BacktestElo(k_base=k_base, k_rookie=k_rookie)

    def train_step(self, history: list) -> None:
        self.elo = BacktestElo(k_base=self.k_base, k_rookie=self.k_rookie)
        for obs in history:
            finish_order = [r["driver"] for r in obs["results"] if not r["dnf"]]
            self.elo.update(finish_order)

    def predict_step(self, features: dict) -> np.ndarray:
        names = [e["driver"] for e in features["entries"]]
        elos = np.array([self.elo.rating(nm) for nm in names])
        return position_probs(elos, self.n_sims,
                              _race_seed(self.sim_seed, features["season"],
                                        features["round"], 91))


def paired_bootstrap_ci(delta: np.ndarray, *, n_boot: int = 2000,
                        seed: int = 13) -> tuple:
    """IC95 por bootstrap PAREADO do delta por corrida (mesmo padrão do
    brasileirao-predictor: reamostra os ÍNDICES, preservando o pareamento
    corrida-a-corrida entre os dois previsores)."""
    rng = np.random.default_rng(seed)
    n = delta.shape[0]
    idx = rng.integers(0, n, size=(n_boot, n))
    means = delta[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def run_h0_formal(races: list[dict], *, burn_in_season: int = 2022,
                  n_sims: int = 5000, sim_seed: int = 13,
                  k_base: float = 24.0, k_rookie: float = 40.0,
                  n_boot: int = 2000, boot_seed: int = 13) -> dict:
    """Roda GridBaselineEvaluator e EloPlackettLuceEvaluator sobre a MESMA
    lista de observações (pareamento garantido por construção — nenhum
    join por índice pode divergir). `min_history` = nº de corridas do
    burn-in, deixando 2022 fora da avaliação exatamente como na Fase 1."""
    obs = _build_h0_observations(races)
    min_history = sum(1 for o in obs if o["season"] <= burn_in_season)
    if min_history >= len(obs):
        raise ValueError("nenhuma corrida após o burn-in para avaliar H0")

    grid_ev = GridBaselineEvaluator(n_sims=n_sims, sim_seed=sim_seed)
    elo_ev = EloPlackettLuceEvaluator(k_base=k_base, k_rookie=k_rookie,
                                      n_sims=n_sims, sim_seed=sim_seed)
    grid_out = grid_ev.run(obs, min_history=min_history)
    elo_out = elo_ev.run(obs, min_history=min_history)

    rps_grid, rps_elo = [], []
    for g, e in zip(grid_out, elo_out):
        assert g["index"] == e["index"]
        outcomes = [r["position"] - 1 for r in g["actual"]]
        rps_grid.append(rps([row.tolist() for row in g["prediction"]], outcomes))
        rps_elo.append(rps([row.tolist() for row in e["prediction"]], outcomes))

    rps_grid_arr, rps_elo_arr = np.array(rps_grid), np.array(rps_elo)
    delta = rps_grid_arr - rps_elo_arr    # negativo => grid (H0) melhor
    ci = paired_bootstrap_ci(delta, n_boot=n_boot, seed=boot_seed)
    dm_stat, dm_p = diebold_mariano(rps_grid_arr.tolist(), rps_elo_arr.tolist(), h=1)

    return {"n_eval": len(rps_grid), "rps_grid_h0": float(rps_grid_arr.mean()),
           "rps_elo": float(rps_elo_arr.mean()),
           "delta_mean": float(delta.mean()), "bootstrap_ci95": list(ci),
           "dm": {"dm": dm_stat, "p": dm_p}}


def verdict_h0_formal(result: dict, alpha: float = 0.05) -> dict:
    """H0-F1-formal: o grid de largada (H0) bate o Elo puro no RPS —
    reafirma o achado da Fase 1 (H1-F1 REFUTADA) por um caminho
    INDEPENDENTE (PrequentialEvaluator do core + bootstrap pareado, não
    o loop manual + Diebold-Mariano da Fase 1). COMPROVADA aqui = grid
    confirmado como piso oficial; CONSISTENTE com H1-F1 REFUTADA, não
    contraditório — são a mesma verdade vista de dois instrumentos."""
    ci_lo, ci_hi = result["bootstrap_ci95"]
    grid_bootstrap = ci_hi < 0.0
    grid_dm = result["dm"]["dm"] < 0.0 and result["dm"]["p"] < alpha
    verdict = "COMPROVADA" if (grid_bootstrap and grid_dm) else "REFUTADA"
    return {"verdict": verdict, "bootstrap_ci95": result["bootstrap_ci95"],
           "dm": result["dm"]}


# =====================================================================
# FASE 4b/c — rating por CONTEXTO de circuito (CS/LoL: rating por mapa) +
# decomposição de fatores (NBA: Four Factors) com dado REAL
# =====================================================================
#
# Três adições sequenciais sobre o blend Elo+grid da Fase 2 (w_grid já
# COMPROVADO, tratado aqui como FIXO — cada adição isola sua própria
# contribuição marginal, comparada ao melhor blend do passo anterior):
#
#   H5-F1c: + bônus de contexto de circuito (RatingBook do core, um por
#           tipo power/downforce/balanced — os metadados qualitativos já
#           declarados em data/circuits_f1.json desde a Fase 0, nunca
#           consumidos até aqui).
#   H6-F1c: + penalidade de Reliability (taxa de DNF rolling por piloto).
#   H7-F1c: + penalidade de Pit Efficiency (duração de pit stop rolling
#           por equipe, z-score contra dispersão HISTÓRICA — nunca a da
#           corrida corrente, que seria lookahead).
#
# w_ctx/w_rel/w_pit escolhidos por busca sequencial (greedy) SÓ no dev
# (2023): fixa o anterior, varre o candidato seguinte. Frozen a partir de
# 2024 — a mesma disciplina de w_grid na Fase 2.

REL_SCALE = 200.0   # Elo penalizados por 100% de taxa de DNF, no teto w_rel=1
PIT_SCALE = 30.0    # Elo penalizados por 1 desvio-padrão de lentidão de boxe, no teto w_pit=1


def _fase4_bundle(race: dict, circuit_catalog: list, pitstops_this_race: list,
                  elo: "BacktestElo", ctxbook: ContextRatingBook,
                  reltrack: ReliabilityTracker,
                  pittrack: PitEfficiencyTracker) -> dict | None:
    """Extrai os componentes ANTES do update (previsão) para uma corrida:
    Elo do modelo, Elo do grid, bônus de contexto, taxa de reliability e
    z de pit efficiency — tudo lido do estado ATUAL dos trackers, nunca
    do resultado desta própria corrida."""
    results = race["results"]
    n = len(results)
    if n < 2:
        return None
    names = [r["driver"] for r in results]
    meta = match_circuit_metadata(race["circuit"], circuit_catalog)
    ctype = circuit_type(meta["power_sensitivity"], meta["downforce_sensitivity"]) if meta else None
    pit_by_driver = race_pitstop_summary(pitstops_this_race)
    return {
        "season": race["season"], "round": race["round"], "n": n, "names": names,
        "circuit_type": ctype,
        "elos_model": np.array([elo.rating(nm) for nm in names]),
        "elos_grid": _grid_elos(results, n),
        "ctx_bonus": np.array([ctxbook.bonus(nm, ctype) if ctype else 0.0
                              for nm in names]),
        "rel_rate": np.array([reltrack.rate(nm) for nm in names]),
        "pit_z": np.array([pittrack.z(r["constructor"]) for r in results]),
        "actual_pos": np.array([r["position"] - 1 for r in results]),
        "dnf": np.array([bool(r["dnf"]) for r in results]),
        "constructor_durations": {
            c: [pit_by_driver[r["driver_id"]] for r in results
               if r["constructor"] == c and r["driver_id"] in pit_by_driver]
            for c in {r["constructor"] for r in results}},
    }


def _fase4_advance_state(race: dict, elo: "BacktestElo",
                         ctxbook: ContextRatingBook,
                         reltrack: ReliabilityTracker,
                         pittrack: PitEfficiencyTracker,
                         bundle: dict, season_points: dict) -> None:
    """Atualiza TODOS os trackers com o resultado real — sempre DEPOIS de
    ler o bundle (previsão) da mesma corrida."""
    results = race["results"]
    finish_order = [r["driver"] for r in results if not r["dnf"]]
    elo.update(finish_order)
    if bundle["circuit_type"]:
        ctxbook.update(bundle["circuit_type"], finish_order)
    for r in results:
        reltrack.update(r["driver"], bool(r["dnf"]))
    for constructor, durs in bundle["constructor_durations"].items():
        if durs:
            pittrack.update(constructor, sum(durs) / len(durs))
    for r in results:
        season_points[race["season"]][r["driver"]] += r["points"]


def _fase4_elo_adjusted(bundle: dict, w_grid: float, w_ctx: float,
                        w_rel: float, w_pit: float) -> np.ndarray:
    return (blend_elos(bundle["elos_model"], bundle["elos_grid"], w_grid)
           + w_ctx * bundle["ctx_bonus"]
           - w_rel * REL_SCALE * bundle["rel_rate"]
           - w_pit * PIT_SCALE * bundle["pit_z"])


def run_fase4(races: list[dict], pitstops_by_race: dict, circuit_catalog: list,
             *, w_grid: float, n_sims: int = 8000, sim_seed: int = 13,
             burn_in_season: int = 2022, dev_season: int = 2023,
             eval_start_season: int = 2024, k_base: float = 24.0,
             k_rookie: float = 40.0, null_samples: int = 500,
             w_ctx: float | None = None, w_rel: float | None = None,
             w_pit: float | None = None,
             w_ctx_candidates: tuple = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5),
             w_rel_candidates: tuple = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0),
             w_pit_candidates: tuple = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0),
             rel_window: int = 12, pit_window: int = 10,
             purge_races: int = 0, embargo_races: int = 0) -> dict:
    """Passada prequential contínua com TRÊS fatores novos sobre o blend
    Elo+grid da Fase 2 (`w_grid` FIXO — já comprovado, não re-buscado
    aqui). Busca sequencial (greedy) de w_ctx→w_rel→w_pit no dev (2023);
    congelados para a avaliação CEGA (2024+). `pitstops_by_race`:
    {(season,round): [...]} de `db.load_pitstops_by_race`.

    `purge_races`/`embargo_races` (previsao-cripto, López de Prado):
    endurece a fronteira dev→avaliação contra correlação serial residual
    (ex.: o MESMO circuito perto da virada de temporada). `purge_races`
    descarta as ÚLTIMAS corridas do dev da BUSCA de peso; `embargo_races`
    descarta as PRIMEIRAS corridas da avaliação das MÉTRICAS reportadas
    (o Elo/trackers continuam atualizando por elas — só não contam no
    RPS agregado). Robustez: comparar com e sem (0 = sem gap, o default
    já usado nas Fases 2-4 originais)."""
    elo = BacktestElo(k_base=k_base, k_rookie=k_rookie)
    ctxbook = ContextRatingBook(default_rating=1400.0)
    reltrack = ReliabilityTracker(window=rel_window)
    pittrack = PitEfficiencyTracker(window=pit_window)
    season_points: dict = defaultdict(lambda: defaultdict(float))
    dev_records: list = []

    for race in races:
        bundle = _fase4_bundle(race, circuit_catalog,
                               pitstops_by_race.get((race["season"], race["round"]), []),
                               elo, ctxbook, reltrack, pittrack)
        if bundle is None:
            continue
        if race["season"] == dev_season:
            dev_records.append(bundle)
        _fase4_advance_state(race, elo, ctxbook, reltrack, pittrack, bundle, season_points)

    if not dev_records:
        raise ValueError(f"nenhuma corrida em {dev_season} para seleção de pesos")
    if purge_races >= len(dev_records):
        raise ValueError(f"purge_races ({purge_races}) >= corridas de dev "
                         f"({len(dev_records)}) — não sobraria nada para a busca de pesos")
    dev_for_search = dev_records[:-purge_races] if purge_races > 0 else dev_records

    def _dev_rps(wc: float, wr: float, wp: float) -> float:
        losses = []
        for rec in dev_for_search:
            adj = _fase4_elo_adjusted(rec, w_grid, wc, wr, wp)
            p = position_probs(adj, n_sims,
                               _race_seed(sim_seed, rec["season"], rec["round"], 40))
            losses.append(rps([row.tolist() for row in p], rec["actual_pos"].tolist()))
        return float(np.mean(losses))

    def _search(candidates: tuple, fixed: tuple, slot: int) -> tuple:
        """Varre `candidates` no slot `slot` de (wc,wr,wp)=`fixed`, mantendo
        os outros fixos. Retorna (melhor_w, melhor_rps)."""
        best_w, best_v = 0.0, _dev_rps(*fixed)
        for cand in candidates:
            trial = list(fixed)
            trial[slot] = cand
            v = _dev_rps(*trial)
            if v < best_v:
                best_v, best_w = v, cand
        return best_w, best_v

    dev_rps_trace = {}
    if w_ctx is None:
        w_ctx, dev_rps_trace["ctx"] = _search(w_ctx_candidates, (0.0, 0.0, 0.0), 0)
    if w_rel is None:
        w_rel, dev_rps_trace["rel"] = _search(w_rel_candidates, (w_ctx, 0.0, 0.0), 1)
    if w_pit is None:
        w_pit, dev_rps_trace["pit"] = _search(w_pit_candidates, (w_ctx, w_rel, 0.0), 2)

    # --- segunda passada: estado fresco, métricas SÓ na avaliação cega ---
    elo2 = BacktestElo(k_base=k_base, k_rookie=k_rookie)
    ctxbook2 = ContextRatingBook(default_rating=1400.0)
    reltrack2 = ReliabilityTracker(window=rel_window)
    pittrack2 = PitEfficiencyTracker(window=pit_window)
    season_points2: dict = defaultdict(lambda: defaultdict(float))
    per_race: list = []
    null_race_perm_rps: list = []
    eval_seen = 0

    for race in races:
        bundle = _fase4_bundle(race, circuit_catalog,
                               pitstops_by_race.get((race["season"], race["round"]), []),
                               elo2, ctxbook2, reltrack2, pittrack2)
        if bundle is None:
            continue
        is_eval = race["season"] >= eval_start_season
        if is_eval:
            eval_seen += 1
        embargoed = is_eval and eval_seen <= embargo_races
        if is_eval and not embargoed:
            variants = {
                "elo_grid": _fase4_elo_adjusted(bundle, w_grid, 0.0, 0.0, 0.0),
                "plus_ctx": _fase4_elo_adjusted(bundle, w_grid, w_ctx, 0.0, 0.0),
                "plus_ctx_rel": _fase4_elo_adjusted(bundle, w_grid, w_ctx, w_rel, 0.0),
                "full": _fase4_elo_adjusted(bundle, w_grid, w_ctx, w_rel, w_pit),
            }
            outcomes = bundle["actual_pos"].tolist()
            rec = {"season": bundle["season"], "round": bundle["round"],
                  "n_drivers": bundle["n"], "circuit_type": bundle["circuit_type"]}
            probs_full = None
            for key, elos in variants.items():
                p = position_probs(elos, n_sims,
                                   _race_seed(sim_seed, bundle["season"],
                                             bundle["round"], 50))
                rec[f"rps_{key}"] = rps([row.tolist() for row in p], outcomes)
                if key == "full":
                    probs_full = p
            rng = np.random.default_rng(
                _race_seed(sim_seed, bundle["season"], bundle["round"], 51))
            cost = _rps_cost_matrix(probs_full)
            null_race_perm_rps.append(
                [float(cost[rng.permutation(bundle["n"]), bundle["actual_pos"]].mean())
                 for _ in range(null_samples)])
            per_race.append(rec)
        _fase4_advance_state(race, elo2, ctxbook2, reltrack2, pittrack2, bundle, season_points2)

    if not per_race:
        raise ValueError(f"nenhuma corrida a partir de {eval_start_season} para avaliação")

    agg = {k: float(np.mean([r[f"rps_{k}"] for r in per_race]))
          for k in ("elo_grid", "plus_ctx", "plus_ctx_rel", "full")}
    dm = {}
    for a, b, tag in (("plus_ctx", "elo_grid", "h5"),
                      ("plus_ctx_rel", "plus_ctx", "h6"),
                      ("full", "plus_ctx_rel", "h7")):
        stat, p = diebold_mariano([r[f"rps_{a}"] for r in per_race],
                                  [r[f"rps_{b}"] for r in per_race], h=1)
        dm[tag] = {"dm": stat, "p": p, "melhor": bool(stat < 0),
                  "rps_a": agg[a], "rps_b": agg[b]}

    null_matrix = np.array(null_race_perm_rps)
    null_dist = sorted(null_matrix.mean(axis=0).tolist())
    nullref = {"observed": agg["full"], "null_p5": float(np.percentile(null_dist, 5)),
              "tail_p": tail_probability(agg["full"], null_dist, side="lower")}

    return {"n_eval": len(per_race), "per_race": per_race, "aggregate": agg,
           "dm": dm, "nullref": nullref,
           "weights": {"w_grid": w_grid, "w_ctx": w_ctx, "w_rel": w_rel,
                      "w_pit": w_pit},
           "dev_rps": dev_rps_trace,
           "params": {"n_sims": n_sims, "sim_seed": sim_seed,
                     "burn_in_season": burn_in_season, "dev_season": dev_season,
                     "eval_start_season": eval_start_season,
                     "rel_scale": REL_SCALE, "pit_scale": PIT_SCALE,
                     "rel_window": rel_window, "pit_window": pit_window}}


def verdict_h5(result: dict, alpha: float = 0.05) -> dict:
    """H5-F1c: bônus de contexto de circuito (RatingBook do core) bate o
    blend Elo+grid puro no RPS, avaliação cega 2024+."""
    d = result["dm"]["h5"]
    return {"verdict": "COMPROVADA" if (d["melhor"] and d["p"] < alpha) else "REFUTADA",
           "dm": d, "w_ctx": result["weights"]["w_ctx"]}


def verdict_h6(result: dict, alpha: float = 0.05) -> dict:
    """H6-F1c: penalidade de Reliability (DNF rolling) bate o blend
    anterior (Elo+grid+contexto) no RPS, avaliação cega 2024+."""
    d = result["dm"]["h6"]
    return {"verdict": "COMPROVADA" if (d["melhor"] and d["p"] < alpha) else "REFUTADA",
           "dm": d, "w_rel": result["weights"]["w_rel"]}


def verdict_h7(result: dict, alpha: float = 0.05) -> dict:
    """H7-F1c: penalidade de Pit Efficiency bate o blend anterior
    (Elo+grid+contexto+reliability) no RPS, avaliação cega 2024+."""
    d = result["dm"]["h7"]
    return {"verdict": "COMPROVADA" if (d["melhor"] and d["p"] < alpha) else "REFUTADA",
           "dm": d, "w_pit": result["weights"]["w_pit"]}


# ---------- harness sintético (Fase 4b/c) ----------

def synthetic_races_context(informative: bool, seed: int = 11) -> list[dict]:
    """Cenário do harness de H5: cada piloto tem uma força-base MAIS uma
    especialização por tipo de circuito ('circuit' = 'power'/'downforce'/
    'balanced' direto, sem precisar de metadado — o teste usa o gerador
    genérico do backtest.py com uma coluna extra). `informative=True`:
    especialização REAL (correlacionada com o tipo, persistente entre
    corridas do mesmo tipo). `informative=False`: sem especialização
    (força única) — o contexto não pode ajudar."""
    import numpy as _np
    rng = _np.random.default_rng(seed)
    n_drivers = 20
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    base_elo = _np.linspace(1600, 1200, n_drivers)
    spec = ({t: rng.uniform(-120, 120, n_drivers) for t in CIRCUIT_TYPES}
           if informative else {t: _np.zeros(n_drivers) for t in CIRCUIT_TYPES})
    races = []
    for s in range(3):
        season = 2022 + s
        for rnd in range(1, 21):
            ctype = CIRCUIT_TYPES[rnd % 3]
            skill = (base_elo + spec[ctype]) * _LN10_400
            order = _np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            quali = _np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            grid_of = _np.empty(n_drivers, dtype=int)
            grid_of[quali] = _np.arange(1, n_drivers + 1)
            results = []
            for pos0, i in enumerate(order):
                results.append({"driver": names[i], "driver_id": names[i].lower(),
                                "constructor": f"Eq{i // 2}", "grid": int(grid_of[i]),
                                "position": pos0 + 1, "status": "Finished",
                                "dnf": 0, "points": float(max(0, 10 - pos0))})
            races.append({"season": season, "round": rnd,
                         "name": f"GP Sintético {season}-{rnd}",
                         "circuit": f"synth-{ctype}", "date": f"{season}-01-01",
                         "results": results})
    return races


_SYNTH_CONTEXT_CATALOG = [
    {"name": "synth-power", "power_sensitivity": 0.9, "downforce_sensitivity": 0.2},
    {"name": "synth-downforce", "power_sensitivity": 0.2, "downforce_sensitivity": 0.9},
    {"name": "synth-balanced", "power_sensitivity": 0.5, "downforce_sensitivity": 0.5},
]


def evaluate_context_pipeline(races: list[dict], *, n_sims: int = 1500,
                              null_samples: int = 100) -> dict:
    """Pipeline completo de H5 (contexto de circuito) para o harness."""
    result = run_fase4(races, pitstops_by_race={},
                       circuit_catalog=_SYNTH_CONTEXT_CATALOG, w_grid=0.5,
                       n_sims=n_sims, null_samples=null_samples,
                       dev_season=2023, eval_start_season=2024,
                       w_rel=0.0, w_pit=0.0)
    return verdict_h5(result)


def synthetic_races_reliability(informative: bool, seed: int = 17) -> list[dict]:
    """Cenário do harness de H6: skill totalmente FLAT — se o skill
    variasse na mesma direção da confiabilidade (como numa primeira
    tentativa desta implementação), o Elo aprenderia o efeito de
    qualquer jeito via as próprias perdas pareadas do DNF, mascarando a
    incremental do fator explícito. Com skill flat, só a taxa de DNF
    PERSISTENTE (independente do rank de força) pode explicar a
    diferença de RPS. `informative=True`: metade dos pilotos quebra 50%
    das vezes, a outra metade nunca quebra. `informative=False`: DNF
    sorteado com a MESMA taxa para todos — a informação por piloto não
    existe, não tem o que aprender."""
    rng = np.random.default_rng(seed)
    n_drivers = 20
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    base_elo = np.full(n_drivers, 1400.0)
    dnf_prob = (np.where(np.arange(n_drivers) % 2 == 0, 0.5, 0.0) if informative
               else np.full(n_drivers, 0.25))
    races = []
    for s in range(3):
        season = 2022 + s
        for rnd in range(1, 21):
            skill = base_elo * _LN10_400
            order = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            quali = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            grid_of = np.empty(n_drivers, dtype=int)
            grid_of[quali] = np.arange(1, n_drivers + 1)
            dnfs = rng.uniform(size=n_drivers) < dnf_prob
            # DNF vai para o fim do grupo (mesma convenção da Jolpica)
            finishers = [i for i in order if not dnfs[i]]
            retirees = [i for i in order if dnfs[i]]
            final_order = finishers + retirees
            results = []
            for pos0, i in enumerate(final_order):
                results.append({"driver": names[i], "driver_id": names[i].lower(),
                                "constructor": f"Eq{i // 2}", "grid": int(grid_of[i]),
                                "position": pos0 + 1,
                                "status": "Finished" if i in finishers else "Accident",
                                "dnf": bool(dnfs[i]),
                                "points": float(max(0, 10 - pos0)) if not dnfs[i] else 0.0})
            races.append({"season": season, "round": rnd,
                         "name": f"GP Sintético {season}-{rnd}",
                         "circuit": "synth-balanced", "date": f"{season}-01-01",
                         "results": results})
    return races


def evaluate_reliability_pipeline(races: list[dict], *, n_sims: int = 1500,
                                  null_samples: int = 100) -> dict:
    """Pipeline completo de H6 (reliability) para o harness — isola o
    fator fixando w_ctx=0 (sintético não tem contexto de circuito real)."""
    result = run_fase4(races, pitstops_by_race={},
                       circuit_catalog=_SYNTH_CONTEXT_CATALOG, w_grid=0.5,
                       n_sims=n_sims, null_samples=null_samples,
                       dev_season=2023, eval_start_season=2024,
                       w_ctx=0.0, w_pit=0.0)
    return verdict_h6(result)


def synthetic_races_pitstops(informative: bool, seed: int = 23) -> list[dict]:
    """Cenário do harness de H7: metade das equipes tem habilidade de
    boxe MUITO maior (persistente, binária) — desloca a posição final E
    gera durações de pit stop correlacionadas. Crucial: o QUALI (grid)
    NÃO reflete a habilidade de boxe (ela só aparece DURANTE a corrida,
    igual pit stop real) — senão o blend Elo+grid já capturaria o efeito
    pela via do grid, mascarando a incremental do pit_z (mesma lição do
    H6: se skill e o fator novo se moverem pelo MESMO canal que o Elo já
    enxerga, o Elo aprende sozinho). `informative=False`: toda equipe
    igual — durações sem relação com a posição final."""
    rng = np.random.default_rng(seed)
    n_drivers = 20
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    n_teams = n_drivers // 2
    team_pit_skill = (np.where(np.arange(n_teams) % 2 == 0, 500.0, 0.0)
                      if informative else np.zeros(n_teams))
    base_elo = np.full(n_drivers, 1400.0)
    races, pitstops_by_race = [], {}
    for s in range(3):
        season = 2022 + s
        for rnd in range(1, 21):
            skill = (base_elo + np.repeat(team_pit_skill, 2)) * _LN10_400
            order = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            quali = np.argsort(-(base_elo * _LN10_400 + rng.gumbel(size=n_drivers)))
            grid_of = np.empty(n_drivers, dtype=int)
            grid_of[quali] = np.arange(1, n_drivers + 1)
            results, pits = [], []
            for pos0, i in enumerate(order):
                team_idx = i // 2
                dur = 25.0 - team_pit_skill[team_idx] / 20.0 + rng.normal(scale=1.0)
                driver_id = names[i].lower()
                pits.append({"driver_id": driver_id, "duration_s": max(10.0, dur)})
                results.append({"driver": names[i], "driver_id": driver_id,
                                "constructor": f"Eq{team_idx}", "grid": int(grid_of[i]),
                                "position": pos0 + 1, "status": "Finished",
                                "dnf": 0, "points": float(max(0, 10 - pos0))})
            races.append({"season": season, "round": rnd,
                         "name": f"GP Sintético {season}-{rnd}",
                         "circuit": "synth-balanced", "date": f"{season}-01-01",
                         "results": results})
            pitstops_by_race[(season, rnd)] = pits
    return races, pitstops_by_race


def evaluate_pit_pipeline(races_and_pits: tuple, *, n_sims: int = 1500,
                          null_samples: int = 100) -> dict:
    """Pipeline completo de H7 (pit efficiency) para o harness — isola o
    fator fixando w_ctx=w_rel=0."""
    races, pitstops = races_and_pits
    result = run_fase4(races, pitstops_by_race=pitstops,
                       circuit_catalog=_SYNTH_CONTEXT_CATALOG, w_grid=0.5,
                       n_sims=n_sims, null_samples=null_samples,
                       dev_season=2023, eval_start_season=2024,
                       w_ctx=0.0, w_rel=0.0)
    return verdict_h7(result)


# =====================================================================
# FASE 4d — choque de volatilidade pós-patch (CS/LoL). MECANISMO
# VALIDADO SÓ EM SINTÉTICO — sem calendário real de upgrades
# aerodinâmicos, NÃO é acionado no backtest real nem no serving.
# =====================================================================

def synthetic_races_shock(seed: int = 31, n_drivers: int = 10,
                          n_races: int = 40, jump_race: int = 20,
                          jump_size: float = 300.0) -> tuple:
    """Grid fixo, exceto UM piloto (o mais fraco) que recebe um salto de
    força NO MEIO da série sintética — o análogo do pacote de upgrade
    aerodinâmico que muda a força de uma equipe de um fim de semana para
    o outro. Retorna (corridas, nome_do_piloto_que_recebe_o_salto,
    índice_da_corrida_do_salto)."""
    rng = np.random.default_rng(seed)
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    base_elo = np.linspace(1500.0, 1300.0, n_drivers)
    shocked = names[-1]
    races = []
    for rnd in range(1, n_races + 1):
        elo_now = base_elo.copy()
        if rnd >= jump_race:
            elo_now[-1] += jump_size
        skill = elo_now * _LN10_400
        order = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
        results = [{"driver": names[i], "position": pos0 + 1}
                  for pos0, i in enumerate(order)]
        races.append({"round": rnd, "results": results})
    return races, shocked, jump_race


def evaluate_volatility_shock(*, trigger: bool, window: int = 10,
                              shock_races: int = 8, shock_multiplier: float = 4.0,
                              n_sims: int = 1500, seed: int = 31) -> float:
    """RPS médio na JANELA logo após o salto de força — `trigger=True`
    aciona `VolatilityShock` exatamente no piloto/corrida do salto (o
    cenário real de uso: alguém decide, com informação externa — "essa
    equipe trouxe upgrade nesta corrida" —, disparar o choque);
    `trigger=False` é o Elo padrão, sem choque algum. RPS menor com
    trigger=True demonstra que o mecanismo ajuda o Elo a reagir mais
    rápido ao salto."""
    races, shocked, jump = synthetic_races_shock(seed=seed)
    shock = VolatilityShock() if trigger else None
    elo = BacktestElo(shock=shock)
    losses = []
    for race in races:
        names = [r["driver"] for r in race["results"]]
        actual = [r["position"] - 1 for r in race["results"]]
        elos = np.array([elo.rating(nm) for nm in names])
        p = position_probs(elos, n_sims, _race_seed(seed, 2000, race["round"], 60))
        if jump <= race["round"] < jump + window:
            losses.append(rps([row.tolist() for row in p], actual))
        if trigger and race["round"] == jump:
            shock.trigger(shocked, races=shock_races, multiplier=shock_multiplier)
        elo.update(names)
    return float(np.mean(losses))


# =====================================================================
# FASE 5 — H8-F1: choque estrutural de TRANSIÇÃO DE REGULAMENTO
# =====================================================================
#
# Motivação: 2026 é o pior estrato do modelo (Fase 1/validação viva) —
# o Elo carrega 3+ anos de inércia do regulamento ANTERIOR e demora a
# "desconfiar" do histórico quando o carro muda de categoria inteira.
# Mecanismo: no primeiro round de uma temporada de regulamento NOVO
# (2022, 2026 — mudanças reais e documentadas do regulamento técnico da
# F1, não inventadas), encolhe TODOS os ratings em direção à semente
# (1400) por um fator fixo — força o modelo a "esquecer" parte do
# histórico acumulado exatamente no momento em que ele deixa de valer.
#
# Calibração CEGA: como o histórico do projeto começa em 2022 (burn-in
# — não há Elo acumulado de 2021 pra chocar; a virada de 2022 já é
# um no-op por construção), NÃO existe uma segunda transição real no
# nosso dado para calibrar o fator. Calibrar em 2026 e aplicar em 2026
# seria o oposto de cego. Solução adotada: o fator é escolhido SÓ em
# cenário SINTÉTICO (reembaralhamento de força do campo INTEIRO numa
# fronteira de temporada conhecida) — nunca olhando o RPS real de 2026 —
# e aplicado CEGAMENTE ao histórico real.

TRANSITION_SEASONS = (2022, 2026)   # mudanças reais de regulamento técnico da F1


def synthetic_races_transition(seed: int = 41, n_drivers: int = 20,
                               n_seasons_before: int = 3,
                               races_per_season: int = 20,
                               reshuffle: bool = True) -> tuple:
    """Cenário do harness de H8: `n_seasons_before` temporadas com forças
    ESTÁVEIS, depois uma fronteira de temporada onde o campo INTEIRO é
    reembaralhado (`reshuffle=True` — análogo a uma mudança real de
    regulamento; `reshuffle=False`: a força continua a mesma, controle
    de especificidade — encolher os ratings aí só pode ATRAPALHAR).
    Retorna (corridas, temporada_da_fronteira)."""
    rng = np.random.default_rng(seed)
    names = [f"Piloto{i:02d}" for i in range(n_drivers)]
    skill_antes = np.linspace(1600.0, 1200.0, n_drivers)
    skill_depois = (rng.permutation(skill_antes) if reshuffle
                   else skill_antes.copy())
    races = []
    temporada_fronteira = 2022 + n_seasons_before
    for s in range(n_seasons_before + 2):
        season = 2022 + s
        elo_now = skill_antes if season < temporada_fronteira else skill_depois
        for rnd in range(1, races_per_season + 1):
            skill = elo_now * _LN10_400
            order = np.argsort(-(skill + rng.gumbel(size=n_drivers)))
            results = [{"driver": names[i], "position": pos0 + 1, "dnf": 0}
                      for pos0, i in enumerate(order)]
            races.append({"season": season, "round": rnd, "results": results})
    return races, temporada_fronteira


def _rps_window_apos_fronteira(races: list, fronteira: int, shrink_factor: float,
                               window: int = 8, n_sims: int = 1200,
                               seed: int = 41) -> float:
    """RPS médio nas `window` primeiras corridas da temporada de
    fronteira — a janela que o choque estrutural deveria melhorar."""
    elo = BacktestElo()
    losses = []
    for race in races:
        results = race["results"]
        names = [r["driver"] for r in results]
        actual = [r["position"] - 1 for r in results]
        if race["season"] == fronteira and race["round"] == 1:
            elo.shrink_to_mean(shrink_factor)
        elos = np.array([elo.rating(nm) for nm in names])
        p = position_probs(elos, n_sims,
                           _race_seed(seed, race["season"], race["round"], 80))
        if race["season"] == fronteira and race["round"] <= window:
            losses.append(rps([row.tolist() for row in p], actual))
        elo.update(names)
    return float(np.mean(losses)) if losses else float("nan")


def calibrate_shrink_factor_sintetico(*, candidates: tuple = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                                      seed: int = 41) -> dict:
    """Calibração CEGA do fator de encolhimento: SÓ no cenário sintético
    com reembaralhamento real de força na fronteira. Retorna o fator
    vencedor e o RPS de cada candidato — nunca toca dado real."""
    races, fronteira = synthetic_races_transition(seed=seed, reshuffle=True)
    losses = {f: _rps_window_apos_fronteira(races, fronteira, f, seed=seed)
             for f in candidates}
    melhor = min(losses, key=losses.get)
    return {"factor": melhor, "losses_por_candidato": losses}


def evaluate_transition_shock_pipeline(*, reshuffle: bool, seed: int = 41,
                                       shrink_factor: float = 0.6) -> dict:
    """Harness H8: `reshuffle=True` (força realmente muda na fronteira)
    tem que mostrar RPS(com choque) < RPS(sem choque) na janela
    pós-fronteira; `reshuffle=False` (força ESTÁVEL) tem que mostrar o
    oposto ou neutro — encolher ratings que já estão certos só atrapalha
    (especificidade: o choque não pode "ajudar" quando não há ruptura)."""
    races, fronteira = synthetic_races_transition(seed=seed, reshuffle=reshuffle)
    com_choque = _rps_window_apos_fronteira(races, fronteira, shrink_factor, seed=seed)
    sem_choque = _rps_window_apos_fronteira(races, fronteira, 0.0, seed=seed)
    return {"com_choque": com_choque, "sem_choque": sem_choque,
           "ajuda": com_choque < sem_choque}


def run_h8(races: list, *, shrink_factor: float, n_sims: int = 10000,
          sim_seed: int = 13, burn_in_season: int = 2022,
          transition_seasons: tuple = TRANSITION_SEASONS,
          null_samples: int = 500) -> dict:
    """Passada prequential 2022→fim aplicando o choque estrutural
    (`shrink_factor`, calibrado às cegas em sintético) no primeiro round
    de cada temporada em `transition_seasons`. Compara, POR TEMPORADA
    avaliada (>burn_in), RPS com choque vs SEM choque (Elo comum) —
    mesmo par de corridas, mesma seed de simulação, só o estado do Elo
    difere."""
    def _passada(shrink: float) -> dict:
        elo = BacktestElo()
        por_temporada: dict = defaultdict(list)
        for race in races:
            results = race["results"]
            n = len(results)
            if n < 2:
                continue
            names = [r["driver"] for r in results]
            actual = [r["position"] - 1 for r in results]
            if race["round"] == 1 and race["season"] in transition_seasons:
                elo.shrink_to_mean(shrink)
            is_eval = race["season"] > burn_in_season
            if is_eval:
                elos = np.array([elo.rating(nm) for nm in names])
                p = position_probs(elos, n_sims,
                                   _race_seed(sim_seed, race["season"],
                                             race["round"], 85))
                por_temporada[race["season"]].append(
                    rps([row.tolist() for row in p], actual))
            finish_order = [r["driver"] for r in results if not r["dnf"]]
            elo.update(finish_order)
        return por_temporada

    com = _passada(shrink_factor)
    sem = _passada(0.0)
    temporadas = sorted(com)
    por_temporada = {}
    dm_2026 = None
    for s in temporadas:
        rps_com = float(np.mean(com[s]))
        rps_sem = float(np.mean(sem[s]))
        por_temporada[s] = {"rps_com_choque": rps_com, "rps_sem_choque": rps_sem,
                           "n": len(com[s])}
        if s in transition_seasons and s > burn_in_season:
            stat, p = diebold_mariano(com[s], sem[s], h=1)
            por_temporada[s]["dm"] = {"dm": stat, "p": p,
                                      "com_choque_melhor": bool(stat < 0)}
            if s == 2026:
                dm_2026 = por_temporada[s]["dm"]
    return {"por_temporada": por_temporada, "dm_2026": dm_2026,
           "shrink_factor": shrink_factor,
           "params": {"transition_seasons": transition_seasons,
                     "n_sims": n_sims, "burn_in_season": burn_in_season}}


def verdict_h8(result: dict, alpha: float = 0.05) -> dict:
    """H8-F1: o choque estrutural (fator calibrado às cegas em
    sintético) reduz o RPS de 2026 frente ao Elo comum, DM p<alpha."""
    dm = result["dm_2026"]
    if dm is None:
        return {"verdict": "REFUTADA", "motivo": "2026 fora da avaliação"}
    verdict = "COMPROVADA" if (dm["com_choque_melhor"] and dm["p"] < alpha) else "REFUTADA"
    return {"verdict": verdict, "dm": dm, "shrink_factor": result["shrink_factor"]}


def evaluate_h8_pipeline(races_e_fronteira: tuple, *,
                         shrink_factor: float = 0.8) -> dict:
    """Contrato do harness do core: recebe a série pronta de
    `synthetic_races_transition` (`edge_generator`=reshuffle=True,
    `noise_generator`=reshuffle=False) e devolve o veredito."""
    races, fronteira = races_e_fronteira
    com = _rps_window_apos_fronteira(races, fronteira, shrink_factor)
    sem = _rps_window_apos_fronteira(races, fronteira, 0.0)
    return {"verdict": "COMPROVADA" if com < sem else "REFUTADA",
           "com_choque": com, "sem_choque": sem}
