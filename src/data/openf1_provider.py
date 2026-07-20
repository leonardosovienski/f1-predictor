"""OpenF1 secondary source for read-only coverage audits.

This adapter never writes snapshots or feeds the model.  It exists to compare
session identity/timing with the canonical Jolpica path before any promotion.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable
import urllib.parse
import urllib.request

from ..config import ROOT as _ROOT  # noqa: F401  (activate vendored core)
from predictor_core.data.contracts import DataUnavailableError

BASE = "https://api.openf1.org/v1"


class OpenF1Provider:
    def __init__(self, *, timeout: float = 30.0,
                 get_json: Callable[[str], Any] | None = None):
        self.timeout = timeout
        self._get_json = get_json or self._http_get_json

    def _http_get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url, headers={"User-Agent": "f1-predictor-source-audit/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (OSError, ValueError) as exc:
            raise DataUnavailableError(f"OpenF1 indisponível: {exc}") from exc

    def list_race_sessions(self, year: int, *,
                           observed_at: datetime | None = None) -> list[dict[str, Any]]:
        observed = observed_at or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at deve conter timezone")
        observed = observed.astimezone(timezone.utc)
        query = urllib.parse.urlencode({"year": int(year), "session_name": "Race"})
        payload = self._get_json(f"{BASE}/sessions?{query}")
        if not isinstance(payload, list):
            raise DataUnavailableError("OpenF1 retornou lista de sessões inválida")
        rows = []
        for item in payload:
            try:
                start = datetime.fromisoformat(str(item["date_start"]).replace("Z", "+00:00"))
                if start.tzinfo is None:
                    raise ValueError
                session_key = int(item["session_key"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({
                "source": "openf1", "source_session_id": session_key,
                "meeting_key": item.get("meeting_key"),
                "name": item.get("meeting_name") or item.get("location"),
                "scheduled_start_utc": start.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "observed_at": observed.isoformat(timespec="seconds"),
                "shadow_only": True,
            })
        return sorted(rows, key=lambda row: row["scheduled_start_utc"])
