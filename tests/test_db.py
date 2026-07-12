"""SQLite f1.db — ingestão idempotente, corrida futura, ordem prequential."""
from src.data.db import build_db, connect, load_races_with_results


class FakeProvider:
    """Duas temporadas mínimas; a última corrida está no futuro."""

    def fetch_schedule(self, season):
        if season == 2022:
            return [
                {"season": 2022, "round": 1, "name": "GP A",
                 "circuit": "A", "date": "2022-03-20"},
                {"season": 2022, "round": 2, "name": "GP B",
                 "circuit": "B", "date": "2022-03-27"},
            ]
        return [{"season": 2023, "round": 1, "name": "GP C",
                 "circuit": "C", "date": "2099-01-01"}]      # futura

    def fetch_results(self, season, round_):
        assert (season, round_) != (2023, 1), \
            "corrida futura não deve ser buscada"
        base = {"season": season, "round": round_, "constructor": "Eq",
                "status": "Finished", "dnf": False, "points": 1.0}
        return [
            {**base, "driver_id": "a", "driver": "Alice", "grid": 2, "position": 1},
            {**base, "driver_id": "b", "driver": "Bob", "grid": 1, "position": 2,
             "status": "Accident", "dnf": True},
        ]


def test_build_e_load(tmp_path):
    db = tmp_path / "f1.db"
    stats = build_db(FakeProvider(), [2022, 2023], path=db)
    assert stats["races"] == 3
    assert stats["results"] == 4                   # futura não tem resultado

    races = load_races_with_results(db)
    assert [(r["season"], r["round"]) for r in races] == [(2022, 1), (2022, 2)]
    rows = races[0]["results"]
    assert [r["position"] for r in rows] == [1, 2]        # ordem de chegada
    assert rows[1]["dnf"] == 1


def test_rebuild_idempotente(tmp_path):
    db = tmp_path / "f1.db"
    build_db(FakeProvider(), [2022], path=db)
    build_db(FakeProvider(), [2022], path=db)      # INSERT OR REPLACE
    conn = connect(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    finally:
        conn.close()
    assert n == 4


def test_leitura_read_only(tmp_path):
    db = tmp_path / "f1.db"
    build_db(FakeProvider(), [2022], path=db)
    conn = connect(db)                             # mode=ro
    try:
        import sqlite3
        try:
            conn.execute("DELETE FROM results")
            assert False, "conexão read-only aceitou escrita"
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()
