"""Portable repository implementations; PostgreSQL/object storage are adapters."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .contracts import OperationalRepository, SourceEnvelope, TemporalKind


class FileSnapshotRepository:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        if not key or Path(key).is_absolute() or ".." in Path(key).parts:
            raise ValueError("invalid snapshot key")
        return self.root / key

    def put_if_absent(self, key: str, payload: bytes, sha256: str) -> bool:
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise ValueError("snapshot hash mismatch")
        destination = self._path(key)
        if destination.exists():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(dir=destination.parent, prefix=".snapshot-", suffix=".tmp")
        temporary = Path(raw)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None


class MemoryOperationalRepository(OperationalRepository):
    def __init__(self) -> None:
        self._items: list[SourceEnvelope] = []

    def save_envelope(self, envelope: SourceEnvelope) -> None:
        if any(item.payload_hash == envelope.payload_hash for item in self._items):
            return
        self._items.append(envelope)

    def latest(self, event_id: str, kind: TemporalKind) -> SourceEnvelope | None:
        matches = [item for item in self._items if item.event_id == event_id and item.kind == kind]
        return max(matches, key=lambda item: item.available_at) if matches else None
