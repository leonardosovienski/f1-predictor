"""Fatores contextuais — Fase 4. Três frentes emprestadas do ecossistema:

1. **Rating por CONTEXTO de circuito** (inspirado em CS/LoL: rating por
   mapa/campeão) — usa `predictor_core.kernel.rating.RatingBook` DE
   VERDADE (não workaround): um `RatingBook` por tipo de circuito
   (power/downforce/balanced, classificado a partir dos metadados
   qualitativos já declarados em `data/circuits_f1.json` desde a Fase 0).
   O rating por contexto entra no modelo como um DESVIO aditivo em Elo
   sobre o rating global — "quanto esse piloto rende NESSE tipo de
   circuito, além/aquém da força geral dele".

2. **Reliability e Pit Efficiency** (inspirado no "Four Factors" do
   basquete: decompor a força em componentes isolados em vez de um rating
   único). F1 tem dado real para dois: taxa de DNF por piloto (rolling,
   prequential) e duração média de pit stop por equipe (rolling,
   prequential, via `data/f1.db.pitstops`). "Ritmo de quali" e "ritmo de
   corrida" já são cobertos pelo Elo+grid da Fase 2 — não duplicados aqui.

3. **Choque de volatilidade pós-patch** (CS/LoL: K temporariamente maior
   após um patch invalida parte do histórico). Mecanismo implementado e
   validado em harness SINTÉTICO; NÃO aplicado a dados reais — a Jolpica
   não tem calendário de atualizações aerodinâmicas, e inventar datas de
   upgrade violaria a regra de ouro do projeto ("nada inventado").
"""
from __future__ import annotations

from collections import defaultdict, deque

from . import config  # noqa: F401  (injeta vendor/ no sys.path)

from predictor_core.kernel.rating import RatingBook

# ---------- 1. rating por contexto de circuito ----------

CIRCUIT_TYPES = ("power", "downforce", "balanced")

# Apelidos: nome popular (usado em data/circuits_f1.json) que NÃO é
# substring do nome oficial longo da Jolpica — só o caso descoberto na
# ingestão real; não inventa mapeamento para o que não tem metadado.
_CIRCUIT_ALIASES = {"Autódromo José Carlos Pace": "Interlagos"}


def circuit_type(power_sensitivity: float, downforce_sensitivity: float,
                 threshold: float = 0.15) -> str:
    """Classifica um circuito em power/downforce/balanced a partir dos
    metadados qualitativos declarados na Fase 0 (não consumidos até
    aqui). Diferença > threshold decide o eixo; senão, balanced."""
    diff = power_sensitivity - downforce_sensitivity
    if diff > threshold:
        return "power"
    if diff < -threshold:
        return "downforce"
    return "balanced"


def match_circuit_metadata(jolpica_circuit_name: str,
                           catalog: list[dict]) -> dict | None:
    """Casa o nome oficial longo da Jolpica ('Autodromo Nazionale di
    Monza') com a entrada curta do catálogo declarado ('Monza') por
    substring; usa `_CIRCUIT_ALIASES` só para o caso que não bate por
    substring. None se o circuito não tem metadado declarado (calendário
    histórico tem venues fora do calendário 2026 — ex. Ímola, Bahrein,
    Jeddah, Paul Ricard — cobertura parcial, não erro)."""
    alias = _CIRCUIT_ALIASES.get(jolpica_circuit_name)
    name_low = (alias or jolpica_circuit_name).lower()
    hits = [c for c in catalog if c["name"].lower() in name_low]
    return hits[0] if len(hits) == 1 else None


class ContextRatingBook:
    """Um `predictor_core.kernel.rating.RatingBook` POR tipo de circuito
    (reuso direto do core, não reimplementação). `bonus(driver, type)` é o
    desvio do rating de contexto em relação ao `default_rating` — o que
    entra como ajuste aditivo no Elo global do modelo."""

    def __init__(self, default_rating: float = 1400.0, k: float = 24.0):
        self.default_rating = default_rating
        self.books = {t: RatingBook(default_rating=default_rating, k=k)
                     for t in CIRCUIT_TYPES}

    def bonus(self, driver: str, type_: str) -> float:
        return self.books[type_].rating(driver) - self.default_rating

    def update(self, type_: str, finish_order: list[str]) -> None:
        if len(finish_order) >= 2:
            self.books[type_].record_ranking(finish_order)


# ---------- 2. reliability e pit efficiency (rolling, prequential) ----------

class ReliabilityTracker:
    """Taxa de DNF rolling por PILOTO, janela de `window` corridas mais
    recentes — só usa corridas JÁ VISTAS (chamar `rate` ANTES de `update`
    na mesma corrida evita lookahead). Sem histórico: taxa default 0.10
    (base rate aproximado do grid — nem otimista nem punitivo)."""

    def __init__(self, window: int = 12, default_rate: float = 0.10):
        self.window = window
        self.default_rate = default_rate
        self._history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=window))

    def rate(self, driver: str) -> float:
        h = self._history.get(driver)
        if not h:
            return self.default_rate
        return sum(h) / len(h)

    def update(self, driver: str, dnf: bool) -> None:
        self._history[driver].append(1.0 if dnf else 0.0)


class PitEfficiencyTracker:
    """Duração média de pit stop rolling por EQUIPE (habilidade de boxe é
    do time, não do piloto), em desvio-padrão (z-score) relativo à
    dispersão HISTÓRICA entre equipes — NUNCA a dispersão da corrida
    corrente (isso seria lookahead: a parada acontece DURANTE a corrida,
    diferente do grid que é conhecido ANTES da largada). `z()` só usa
    observações estritamente anteriores; sem histórico, z=0 (neutro)."""

    def __init__(self, window: int = 10, field_window: int = 60):
        self.window = window
        self._history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=window))
        self._field: deque = deque(maxlen=field_window)   # médias por (equipe, corrida) passadas

    def z(self, constructor: str) -> float:
        h = self._history.get(constructor)
        if not h or len(self._field) < 2:
            return 0.0
        avg = sum(h) / len(h)
        field_mean = sum(self._field) / len(self._field)
        var = sum((x - field_mean) ** 2 for x in self._field) / (len(self._field) - 1)
        field_std = var ** 0.5
        if field_std <= 0:
            return 0.0
        return (avg - field_mean) / field_std

    def update(self, constructor: str, race_avg_duration: float) -> None:
        self._history[constructor].append(race_avg_duration)
        self._field.append(race_avg_duration)


def race_pitstop_summary(pitstops: list[dict]) -> dict:
    """{constructor_or_driver_id: duração média na corrida} — a Jolpica dá
    pitstops por PILOTO; o chamador decide se agrega por equipe (via mapa
    driver_id->constructor da própria corrida)."""
    by_driver: dict[str, list[float]] = defaultdict(list)
    for p in pitstops:
        by_driver[p["driver_id"]].append(p["duration_s"])
    return {d: sum(v) / len(v) for d, v in by_driver.items()}


# ---------- 3. choque de volatilidade pós-patch (mecanismo; só sintético) ----------

class VolatilityShock:
    """Choque de K temporário — inspirado no "patch invalida histórico
    parcialmente" de CS/LoL. `trigger(name, races=N, multiplier=M)`: pelas
    próximas N atualizações de rating desse nome, o K efetivo é
    multiplicado por M (>1 = mais peso ao NOVO, "esquecendo" o rating
    anterior mais rápido). Decai sozinho — sem chamada extra por corrida.

    MECANISMO VALIDADO SÓ EM SINTÉTICO (ver tests/test_context_factors.py)
    — sem calendário real de upgrades aerodinâmicos, NÃO é acionado nos
    backtests/serving reais desta fase."""

    def __init__(self):
        self._remaining: dict[str, tuple] = {}   # name -> (races_left, multiplier)

    def trigger(self, name: str, races: int, multiplier: float) -> None:
        if races <= 0 or multiplier <= 0:
            raise ValueError("races e multiplier precisam ser positivos")
        self._remaining[name] = (races, multiplier)

    def k_multiplier(self, name: str) -> float:
        entry = self._remaining.get(name)
        return entry[1] if entry else 1.0

    def tick(self, name: str) -> None:
        """Chamar UMA vez por corrida em que `name` foi atualizado —
        decrementa o choque; remove quando esgotado."""
        entry = self._remaining.get(name)
        if not entry:
            return
        races_left, multiplier = entry
        if races_left <= 1:
            del self._remaining[name]
        else:
            self._remaining[name] = (races_left - 1, multiplier)
