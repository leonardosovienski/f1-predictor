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


def test_corrida_do_proprio_dia_e_ingerida(tmp_path):
    # Regressão: `date >= hoje` pulava a corrida do PRÓPRIO dia mesmo já
    # terminada — só ingeria no dia seguinte. Agora tenta buscar; se ainda
    # não correu, o provider devolve vazio (e não vira cache imutável).
    from datetime import date

    class HojeProvider:
        def __init__(self, com_resultado):
            self.com_resultado = com_resultado

        def fetch_schedule(self, season):
            return [{"season": 2026, "round": 1, "name": "GP Hoje",
                     "circuit": "H", "date": date.today().isoformat()}]

        def fetch_results(self, season, round_):
            if not self.com_resultado:
                return []                     # ainda não largou
            base = {"season": season, "round": round_, "constructor": "Eq",
                    "status": "Finished", "dnf": False, "points": 1.0}
            return [{**base, "driver_id": "a", "driver": "Alice",
                     "grid": 1, "position": 1},
                    {**base, "driver_id": "b", "driver": "Bob",
                     "grid": 2, "position": 2}]

    # já terminou: resultado entra no mesmo build
    db1 = tmp_path / "com.db"
    stats = build_db(HojeProvider(True), [2026], path=db1)
    assert stats["results"] == 2
    assert len(load_races_with_results(db1)) == 1
    # ainda não largou: fica só na agenda, sem erro
    db2 = tmp_path / "sem.db"
    stats = build_db(HojeProvider(False), [2026], path=db2)
    assert stats["results"] == 0
    assert load_races_with_results(db2) == []


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
