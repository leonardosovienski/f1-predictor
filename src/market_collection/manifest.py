from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import BatchManifest


class ManifestError(ValueError):
    pass


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_verify_manifest(path: Path) -> tuple[BatchManifest, str, list[Path]]:
    manifest_path = path.resolve(strict=True)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = BatchManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ManifestError(f"invalid manifest: {exc}") from exc
    root = manifest_path.parent
    resolved: list[Path] = []
    for item in manifest.source_files:
        candidate = (root / item.path).resolve(strict=True)
        if not candidate.is_relative_to(root):
            raise ManifestError("source file escapes the batch directory")
        if candidate.stat().st_size != item.size_bytes:
            raise ManifestError(f"source size mismatch: {item.path}")
        if file_sha256(candidate).lower() != item.sha256.lower():
            raise ManifestError(f"source hash mismatch: {item.path}")
        resolved.append(candidate)
    return manifest, canonical_sha256(raw), resolved
