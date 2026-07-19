"""Modelo Elo de F1 — Fase 0 (esqueleto). PRIMEIRO domínio ORDINAL do
ecossistema: o resultado é uma ordenação de 22 posições, não um binário.

Matemática:
- Rating Elo por PILOTO; força s_i = 10^(elo_i/400) (Bradley-Terry).
- A ordenação da corrida segue **Plackett-Luce** com essas forças — que é
  exatamente a extensão multiclasse do Elo: P(i à frente de j) marginal
  = s_i/(s_i+s_j) = logística clássica. Win/podium/top6 saem de simulação
  da ordenação via truque de Gumbel (argsort de elo·ln10/400 + ruído
  Gumbel), determinística com a seed do config.
- Head-to-head: fórmula fechada (sem simulação).
- update_ratings: comparações PAREADAS da ordem de chegada (todo par i,j),
  com K/(n-1) por par (magnitude total ~K por corrida) e K de NOVATO maior
  (progressão rápida) — média dos K dos dois pilotos do par. Soma zero.

Fase 0 declarada: `circuit` e `weather` são VALIDADOS mas não ajustam o
rating (as características de circuito e clima são a extensão da Fase 1+ —
os metadados já vivem em data/circuits_f1.json).
"""
import json
import math
from pathlib import Path

import numpy as np

from .config import (ROOT, load_config, load_drivers, resolve_circuit,
                     resolve_driver)

_LN10_400 = math.log(10.0) / 400.0

_FASE2_DEFAULTS = {"w_grid": 0.0, "platt_a": 1.0, "platt_b": 0.0,
                  "usar_blend": False, "usar_calibracao": False}


def win_probability(elo_a: float, elo_b: float) -> float:
    """P(A termina à frente de B) — logística clássica do Elo."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def _load_fase2_params(path: Path | str | None = None) -> dict:
    """Parâmetros vividos da Fase 2 (w do blend, Platt do pódio),
    condicionados aos vereditos H3-F1b/H4-F1b. Sem o arquivo (ainda não
    rodou scripts/run_fase2.py) ou veredito REFUTADA: cai no default —
    nenhuma feature nova entra no serving sem ter sido comprovada."""
    p = Path(path) if path else (ROOT / "data" / "fase2_params.json")
    if not p.exists():
        return dict(_FASE2_DEFAULTS)
    saved = json.loads(p.read_text(encoding="utf-8"))
    return {**_FASE2_DEFAULTS, **saved}


class F1EloModel:
    """Ratings Elo dos pilotos do grid 2026 (semente = campeonato 2025)."""

    def __init__(self, ratings_file: Path | str | None = None):
        cfg = load_config()
        self.drivers = {d["name"]: d for d in load_drivers()}
        self.ratings = {d["name"]: float(d["initial_elo"])
                        for d in load_drivers()}
        self.n_sims = int(cfg["model"].get("n_sims", 20000))
        self.seed = int(cfg["model"].get("sim_seed", 13))
        self.k_base = float(cfg["k_factor_base"])
        self.k_rookie = float(cfg["k_factor_rookie"])
        self.path = Path(ratings_file) if ratings_file else (
            ROOT / cfg.get("ratings_file", "data/ratings.json"))
        if self.path.exists():
            vividos = json.loads(self.path.read_text(encoding="utf-8"))
            # só pilotos do grid: um ratings.json com histórico (aposentados)
            # não pode inflar o grid do serving
            self.ratings.update({k: float(v) for k, v in vividos.items()
                                 if k in self.ratings})

    def _k(self, name: str) -> float:
        return (self.k_rookie if self.drivers.get(name, {}).get("rookie")
                else self.k_base)

    def predict_race(self, circuit: str, weather: str = "dry") -> dict:
        """Ranking dos 22 com P(win/podium/top6) — Plackett-Luce simulado.

        weather é validado ('dry'|'wet') mas NÃO ajusta na Fase 0 (declarado)."""
        c = resolve_circuit(circuit)
        if weather not in ("dry", "wet"):
            raise ValueError(f"weather desconhecido: {weather!r} (dry|wet)")
        names = list(self.ratings)
        skill = np.array([self.ratings[n] for n in names]) * _LN10_400
        rng = np.random.default_rng(self.seed)
        # Gumbel-max: argsort(skill + G) ~ Plackett-Luce com s=exp(skill)
        noise = rng.gumbel(size=(self.n_sims, len(names)))
        order = np.argsort(-(skill[None, :] + noise), axis=1)
        pos = np.empty_like(order)
        rows = np.arange(self.n_sims)[:, None]
        pos[rows, order] = np.arange(len(names))[None, :]

        out = {}
        for i, n in enumerate(names):
            p = pos[:, i]
            out[n] = {"win": round(float((p == 0).mean()), 4),
                      "podium": round(float((p < 3).mean()), 4),
                      "top6": round(float((p < 6).mean()), 4),
                      "elo": round(self.ratings[n], 1),
                      "team": self.drivers[n]["team"]}
        ranking = dict(sorted(out.items(), key=lambda kv: -kv[1]["win"]))
        return {"circuit": c["name"], "weather": weather,
                "n_drivers": len(names), "n_sims": self.n_sims,
                "ranking": ranking, "model": "elo-plackett-luce-fase0"}

    def predict_race_with_grid(self, circuit: str, grid: dict,
                               weather: str = "dry",
                               params_file: Path | str | None = None) -> dict:
        """Ranking PÓS-QUALI — Elo misturado ao grid de largada (Fase 2:
        H3-F1b COMPROVADA — RPS 0.1281 vs 0.1416 do Elo puro, DM p≈0).

        `grid`: {piloto: posição de largada (1..n); 0 = saiu do pit lane},
        um valor único por piloto entre os inscritos. O peso do blend e a
        calibração de Platt do P(pódio) vêm de `data/fase2_params.json`
        (vividos no backtest); sem o arquivo, cai no Elo puro da Fase 0
        (nenhuma feature nova aplicada sem ter sido comprovada)."""
        from .backtest import apply_platt, blend_elos, ladder  # lazy: evita ciclo

        c = resolve_circuit(circuit)
        if weather not in ("dry", "wet"):
            raise ValueError(f"weather desconhecido: {weather!r} (dry|wet)")
        entradas = [resolve_driver(n)["name"] for n in grid]
        if len(set(entradas)) != len(entradas):
            raise ValueError("piloto duplicado no grid (aliases que "
                             "resolvem para a mesma identidade)")
        pilotos = {resolve_driver(n)["name"]: int(p) for n, p in grid.items()}
        # position=0 ("saiu do pit lane") NÃO é única — múltiplos pilotos
        # podem largar do pit lane na mesma corrida (penalidades de grid);
        # o próprio blend abaixo já trata todo 0 como "última posição" (n+1),
        # então a validação não pode exigir unicidade para 0. Só posições
        # reais (>=1) precisam ser únicas.
        nonzero = [p for p in pilotos.values() if p != 0]
        if len(set(nonzero)) != len(nonzero):
            raise ValueError("posições de grid repetidas")
        names = list(pilotos)
        n = len(names)
        if n < 2:
            raise ValueError("grid precisa de pelo menos 2 pilotos")

        params = _load_fase2_params(params_file)
        elos_model = np.array([self.ratings[nm] for nm in names])
        if params["usar_blend"]:
            grid_raw = np.array([pilotos[nm] if pilotos[nm] > 0 else n + 1
                                 for nm in names], dtype=float)
            grid_rank = grid_raw.argsort(kind="stable").argsort()
            elos_grid = ladder(n)[grid_rank]
            elos = blend_elos(elos_model, elos_grid, params["w_grid"])
            model_tag = "elo-grid-blend-fase2"
        else:
            elos = elos_model
            model_tag = "elo-plackett-luce-fase0"

        skill = elos * _LN10_400
        rng = np.random.default_rng(self.seed)
        noise = rng.gumbel(size=(self.n_sims, n))
        order = np.argsort(-(skill[None, :] + noise), axis=1)
        pos = np.empty_like(order)
        rows = np.arange(self.n_sims)[:, None]
        pos[rows, order] = np.arange(n)[None, :]

        out = {}
        for i, nm in enumerate(names):
            p = pos[:, i]
            podium_raw = float((p < 3).mean())
            if params["usar_calibracao"]:
                podium = float(apply_platt(np.array([podium_raw]),
                                           params["platt_a"],
                                           params["platt_b"])[0])
            else:
                podium = podium_raw
            out[nm] = {"win": round(float((p == 0).mean()), 4),
                      "podium": round(podium, 4),
                      "top6": round(float((p < 6).mean()), 4),
                      "elo": round(self.ratings[nm], 1),
                      "grid": pilotos[nm],
                      "team": self.drivers[nm]["team"]}
        ranking = dict(sorted(out.items(), key=lambda kv: -kv[1]["win"]))
        return {"circuit": c["name"], "weather": weather,
                "n_drivers": n, "n_sims": self.n_sims, "ranking": ranking,
                "model": model_tag, "w_grid": params["w_grid"],
                "podium_calibrado": params["usar_calibracao"]}

    def predict_head_to_head(self, driver_a: str, driver_b: str,
                             circuit: str) -> dict:
        """P(A termina à frente de B) — fórmula fechada; consistente com a
        marginal do Plackett-Luce usado no predict_race."""
        a = resolve_driver(driver_a)["name"]
        b = resolve_driver(driver_b)["name"]
        if a == b:
            raise ValueError("um piloto não disputa consigo mesmo")
        c = resolve_circuit(circuit)
        p = win_probability(self.ratings[a], self.ratings[b])
        return {"driver_a": a, "driver_b": b, "circuit": c["name"],
                "prob_a_beats_b": round(p, 4),
                "prob_b_beats_a": round(1.0 - p, 4),
                "elo_a": round(self.ratings[a], 1),
                "elo_b": round(self.ratings[b], 1),
                "model": "elo-h2h-fase0"}

    def update_ratings(self, race_results: dict) -> dict:
        """race_results: {nome: posição final (1..n)}. Atualização PAREADA:
        para cada par (i,j), S=1 se i chegou à frente; K do par = média dos
        K individuais (novato anda mais rápido), dividido por (n-1).
        DNFs/ausentes: quem não está no dict não pontua nem perde."""
        nomes = [resolve_driver(n)["name"] for n in race_results]
        if len(set(nomes)) != len(nomes):
            raise ValueError("piloto duplicado no resultado (aliases que "
                             "resolvem para a mesma identidade)")
        pos = {resolve_driver(n)["name"]: int(p)
               for n, p in race_results.items()}
        if any(p < 1 for p in pos.values()):
            raise ValueError("posição final inválida (< 1) no resultado")
        if len(set(pos.values())) != len(pos):
            raise ValueError("posições repetidas no resultado")
        n = len(nomes)
        if n < 2:
            raise ValueError("resultado precisa de pelo menos 2 pilotos")
        delta = {m: 0.0 for m in nomes}
        for i in range(n):
            for j in range(i + 1, n):
                a, b = nomes[i], nomes[j]
                s_a = 1.0 if pos[a] < pos[b] else 0.0
                e_a = win_probability(self.ratings[a], self.ratings[b])
                k = (self._k(a) + self._k(b)) / 2.0 / (n - 1)
                d = k * (s_a - e_a)
                delta[a] += d
                delta[b] -= d
        for m in nomes:
            self.ratings[m] += delta[m]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({k: round(v, 2) for k, v in self.ratings.items()},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {m: round(delta[m], 2) for m in sorted(nomes, key=pos.get)}
