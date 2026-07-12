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
