"""Fonte de dados de F1 — STUB da Fase 0 com a via da Fase 1 já validada.

Sondagem 2026-07-11: **Jolpica** (api.jolpi.ca — sucessor mantido do Ergast,
mesmo schema) responde sem chave: standings 2025 (semente do Elo), grid 2026
real (22 pilotos — Cadillac entrou) e calendário 2026 (22 corridas) vieram
de lá. A Fase 1 implementa fetch_results (ordem de chegada por corrida,
histórico para o backtest prequential ordinal com RPS do core); FastF1 fica
para telemetria fina (clima real, stints) se necessário.
"""
import os

from predictor_core.data.contracts import DataUnavailableError


class F1Provider:
    """Interface da fonte F1. Fase 0: fetch_* levanta DataUnavailableError —
    nenhum teste ou serving depende de rede sem perceber."""

    BASE_URL = "https://api.jolpi.ca/ergast/f1"

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.cache_dir = os.environ.get("FASTF1_CACHE_DIR")

    def health_check(self) -> bool:
        """Fase 0: sem rede no runtime — sempre False (a sondagem da criação
        foi manual e está documentada nos data/*.json)."""
        return False

    def fetch_results(self, season: int, round_: int | None = None) -> list[dict]:
        """Fase 1: ordem de chegada por corrida (backtest ordinal)."""
        raise DataUnavailableError(
            "F1Provider é stub na Fase 0 — implementar com Jolpica "
            f"({self.BASE_URL}/<season>/<round>/results.json) na Fase 1")

    def fetch_schedule(self, season: int) -> list[dict]:
        """Fase 1: calendário (largada real alimenta matures_at)."""
        raise DataUnavailableError("F1Provider é stub na Fase 0")
