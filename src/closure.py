"""Fail-closed human closure record for retired F1 research tracks."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

CLOSURE_FILE = "authorized_closure.json"


class ResearchClosedError(RuntimeError):
    """A human-closed research track cannot run without a new audit decision."""


def closure_path(root: Path | str = ROOT) -> Path:
    return Path(root) / "data" / CLOSURE_FILE


def require_open(track: str, *, root: Path | str = ROOT) -> None:
    """Reject H8/H2H execution once the immutable human decision exists."""
    path = closure_path(root)
    if not path.is_file():
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResearchClosedError(f"closure record unreadable: {path}") from exc
    status = record.get("tracks", {}).get(track)
    if status == "CLOSED_BY_HUMAN_DECISION":
        raise ResearchClosedError(
            f"{track} is CLOSED_BY_HUMAN_DECISION; a new explicit, auditable "
            "human decision is required before reopening")


def require_real_money_allowed(*, root: Path | str = ROOT) -> None:
    """The authorized closure blocks real-money operation independently of H1."""
    path = closure_path(root)
    if not path.is_file():
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResearchClosedError(f"closure record unreadable: {path}") from exc
    if record.get("real_money_operation") == "PERMANENTLY_BLOCKED":
        raise PermissionError(
            "real-money operation is PERMANENTLY_BLOCKED by human closure; "
            "a new explicit, auditable human decision is required")
