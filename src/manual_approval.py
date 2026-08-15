"""Aprovação humana local para o registro de uma ordem já elegível.

Isto não integra casa de apostas nem envia ordens.  O arquivo de aprovação é
um artefato auditável, de uso único para uma intenção específica de aposta.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


def bet_fingerprint(*, market: str, selection: str, prob_model: float,
                    decimal_odds: float, bankroll: float, **_: Any) -> str:
    payload = {"market": market, "selection": selection,
               "prob_model": round(float(prob_model), 8),
               "decimal_odds": round(float(decimal_odds), 8),
               "bankroll": round(float(bankroll), 2)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_manual_approval(path: str | Path | None, *, fingerprint: str,
                            now: datetime | None = None) -> dict[str, Any]:
    if path is None:
        raise PermissionError("aposta real exige arquivo de aprovação manual")
    artifact = Path(path)
    if not artifact.is_file():
        raise PermissionError("arquivo de aprovação manual ausente")
    try:
        approval = json.loads(artifact.read_text(encoding="utf-8"))
        approved_at = datetime.fromisoformat(approval["approved_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PermissionError("arquivo de aprovação manual inválido") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        # Sem isto, um `now` ingênuo comparado a approved_at/expires_at (ambos
        # já validados como timezone-aware) levanta TypeError sem ser
        # capturado aqui — quebra a garantia de "sempre PermissionError,
        # nunca uma exceção solta" que record_bet/operate.py dependem para
        # tratar aposta real recusada de forma limpa.
        raise PermissionError("aprovação manual: 'now' precisa ser timezone-aware")
    if (approval.get("schema_version") != 1 or approval.get("status") != "APPROVED"
            or not isinstance(approval.get("approval_id"), str)
            or not approval["approval_id"].strip()
            or not isinstance(approval.get("approved_by"), str)
            or not approval["approved_by"].strip()
            or approval.get("bet_fingerprint") != fingerprint
            or approved_at.tzinfo is None or expires_at.tzinfo is None
            or approved_at > current or expires_at <= current):
        raise PermissionError("aprovação manual não é válida para esta ordem")
    return {"approval_id": approval["approval_id"],
            "approved_by": approval["approved_by"],
            "approved_at": approval["approved_at"], "expires_at": approval["expires_at"]}
