#!/usr/bin/env python3
"""Gera artefatos operacionais SINTÉTICOS para a suíte rodar num clone limpo.

`data/f1.db` e `data/ratings.json` nascem do pipeline de ingestão e estão no
`.gitignore` (`*.db`). Num runner de CI eles nunca existem, e 11 dos 14 testes
de `tests/test_snapshots.py` dependem deles — historicamente isso era "resolvido"
com `|| true` no workflow, que forçava exit 0 e apagava junto qualquer regressão
real do resto da suíte.

Este script cria um substrato DETERMINÍSTICO com a mesma forma do real, montado
a partir do que JÁ é versionado (`data/drivers_f1.json`, `data/circuits_f1.json`),
para que aqueles testes voltem a rodar de verdade em CI em vez de só pular.

REGRA DE SEGURANÇA: nunca sobrescreve arquivo existente. Na máquina do operador
o `f1.db` real é dado de ingestão — perdê-lo por rodar um script de teste seria
inaceitável. Sem `--force`, um arquivo já presente é preservado e reportado.

Uso:
    python scripts/seed_test_fixtures.py           # cria só o que falta
    python scripts/seed_test_fixtures.py --force   # recria (destrutivo)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "f1.db"
RATINGS_PATH = ROOT / "data" / "ratings.json"
FASE2_PATH = ROOT / "data" / "fase2_params.json"

SEASON = 2026
# Rodadas 1..COMPLETED têm resultado; as seguintes ficam só em `races` — é
# assim que `_next_open_round()` acha uma corrida futura para o snapshot
# pré-evento. Com todas liquidadas, aquele fixture não teria o que testar.
COMPLETED_ROUNDS = 11
RACE_INTERVAL_DAYS = 14
# A primeira rodada ABERTA fica este tanto de dias no futuro, contado da
# geração. O calendário é ancorado em "hoje" de propósito: uma data fixa
# apodreceria (o próprio `_next_open_round` carrega o comentário de que um
# round hardcoded quebrou 7 testes no dia seguinte a um GP). Além disso os
# testes geram o snapshot com `now = início - 1 dia` e carimbam o grid com um
# `source_retrieved_at_utc` fixo no passado — se a corrida aberta não estivesse
# à frente, o snapshot seria recusado por "retrieved posterior à geração".
DAYS_UNTIL_FIRST_OPEN_RACE = 21

_SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
    season  INTEGER NOT NULL, round INTEGER NOT NULL, name TEXT NOT NULL,
    circuit TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY (season, round));
CREATE TABLE IF NOT EXISTS results (
    season INTEGER NOT NULL, round INTEGER NOT NULL, driver_id TEXT NOT NULL,
    driver TEXT NOT NULL, constructor TEXT NOT NULL, grid INTEGER NOT NULL,
    position INTEGER NOT NULL, status TEXT NOT NULL, dnf INTEGER NOT NULL,
    points REAL NOT NULL, PRIMARY KEY (season, round, driver_id));
CREATE TABLE IF NOT EXISTS pitstops (
    season INTEGER NOT NULL, round INTEGER NOT NULL, driver_id TEXT NOT NULL,
    lap INTEGER NOT NULL, stop INTEGER NOT NULL, duration_s REAL NOT NULL,
    PRIMARY KEY (season, round, driver_id, stop));
"""

_POINTS = {1: 25.0, 2: 18.0, 3: 15.0, 4: 12.0, 5: 10.0,
           6: 8.0, 7: 6.0, 8: 4.0, 9: 2.0, 10: 1.0}

# O nome oficial de um GP é o GENTÍLICO do país ("Australian Grand Prix"), não o
# país cru. Isso não é cosmético: `event_id` deriva do nome, e o caminho do
# snapshot sai dele — `tests/test_snapshots.py::_manual_pre` grava usando
# "Australian Grand Prix" e a maturação relê o nome do BANCO. Um "Australia
# Grand Prix" aqui geraria caminhos diferentes e a maturação não acharia o
# PRE_EVENT. Países sem entrada caem no próprio nome, que é suficiente para as
# rodadas que nenhum teste referencia pelo nome.
_DEMONYM = {
    "Australia": "Australian", "China": "Chinese", "Japan": "Japanese",
    "USA": "United States", "Canada": "Canadian", "Monaco": "Monaco",
    "Spain": "Spanish", "Austria": "Austrian", "UK": "British",
    "Belgium": "Belgian", "Hungary": "Hungarian", "Netherlands": "Dutch",
    "Italy": "Italian", "Azerbaijan": "Azerbaijan", "Singapore": "Singapore",
    "Mexico": "Mexico City", "Brazil": "São Paulo", "Qatar": "Qatar",
    "UAE": "Abu Dhabi",
}


def _driver_id(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _load(path: Path, key: str) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))[key]


def _race_date(round_: int, today: date | None = None) -> str:
    """Data da rodada, ancorada na primeira corrida ABERTA (COMPLETED+1)."""
    anchor = (today or date.today()) + timedelta(days=DAYS_UNTIL_FIRST_OPEN_RACE)
    delta = RACE_INTERVAL_DAYS * (round_ - (COMPLETED_ROUNDS + 1))
    return (anchor + timedelta(days=delta)).isoformat()


def _finishing_order(drivers: list[dict], round_: int) -> list[dict]:
    """Ordem de chegada determinística: rotaciona o grid pelo número da rodada.

    Sem aleatoriedade — o mesmo round produz sempre o mesmo resultado, senão os
    testes de determinismo de snapshot perderiam o sentido.
    """
    n = len(drivers)
    return [drivers[(index + round_) % n] for index in range(n)]


def build_database(path: Path) -> None:
    drivers = _load(ROOT / "data" / "drivers_f1.json", "drivers")
    circuits = _load(ROOT / "data" / "circuits_f1.json", "circuits")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        for circuit in circuits:
            round_ = int(circuit["round"])
            conn.execute(
                "INSERT OR REPLACE INTO races VALUES (?,?,?,?,?)",
                (SEASON, round_,
                 f"{_DEMONYM.get(circuit['country'], circuit['country'])} Grand Prix",
                 circuit["name"], _race_date(round_)))
        for round_ in range(1, COMPLETED_ROUNDS + 1):
            for position, driver in enumerate(_finishing_order(drivers, round_), start=1):
                # DNF só fora da zona de pontos, para não criar a combinação
                # incoerente "abandonou e pontuou".
                dnf = 1 if position > len(drivers) - 2 else 0
                conn.execute(
                    "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (SEASON, round_, _driver_id(driver["name"]), driver["name"],
                     driver["team"], position, position,
                     "Retired" if dnf else "Finished", dnf,
                     0.0 if dnf else _POINTS.get(position, 0.0)))
        conn.commit()
    finally:
        conn.close()


def build_ratings(path: Path) -> None:
    drivers = _load(ROOT / "data" / "drivers_f1.json", "drivers")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({d["name"]: float(d["initial_elo"]) for d in drivers},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def build_fase2_params(path: Path) -> None:
    """Escreve os DEFAULTS da Fase 2 (`model._FASE2_DEFAULTS`).

    O modelo tolera o arquivo ausente e cai nesses mesmos defaults, mas
    `snapshots.create_pre_event_snapshot` exige que ele exista para carimbar o
    hash na proveniência — o snapshot fixa TODA entrada. Semear com o default
    é neutro: `usar_blend`/`usar_calibracao` em False mantêm o Elo puro da
    Fase 0, sem ligar nenhuma feature que não foi comprovada.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"w_grid": 0.0, "platt_a": 1.0, "platt_b": 0.0,
                    "usar_blend": False, "usar_calibracao": False},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="recria mesmo se o arquivo já existir (DESTRUTIVO)")
    args = parser.parse_args(argv)

    for path, build in ((DB_PATH, build_database), (RATINGS_PATH, build_ratings),
                        (FASE2_PATH, build_fase2_params)):
        if path.exists() and not args.force:
            print(f"preservado (já existe): {path.relative_to(ROOT)}")
            continue
        build(path)
        print(f"gerado: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
