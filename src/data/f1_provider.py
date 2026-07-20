"""Fonte de dados de F1 — Jolpica (api.jolpi.ca, sucessor mantido do Ergast).

Fase 1: `fetch_results(season, round)` (ordem de chegada + grid + status) e
`fetch_schedule(season)` saem do stub. Sem chave. Cortesia com o projeto
comunitário: **1s entre chamadas de rede** e cache agressivo em `data/raw/`
— um JSON por corrida, IMUTÁVEL pós-corrida (cache hit nunca toca a rede).

Parsing devolve dicts planos (season, round, driver, constructor, grid,
position, status, points) — o formato que o db.py ingere. `is_dnf` é a
convenção declarada: status "Finished" ou "+N Lap(s)" = classificado;
qualquer outro (Accident, Engine, ...) = DNF.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..config import ROOT  # injeta vendor/ no sys.path antes do core
from predictor_core.data.contracts import DataUnavailableError

_USER_AGENT = "f1-predictor/0.1 (research; github: pessoal)"
_RATE_LIMIT_S = 1.0


def _parse_duration_s(raw: str) -> float | None:
    """Ergast/Jolpica formata duração de pit stop como segundos puros
    ('23.145') OU 'M:SS.sss' quando >= 60s (bandeira vermelha, drive-through
    contado como stop) — normaliza para float sempre em segundos. String
    vazia (lacuna de captura da fonte, ocorre em corridas antigas) → None,
    descartada pelo chamador em vez de quebrar a ingestão inteira."""
    if not raw:
        return None
    if ":" in raw:
        minutes, seconds = raw.split(":", 1)
        return int(minutes) * 60.0 + float(seconds)
    return float(raw)


def is_dnf(status: str) -> bool:
    """DNF = não classificado. Ergast/Jolpica: 'Finished', '+N Lap(s)'
    (convenção 2022) e 'Lapped' (convenção 2023+, MESMO conceito — piloto
    classificado, voltas atrás do líder) são classificados; todo o resto
    (Accident, Engine, Retired, Disqualified, Did not start...) é DNF."""
    return not (status == "Finished" or status == "Lapped"
               or status.startswith("+"))


class F1Provider:
    """Cliente Jolpica com cache local imutável por corrida."""

    BASE_URL = "https://api.jolpi.ca/ergast/f1"

    def __init__(self, timeout: float = 30.0, cache_dir: Path | str | None = None,
                 offline: bool = False):
        self.timeout = timeout
        self.cache_dir = Path(cache_dir if cache_dir is not None
                              else os.environ.get("F1_RAW_CACHE_DIR",
                                                  ROOT / "data" / "raw"))
        self.offline = offline
        self._last_call = 0.0

    # ---------- rede + cache ----------

    def _get(self, path: str, cache_name: str, *,
             cacheable=lambda data: True) -> dict:
        """Busca `path` na API com cache em `data/raw/<cache_name>.json`.
        Cache hit não toca a rede; miss respeita o rate limit de 1s e faz
        retry com backoff em 429/5xx (a Jolpica tem teto por hora além do
        burst). Só grava o cache se `cacheable(data)` — corrida futura
        (resultado vazio) não pode virar cache imutável."""
        cached = self.cache_dir / f"{cache_name}.json"
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        if self.offline:
            raise DataUnavailableError(
                f"offline e sem cache para {cache_name} ({cached})")
        url = f"{self.BASE_URL}/{path}"
        data = None
        for attempt in range(1, 5):
            wait = _RATE_LIMIT_S - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                self._last_call = time.monotonic()
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    retry_after = e.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after
                               else 15.0 * attempt)
                    continue
                raise DataUnavailableError(
                    f"Jolpica indisponível ({url}): {e}") from e
            except (OSError, ValueError) as e:
                raise DataUnavailableError(
                    f"Jolpica indisponível ({url}): {e}") from e
        self._last_call = time.monotonic()
        if cacheable(data):
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(data, ensure_ascii=False),
                              encoding="utf-8")
        return data

    def health_check(self) -> bool:
        try:
            return bool(self.fetch_schedule(2026))
        except DataUnavailableError:
            return False

    # ---------- endpoints ----------

    def fetch_schedule(self, season: int) -> list[dict]:
        """Calendário com instante oficial UTC quando publicado pela fonte."""
        data = self._get(f"{season}.json?limit=30", f"schedule_{season}")
        races = data["MRData"]["RaceTable"]["Races"]
        out = []
        for race in races:
            scheduled = None
            if race.get("time"):
                parsed = datetime.fromisoformat(
                    f"{race['date']}T{race['time']}".replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise DataUnavailableError("Jolpica publicou largada sem timezone")
                scheduled = parsed.astimezone(timezone.utc).isoformat(
                    timespec="seconds").replace("+00:00", "Z")
            out.append({"season": int(race["season"]),
                        "round": int(race["round"]),
                        "name": race["raceName"],
                        "circuit": race["Circuit"]["circuitName"],
                        "date": race["date"],
                        "scheduled_start_utc": scheduled,
                        "qualifying_start_utc": self._session_start(race.get("Qualifying"))})
        return out

    @staticmethod
    def _session_start(session: dict | None) -> str | None:
        if not session or not session.get("date") or not session.get("time"):
            return None
        parsed = datetime.fromisoformat(
            f"{session['date']}T{session['time']}".replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DataUnavailableError("Jolpica publicou sessão sem timezone")
        return parsed.astimezone(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")

    def fetch_results(self, season: int, round_: int) -> list[dict]:
        """Resultado de UMA corrida: lista por piloto com posição final
        (classificação oficial — DNFs entram ordenados por voltas), grid de
        largada (0 = saiu do pit lane), status e pontos. Vazia se a corrida
        ainda não aconteceu."""
        data = self._get(
            f"{season}/{round_}/results.json?limit=100",
            f"results_{season}_{round_:02d}",
            cacheable=lambda d: bool(d["MRData"]["RaceTable"]["Races"]))
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            return []
        out = []
        for res in races[0]["Results"]:
            drv = res["Driver"]
            out.append({
                "season": season, "round": round_,
                "driver_id": drv["driverId"],
                "driver": f"{drv['givenName']} {drv['familyName']}",
                "constructor": res["Constructor"]["name"],
                "grid": int(res["grid"]),
                "position": int(res["position"]),
                "status": res["status"],
                "dnf": is_dnf(res["status"]),
                "points": float(res.get("points", 0.0)),
            })
        return out

    def fetch_qualifying(self, season: int, round_: int) -> list[dict]:
        """Resultado do QUALI (grid de largada) de uma corrida, ANTES da
        corrida acontecer: [{driver, driver_id, constructor, position}]
        ordenado por posição de largada. Vazia se o quali ainda não
        aconteceu (imutável depois — sessão de classificação não é
        re-corrida). Fonte do `--grid` automático do serving pós-quali."""
        data = self._get(
            f"{season}/{round_}/qualifying.json?limit=100",
            f"qualifying_{season}_{round_:02d}",
            cacheable=lambda d: bool(d["MRData"]["RaceTable"]["Races"]))
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            return []
        out = []
        for q in races[0]["QualifyingResults"]:
            drv = q["Driver"]
            out.append({"season": season, "round": round_,
                       "driver_id": drv["driverId"],
                       "driver": f"{drv['givenName']} {drv['familyName']}",
                       "constructor": q["Constructor"]["name"],
                       "position": int(q["position"])})
        return out

    def fetch_pitstops(self, season: int, round_: int) -> list[dict]:
        """Paradas de UMA corrida: [{driver_id, lap, stop, duration_s}].
        Duração em segundos (float); vazia se a corrida ainda não
        aconteceu OU se a Jolpica não tem o dado para aquela temporada
        (cobertura de pitstops é mais recente que a de results)."""
        data = self._get(
            f"{season}/{round_}/pitstops.json?limit=100",
            f"pitstops_{season}_{round_:02d}",
            cacheable=lambda d: bool(d["MRData"]["RaceTable"]["Races"]))
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            return []
        out = []
        for p in races[0].get("PitStops", []):
            dur = _parse_duration_s(p.get("duration", ""))
            if dur is None:
                continue          # duração não capturada pela fonte — descarta o registro
            out.append({"season": season, "round": round_,
                       "driver_id": p["driverId"], "lap": int(p["lap"]),
                       "stop": int(p["stop"]), "duration_s": dur})
        return out
