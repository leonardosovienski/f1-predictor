"""SQLite do histórico de F1 — padrão db.py da plataforma (WAL; leitura
sempre read-only via URI mode=ro).

Tabelas:
  races     (season, round, name, circuit, date)          PK (season, round)
  results   (season, round, driver_id, driver, constructor,
             grid, position, status, dnf, points)          PK (season, round, driver_id)
  pitstops  (season, round, driver_id, lap, stop, duration_s)
                                                            PK (season, round, driver_id, stop)

`build_db` ingere via provider (cache local primeiro — rede só no miss) e é
idempotente: INSERT OR REPLACE por corrida. Corridas futuras (sem resultado)
ficam só em `races`. Pitstops é best-effort: cobertura da Jolpica para essa
tabela é mais recente que a de `results` — corrida sem pitstop registrado
simplesmente não aparece na tabela (não é erro).
"""
import sqlite3
from datetime import date
from pathlib import Path

from ..config import ROOT

DB_PATH = ROOT / "data" / "f1.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
    season  INTEGER NOT NULL,
    round   INTEGER NOT NULL,
    name    TEXT    NOT NULL,
    circuit TEXT    NOT NULL,
    date    TEXT    NOT NULL,
    PRIMARY KEY (season, round)
);
CREATE TABLE IF NOT EXISTS results (
    season      INTEGER NOT NULL,
    round       INTEGER NOT NULL,
    driver_id   TEXT    NOT NULL,
    driver      TEXT    NOT NULL,
    constructor TEXT    NOT NULL,
    grid        INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    status      TEXT    NOT NULL,
    dnf         INTEGER NOT NULL,
    points      REAL    NOT NULL,
    PRIMARY KEY (season, round, driver_id)
);
CREATE TABLE IF NOT EXISTS pitstops (
    season      INTEGER NOT NULL,
    round       INTEGER NOT NULL,
    driver_id   TEXT    NOT NULL,
    lap         INTEGER NOT NULL,
    stop        INTEGER NOT NULL,
    duration_s  REAL    NOT NULL,
    PRIMARY KEY (season, round, driver_id, stop)
);
"""


def connect(path: Path | str | None = None, readonly: bool = True) -> sqlite3.Connection:
    """Read-only por default (P12): quem lê nunca segura lock de escrita."""
    p = Path(path or DB_PATH)
    if readonly:
        return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def build_db(provider, seasons: list[int], path: Path | str | None = None) -> dict:
    """Ingere calendário + resultados das temporadas. Retorna contagens."""
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(p, readonly=False)
    conn.executescript(_SCHEMA)
    n_races = n_results = n_pitstops = 0
    hoje = date.today().isoformat()
    try:
        for season in seasons:
            for race in provider.fetch_schedule(season):
                conn.execute(
                    "INSERT OR REPLACE INTO races VALUES (?,?,?,?,?)",
                    (race["season"], race["round"], race["name"],
                     race["circuit"], race["date"]))
                if race["date"] >= hoje:      # ainda não correu — só agenda
                    n_races += 1
                    continue
                rows = provider.fetch_results(season, race["round"])
                for r in rows:
                    conn.execute(
                        "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (r["season"], r["round"], r["driver_id"], r["driver"],
                         r["constructor"], r["grid"], r["position"],
                         r["status"], int(r["dnf"]), r["points"]))
                n_races += 1
                n_results += len(rows)
                if hasattr(provider, "fetch_pitstops"):
                    pits = provider.fetch_pitstops(season, race["round"])
                    for ps in pits:
                        conn.execute(
                            "INSERT OR REPLACE INTO pitstops VALUES (?,?,?,?,?,?)",
                            (ps["season"], ps["round"], ps["driver_id"],
                             ps["lap"], ps["stop"], ps["duration_s"]))
                    n_pitstops += len(pits)
            conn.commit()
    finally:
        conn.close()
    return {"races": n_races, "results": n_results, "pitstops": n_pitstops,
           "path": str(p)}


def load_races_with_results(path: Path | str | None = None) -> list[dict]:
    """Corridas COM resultado, em ordem cronológica (season, round) — a
    sequência prequential. Cada item: {season, round, name, circuit, date,
    results: [{driver, constructor, grid, position, status, dnf, points}]}."""
    conn = connect(path)
    try:
        conn.row_factory = sqlite3.Row
        races = conn.execute(
            "SELECT DISTINCT r.season, r.round, r.name, r.circuit, r.date "
            "FROM races r JOIN results x ON x.season=r.season AND x.round=r.round "
            "ORDER BY r.season, r.round").fetchall()
        out = []
        for rc in races:
            rows = conn.execute(
                "SELECT driver_id, driver, constructor, grid, position, status, "
                "dnf, points FROM results WHERE season=? AND round=? "
                "ORDER BY position", (rc["season"], rc["round"])).fetchall()
            out.append({**dict(rc), "results": [dict(r) for r in rows]})
        return out
    finally:
        conn.close()


def load_pitstops_by_race(path: Path | str | None = None) -> dict:
    """{(season, round): [{driver_id, lap, stop, duration_s}, ...]} — chave
    para juntar com `load_races_with_results` sem duplicar leitura."""
    conn = connect(path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT season, round, driver_id, lap, stop, duration_s "
            "FROM pitstops ORDER BY season, round, driver_id, stop").fetchall()
        out: dict = {}
        for r in rows:
            out.setdefault((r["season"], r["round"]), []).append(dict(r))
        return out
    finally:
        conn.close()
