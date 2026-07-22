"""Point-in-time metadata contract for optional FastF1 exploration only."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class FastF1ContractError(ValueError):
    pass


def _utc(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise FastF1ContractError(f"{name} inválido") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FastF1ContractError(f"{name} exige timezone")
    return parsed.astimezone(timezone.utc)


def validate_fastf1_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    required = {"downloaded_at", "cache_version", "fastf1_version", "event", "session",
                "session_start_at", "cutoff_at", "source_last_modified", "laps_excluded",
                "compounds", "stints", "track_conditions", "weather_available_at",
                "penalties_available_at", "corrections"}
    missing = sorted(required - set(record))
    if missing:
        raise FastF1ContractError(f"campos FastF1 ausentes: {missing}")
    session_start, cutoff = _utc(record["session_start_at"], "session_start_at"), _utc(record["cutoff_at"], "cutoff_at")
    downloaded = _utc(record["downloaded_at"], "downloaded_at")
    if cutoff > downloaded:
        raise FastF1ContractError("cutoff posterior ao download cria lookahead")
    for field in ("weather_available_at", "penalties_available_at"):
        if _utc(record[field], field) > cutoff:
            raise FastF1ContractError(f"{field} posterior ao cutoff")
    if record["session"] not in {"FP1", "FP2", "FP3", "Q", "R", "S"}:
        raise FastF1ContractError("sessão FastF1 inválida")
    if not isinstance(record["laps_excluded"], list) or not isinstance(record["corrections"], list):
        raise FastF1ContractError("laps_excluded/corrections devem ser listas")
    out = {**record, "session_start_at": session_start.isoformat(), "cutoff_at": cutoff.isoformat(),
           "downloaded_at": downloaded.isoformat(), "fuel_load": "latent_not_observed"}
    out["provenance_hash"] = hashlib.sha256(json.dumps(out, sort_keys=True, ensure_ascii=False,
                                                         separators=(",", ":")).encode()).hexdigest()
    return out
