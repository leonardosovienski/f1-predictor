"""Isolated historical F1 storage with explicit anomaly accounting."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_races (
 season INTEGER NOT NULL, round INTEGER NOT NULL, name TEXT NOT NULL,
 circuit TEXT NOT NULL, race_date TEXT NOT NULL, source TEXT NOT NULL,
 shadow_only INTEGER NOT NULL CHECK(shadow_only=1), PRIMARY KEY(season,round));
CREATE TABLE IF NOT EXISTS shadow_results (
 season INTEGER NOT NULL, round INTEGER NOT NULL, driver_id TEXT NOT NULL,
 driver TEXT NOT NULL, constructor TEXT NOT NULL, grid INTEGER NOT NULL,
 position INTEGER NOT NULL, status TEXT NOT NULL, dnf INTEGER NOT NULL,
 points REAL NOT NULL, source TEXT NOT NULL,
 shadow_only INTEGER NOT NULL CHECK(shadow_only=1),
 PRIMARY KEY(season,round,driver_id));
CREATE TABLE IF NOT EXISTS anomalies (
 season INTEGER NOT NULL, round INTEGER NOT NULL, kind TEXT NOT NULL,
 detail TEXT NOT NULL, PRIMARY KEY(season,round,kind,detail));
"""


def connect_shadow(path: str | Path) -> sqlite3.Connection:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path); conn.executescript(SCHEMA); return conn


def ingest_season(conn: sqlite3.Connection, provider: Any, season: int) -> dict[str, int]:
    races = results = anomalies = 0
    for race in provider.fetch_schedule(season):
        rows = provider.fetch_results(season, race["round"])
        driver_ids: set[str] = set(); positions: set[int] = set()
        positive_grids: dict[int, list[str]] = {}
        for row in rows:
            driver_id, position = row.get("driver_id"), row.get("position")
            if not isinstance(driver_id, str) or not driver_id or driver_id in driver_ids:
                raise ValueError("driver_id ausente ou duplicado")
            if not isinstance(position, int) or isinstance(position, bool) \
                    or position < 1 or position in positions:
                raise ValueError("posição final inválida ou duplicada")
            grid = row.get("grid")
            if not isinstance(grid, int) or isinstance(grid, bool) or grid < 0:
                raise ValueError("grid inválido")
            if grid > 0:
                positive_grids.setdefault(grid, []).append(driver_id)
            driver_ids.add(driver_id); positions.add(position)
        conn.execute("INSERT OR REPLACE INTO shadow_races VALUES(?,?,?,?,?,'jolpica',1)",
                     (season, race["round"], race["name"], race["circuit"], race["date"]))
        for grid, drivers in positive_grids.items():
            if len(drivers) > 1:
                detail = f"grid={grid};drivers={','.join(sorted(drivers))}"
                conn.execute("INSERT OR IGNORE INTO anomalies VALUES(?,?,'duplicate_grid',?)",
                             (season, race["round"], detail)); anomalies += 1
        for row in rows:
            conn.execute("INSERT OR REPLACE INTO shadow_results VALUES(?,?,?,?,?,?,?,?,?,?,'jolpica',1)",
                         (season, race["round"], row["driver_id"], row["driver"],
                          row["constructor"], row["grid"], row["position"], row["status"],
                          int(row["dnf"]), float(row["points"])))
        races += 1; results += len(rows)
    conn.commit()
    return {"races": races, "results": results, "anomalies": anomalies}


def coverage_report(conn: sqlite3.Connection) -> dict[str, Any]:
    races, results = conn.execute(
        "SELECT (SELECT count(*) FROM shadow_races),(SELECT count(*) FROM shadow_results)").fetchone()
    seasons = dict(conn.execute("SELECT season,count(*) FROM shadow_races GROUP BY season ORDER BY season"))
    anomalies = conn.execute("SELECT count(*) FROM anomalies").fetchone()[0]
    incomplete = conn.execute("""
      SELECT count(*) FROM shadow_races r LEFT JOIN shadow_results x
      ON x.season=r.season AND x.round=r.round
      WHERE x.driver_id IS NULL
    """).fetchone()[0]
    return {"races": races, "results": results, "by_season": seasons,
            "anomalies": anomalies, "races_without_results": incomplete,
            "shadow_only": True}


def cross_source_report(api_races: list[dict[str, Any]], api_results: dict[str, list[dict[str, Any]]],
                        official: sqlite3.Connection, *, season: int) -> dict[str, int | bool]:
    official_races = {row[0]: (row[1], row[2]) for row in official.execute(
        "SELECT date,round,name FROM races WHERE season=?", (season,))}
    official_by_name = {}
    for official_date, (round_, name) in official_races.items():
        official_by_name.setdefault(name, []).append((official_date, round_))
    matched = unmatched = compared = position_conflicts = grid_conflicts = 0
    for race in api_races:
        event_date = race["scheduled_start_utc"][:10]
        current = official_races.get(event_date)
        if current is None:
            candidates = official_by_name.get(race.get("grand_prix"), [])
            close = [(d, rnd) for d, rnd in candidates
                     if abs((date.fromisoformat(d) - date.fromisoformat(event_date)).days) <= 1]
            if len(close) == 1:
                current = (close[0][1], race.get("grand_prix"))
        if current is None:
            unmatched += 1; continue
        matched += 1; round_ = current[0]
        official_rows = {row[0]: (row[1], row[2]) for row in official.execute(
            "SELECT driver,position,grid FROM results WHERE season=? AND round=?",
            (season, round_))}
        for result in api_results.get(race["source_event_id"], []):
            baseline = official_rows.get(result["driver"])
            if baseline is None:
                continue
            compared += 1
            position_conflicts += int(baseline[0] != result["position"])
            try: api_grid = int(result["grid"])
            except (TypeError, ValueError): api_grid = -1
            grid_conflicts += int(baseline[1] != api_grid)
    return {"matched_races": matched, "unmatched_races": unmatched,
            "compared_driver_results": compared,
            "position_conflicts": position_conflicts, "grid_conflicts": grid_conflicts,
            "audit_passed": bool(matched and not unmatched and not position_conflicts)}
