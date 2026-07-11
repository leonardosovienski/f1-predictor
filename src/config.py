"""Configuração do f1-predictor — carrega config.yaml e resolve paths.

Mesmo padrão dos demais consumidores: YAML na raiz é a única fonte de
parâmetros; vendor/ entra no sys.path aqui.
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_VENDOR = ROOT / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_drivers() -> list[dict]:
    """Grid 2026 real (22 pilotos / 11 equipes) de data/drivers_f1.json."""
    cfg = load_config()
    path = ROOT / cfg.get("drivers_file", "data/drivers_f1.json")
    return json.loads(path.read_text(encoding="utf-8"))["drivers"]


@lru_cache(maxsize=1)
def load_circuits() -> list[dict]:
    """Calendário 2026 real com características (metadados da Fase 1+)."""
    cfg = load_config()
    path = ROOT / cfg.get("circuits_file", "data/circuits_f1.json")
    return json.loads(path.read_text(encoding="utf-8"))["circuits"]


def clear_caches() -> None:
    load_config.cache_clear()
    load_drivers.cache_clear()
    load_circuits.cache_clear()


def _resolve(name: str, pool: list[dict], rotulo: str) -> dict:
    low = name.strip().lower()
    for t in pool:
        if t["name"].lower() == low:
            return t
    hits = [t for t in pool if low in t["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    sugestao = [t["name"] for t in hits]
    raise ValueError(f"{rotulo} desconhecido: {name!r}"
                     + (f" — você quis dizer {sugestao}?" if sugestao else ""))


def resolve_driver(name: str) -> dict:
    """Nome oficial ou substring única ('Verstappen') → registro do piloto."""
    return _resolve(name, load_drivers(), "piloto")


def resolve_circuit(name: str) -> dict:
    """Nome oficial ou substring única ('Monza') → registro do circuito."""
    return _resolve(name, load_circuits(), "circuito")
