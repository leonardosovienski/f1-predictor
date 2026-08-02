"""Scientific configuration and deployable runtime settings."""

import json
from functools import cache, lru_cache
from pathlib import Path

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGE_ROOT = Path(__file__).resolve().parent
ROOT = _PACKAGE_ROOT if (_PACKAGE_ROOT / "config.yaml").is_file() else _PACKAGE_ROOT.parent


class Settings(BaseSettings):
    """Operational configuration. Scientific parameters remain in config.yaml."""

    model_config = SettingsConfigDict(env_prefix="F1_", env_file=".env", extra="ignore")

    environment: str = "development"
    raw_cache_dir: Path = ROOT / "data" / "raw"
    snapshot_dir: Path = ROOT / "snapshots"
    archive_dir: Path = ROOT / "data" / "collection_only"
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'f1.db').as_posix()}"
    object_storage_url: str | None = None
    jolpica_base_url: str = "https://api.jolpi.ca/ergast/f1"
    jolpica_timeout_seconds: float = Field(default=30.0, gt=0)
    api_sports_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("F1_API_SPORTS_KEY", "API_SPORTS_F1_KEY", "API_FOOTBALL_KEY"),
    )
    predictions_log_path: Path | None = None
    bets_log_path: Path | None = None
    events_path: Path | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _root(root: Path | str | None) -> Path:
    return Path(root) if root is not None else ROOT


@cache
def load_config(root: Path | str | None = None) -> dict:
    with open(_root(root) / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@cache
def load_drivers(root: Path | str | None = None) -> list[dict]:
    """Grid 2026 real (22 pilotos / 11 equipes) de data/drivers_f1.json."""
    base = _root(root)
    cfg = load_config(base)
    path = base / cfg.get("drivers_file", "data/drivers_f1.json")
    return json.loads(path.read_text(encoding="utf-8"))["drivers"]


@cache
def load_circuits(root: Path | str | None = None) -> list[dict]:
    """Calendário 2026 real com características (metadados da Fase 1+)."""
    base = _root(root)
    cfg = load_config(base)
    path = base / cfg.get("circuits_file", "data/circuits_f1.json")
    return json.loads(path.read_text(encoding="utf-8"))["circuits"]


def clear_caches() -> None:
    load_config.cache_clear()
    load_drivers.cache_clear()
    load_circuits.cache_clear()
    get_settings.cache_clear()


def _resolve(name: str, pool: list[dict], rotulo: str) -> dict:
    low = name.strip().lower()
    for t in pool:
        if t["name"].lower() == low:
            return t
    hits = [t for t in pool if low in t["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    sugestao = [t["name"] for t in hits]
    raise ValueError(
        f"{rotulo} desconhecido: {name!r}" + (f" — você quis dizer {sugestao}?" if sugestao else "")
    )


def resolve_driver(name: str) -> dict:
    """Nome oficial ou substring única ('Verstappen') → registro do piloto."""
    return _resolve(name, load_drivers(), "piloto")


def resolve_circuit(name: str) -> dict:
    """Nome oficial ou substring única ('Monza') → registro do circuito."""
    return _resolve(name, load_circuits(), "circuito")
