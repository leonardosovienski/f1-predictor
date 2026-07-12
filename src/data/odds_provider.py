"""Fonte de odds — Fase 3. STUB até haver ODDS_API_KEY (mesmo padrão do
F1Provider da Fase 0/1: fetch_* levanta DataUnavailableError sem chave, e
nenhum teste ou serving depende de rede sem perceber).

Sondagem CONCLUÍDA em 2026-07-12: `/v4/sports` com chave real listou 57
esportes — **nenhum é F1/motorsport** (nem "motorsport_f1" nem qualquer
variante; o motorsport mais próximo ofertado nem existe, ao contrário de
boxe/MMA que têm mercado próprio). **A The Odds API NÃO cobre F1** — a
Fase 1b (odds reais) está encerrada por falta de fonte, não é mais
pendência em aberto. `fetch_h2h_odds` continua recusando por design.
"""
import os
import urllib.request
import json

from predictor_core.data.contracts import DataUnavailableError

_USER_AGENT = "f1-predictor/0.1 (research)"


class OddsProvider:
    """Cliente da The Odds API. Sem ODDS_API_KEY: todo fetch_* levanta
    DataUnavailableError — o mesmo contrato do F1Provider pré-Fase-1."""

    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self.api_key = os.environ.get("ODDS_API_KEY") or None

    def health_check(self) -> bool:
        return self.api_key is not None

    def list_sports(self) -> list[dict]:
        """/v4/sports — usar para CONFIRMAR se existe `motorsport_f1`
        antes de qualquer integração de odds real (pendência declarada)."""
        if not self.api_key:
            raise DataUnavailableError(
                "ODDS_API_KEY ausente — configure no .env para sondar "
                f"{self.BASE_URL}/sports")
        url = f"{self.BASE_URL}/sports/?apiKey={self.api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except (OSError, ValueError) as e:
            raise DataUnavailableError(f"The Odds API indisponível: {e}") from e

    def fetch_h2h_odds(self, sport_key: str = "motorsport_f1") -> list[dict]:
        """Odds de mercado H2H — SEMPRE recusa: a sondagem de 2026-07-12
        confirmou que a The Odds API não tem NENHUM mercado de F1 (nem
        `motorsport_f1` nem equivalente), então não há endpoint real para
        chamar aqui. Mantido como esqueleto caso a cobertura mude."""
        if not self.api_key:
            raise DataUnavailableError(
                "ODDS_API_KEY ausente — Fase 3 sem odds reais, só paper")
        raise DataUnavailableError(
            "The Odds API não cobre F1 (sondado em 2026-07-12: 57 "
            "esportes listados, nenhum de motorsport) — sem fonte de "
            "odds reais para esta Fase 3")
