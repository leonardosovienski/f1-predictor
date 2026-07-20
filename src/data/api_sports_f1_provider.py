"""API-Sports Formula 1 adapter for controlled historical expansion.

The free subscription currently exposes seasons 2022--2024.  Data from this
adapter is opt-in, read-only, and shadow-only until reconciled with Jolpica.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
from typing import Any, Callable
from urllib.parse import urlencode
import urllib.request

from ..config import ROOT as _ROOT  # noqa: F401  (activate vendored core)
from predictor_core.data.contracts import DataUnavailableError

BASE = "https://v1.formula-1.api-sports.io"
FREE_SEASONS = frozenset({2022, 2023, 2024})


class ApiSportsF1Provider:
    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0,
                 get_json: Callable[[str, dict[str, str]], Any] | None = None,
                 request_interval: float = 6.1,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep):
        self.api_key = api_key or os.environ.get("API_SPORTS_F1_KEY") \
            or os.environ.get("API_FOOTBALL_KEY")
        self.timeout = timeout
        self._get_json = get_json or self._http_get_json
        self.request_interval = max(0.0, request_interval)
        self._clock, self._sleeper, self._last_request = clock, sleeper, None

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise DataUnavailableError(
                "API_SPORTS_F1_KEY ausente (API_FOOTBALL_KEY também é aceita)")
        return {
            "x-apisports-key": self.api_key,
            "User-Agent": "f1-predictor-source-audit/1.0",
        }

    def _http_get_json(self, url: str, headers: dict[str, str]) -> Any:
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (OSError, ValueError) as exc:
            raise DataUnavailableError(f"API-Sports F1 indisponível: {exc}") from exc

    def _request(self, path: str, params: dict[str, Any]) -> list[Any]:
        if self._last_request is not None:
            remaining = self.request_interval - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleeper(remaining)
        self._last_request = self._clock()
        payload = self._get_json(f"{BASE}/{path}?{urlencode(params)}", self._headers())
        if not isinstance(payload, dict):
            raise DataUnavailableError("API-Sports F1 retornou payload inválido")
        errors = payload.get("errors")
        if errors:
            detail = "; ".join(f"{key}: {value}" for key, value in errors.items()) \
                if isinstance(errors, dict) else str(errors)
            raise DataUnavailableError(f"API-Sports F1 recusou a consulta: {detail}")
        rows = payload.get("response")
        if not isinstance(rows, list):
            raise DataUnavailableError("API-Sports F1 retornou resposta inválida")
        return rows

    @staticmethod
    def _require_free_season(season: int) -> None:
        if season not in FREE_SEASONS:
            raise DataUnavailableError(
                f"temporada {season} fora da janela grátis da API-Sports F1 (2022-2024)")

    def list_races(self, *, season: int,
                   observed_at: datetime | None = None) -> list[dict[str, Any]]:
        self._require_free_season(season)
        observed = observed_at or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at deve conter timezone")
        observed = observed.astimezone(timezone.utc)
        raw_rows = self._request("races", {"season": season, "type": "Race"})
        rows = []
        for item in raw_rows:
            competition = item.get("competition") or {}
            circuit = item.get("circuit") or {}
            try:
                start = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
                event_id = str(item["id"])
                if start.tzinfo is None or not competition.get("name"):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({
                "source": "api_sports_f1", "source_event_id": event_id,
                "season": season, "grand_prix": competition["name"],
                "country": (competition.get("location") or {}).get("country"),
                "circuit": circuit.get("name"),
                "scheduled_start_utc": start.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "observed_at": observed.isoformat(timespec="seconds"),
                "status": item.get("status"), "laps": (item.get("laps") or {}).get("total"),
                "shadow_only": True,
            })
        return sorted(rows, key=lambda row: (row["scheduled_start_utc"], row["source_event_id"]))

    def race_results(self, *, race_id: int) -> list[dict[str, Any]]:
        raw_rows = self._request("rankings/races", {"race": int(race_id)})
        rows = []
        for item in raw_rows:
            driver = item.get("driver") or {}
            team = item.get("team") or {}
            if item.get("position") is None or not driver.get("name"):
                continue
            rows.append({
                "source": "api_sports_f1", "source_event_id": str(race_id),
                "driver_source_id": driver.get("id"), "driver": driver["name"],
                "driver_code": driver.get("abbr"), "team": team.get("name"),
                "position": int(item["position"]), "grid": item.get("grid"),
                "laps": item.get("laps"), "pits": item.get("pits"),
                "elapsed_or_gap": item.get("time"), "shadow_only": True,
            })
        return sorted(rows, key=lambda row: row["position"])
