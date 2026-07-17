"""Modelo Elo ordinal de F1 — Fase 0. Ratings em tmp_path."""
import pytest

from src.model import F1EloModel, win_probability


@pytest.fixture
def model(tmp_path):
    return F1EloModel(ratings_file=tmp_path / "ratings.json")


def test_predict_race_soma_1_e_favorito(model):
    r = model.predict_race("Monza", "dry")
    ranking = r["ranking"]
    assert len(ranking) == 22                      # grid 2026 real (Cadillac)
    soma_win = sum(v["win"] for v in ranking.values())
    assert abs(soma_win - 1.0) < 0.01              # Monte Carlo: 1% de folga
    # semente 2025: Norris campeão → maior P(win)
    assert next(iter(ranking)) == "Lando Norris"
    top = ranking["Lando Norris"]
    assert top["win"] > 0.05
    assert top["win"] <= top["podium"] <= top["top6"] <= 1.0


def test_predict_race_deterministico_com_seed(model):
    r1 = model.predict_race("Monza")
    r2 = model.predict_race("Monza")
    assert r1["ranking"] == r2["ranking"]          # mesma seed → mesmo resultado


def test_podium_medio_e_consistente(model):
    """Σ P(podium) = 3 e Σ P(top6) = 6 (3 vagas de pódio, 6 de top6)."""
    r = model.predict_race("Monaco")
    assert abs(sum(v["podium"] for v in r["ranking"].values()) - 3.0) < 0.03
    assert abs(sum(v["top6"] for v in r["ranking"].values()) - 6.0) < 0.05


def test_head_to_head(model):
    r = model.predict_head_to_head("Verstappen", "Hamilton", "Monza")
    assert abs(r["prob_a_beats_b"] + r["prob_b_beats_a"] - 1.0) < 1e-9
    # Verstappen (1730) > Hamilton (1650) na semente 2025
    assert r["prob_a_beats_b"] > 0.5
    # fórmula fechada consistente com a logística (elos exibidos são
    # arredondados a 1 casa → tolerância proporcional)
    assert abs(r["prob_a_beats_b"]
               - win_probability(r["elo_a"], r["elo_b"])) < 1e-3


def test_predict_race_with_grid_accepts_multiple_pit_lane_starters(model):
    # Regressão: a checagem de duplicidade rejeitava position=0 repetido,
    # mas o próprio blend (linha "pilotos[nm] if pilotos[nm] > 0 else n+1")
    # já trata todo 0 como "última posição" — múltiplos pilotos podem
    # largar do pit lane na mesma corrida (penalidades de grid).
    names = list(model.ratings)[:4]
    grid = {names[0]: 0, names[1]: 0, names[2]: 1, names[3]: 2}
    result = model.predict_race_with_grid("Monza", grid)
    assert len(result["ranking"]) == 4


def test_predict_race_with_grid_still_rejects_duplicate_nonzero_position(model):
    names = list(model.ratings)[:2]
    with pytest.raises(ValueError, match="posições de grid repetidas"):
        model.predict_race_with_grid("Monza", {names[0]: 1, names[1]: 1})


def test_h2h_erros(model):
    with pytest.raises(ValueError):
        model.predict_head_to_head("Verstappen", "verstappen", "Monza")
    with pytest.raises(ValueError):
        model.predict_head_to_head("Piloto Fantasma", "Hamilton", "Monza")
    with pytest.raises(ValueError):
        model.predict_head_to_head("Verstappen", "Hamilton", "Circuito Fantasma")


def test_update_ratings_primeiros_sobem(model):
    """Corrida simulada com a ordem INVERTIDA ao rating: os de baixo (que
    chegaram na frente) sobem; os favoritos que ficaram atrás descem."""
    ordem_elo = sorted(model.ratings, key=model.ratings.get, reverse=True)
    resultado = {n: i + 1 for i, n in enumerate(reversed(ordem_elo))}
    antes = dict(model.ratings)
    deltas = model.update_ratings(resultado)
    vencedor = min(resultado, key=resultado.get)     # pior rating, chegou 1º
    lanterna = max(resultado, key=resultado.get)     # melhor rating, chegou 22º
    assert model.ratings[vencedor] > antes[vencedor]
    assert model.ratings[lanterna] < antes[lanterna]
    # soma zero
    assert abs(sum(model.ratings.values()) - sum(antes.values())) < 1e-6
    assert deltas[vencedor] > 0 > deltas[lanterna]


def test_update_ratings_k_de_novato_maior(model):
    """Mesmo resultado relativo: o novato (Lindblad, K=40) desloca mais que
    um consolidado em posição simétrica."""
    nomes = list(model.ratings)
    # corrida só com 3 pilotos: novato vence dois consolidados de rating igual
    res = {"Arvid Lindblad": 1, "Esteban Ocon": 2, "Lance Stroll": 3}
    antes = model.ratings["Arvid Lindblad"]
    model.update_ratings(res)
    ganho_novato = model.ratings["Arvid Lindblad"] - antes

    m2 = F1EloModel(ratings_file=model.path.with_name("r2.json"))
    m2.ratings["Pierre Gasly"] = m2.ratings["Arvid Lindblad"]  # mesmo rating
    res2 = {"Pierre Gasly": 1, "Esteban Ocon": 2, "Lance Stroll": 3}
    antes2 = m2.ratings["Pierre Gasly"]
    m2.update_ratings(res2)
    ganho_veterano = m2.ratings["Pierre Gasly"] - antes2
    assert ganho_novato > ganho_veterano


def test_update_ratings_persiste(model):
    model.update_ratings({"Max Verstappen": 1, "Lando Norris": 2})
    recarregado = F1EloModel(ratings_file=model.path)
    assert recarregado.ratings["Max Verstappen"] == pytest.approx(
        model.ratings["Max Verstappen"])


def test_update_ratings_erros(model):
    with pytest.raises(ValueError):
        model.update_ratings({"Max Verstappen": 1})          # só 1 piloto
    with pytest.raises(ValueError):
        model.update_ratings({"Max Verstappen": 1, "Lando Norris": 1})  # empate
