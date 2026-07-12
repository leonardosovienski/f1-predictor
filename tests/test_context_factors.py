"""Fase 4 — classificação de circuito, RatingBook por contexto,
reliability/pit efficiency rolling e choque de volatilidade (sintético)."""
import pytest

from src.context_factors import (ContextRatingBook, PitEfficiencyTracker,
                                 ReliabilityTracker, VolatilityShock,
                                 circuit_type, match_circuit_metadata,
                                 race_pitstop_summary)


# ---------- circuit_type / matching ----------

def test_circuit_type_classifica_os_tres_eixos():
    assert circuit_type(0.9, 0.2) == "power"          # Monza
    assert circuit_type(0.1, 0.95) == "downforce"      # Monaco
    assert circuit_type(0.5, 0.5) == "balanced"        # Albert Park


def test_match_circuit_metadata_substring_e_alias():
    catalog = [{"name": "Monza", "power_sensitivity": 0.9,
               "downforce_sensitivity": 0.2},
              {"name": "Interlagos", "power_sensitivity": 0.6,
               "downforce_sensitivity": 0.6}]
    assert match_circuit_metadata("Autodromo Nazionale di Monza",
                                  catalog)["name"] == "Monza"
    assert match_circuit_metadata("Autódromo José Carlos Pace",
                                  catalog)["name"] == "Interlagos"
    assert match_circuit_metadata("Bahrain International Circuit", catalog) is None


# ---------- ContextRatingBook (usa o RatingBook do core) ----------

def test_context_rating_book_bonus_zero_sem_historico():
    book = ContextRatingBook()
    assert book.bonus("Verstappen", "power") == 0.0


def test_context_rating_book_atualiza_so_o_tipo_certo():
    book = ContextRatingBook()
    book.update("power", ["A", "B", "C"])
    assert book.bonus("A", "power") > 0.0
    assert book.bonus("A", "downforce") == 0.0        # outro tipo intocado
    assert book.bonus("C", "power") < 0.0              # último perde rating


def test_context_rating_book_usa_ratingbook_do_core():
    from predictor_core.kernel.rating import RatingBook
    book = ContextRatingBook()
    assert isinstance(book.books["power"], RatingBook)


# ---------- reliability ----------

def test_reliability_default_sem_historico():
    t = ReliabilityTracker(default_rate=0.1)
    assert t.rate("Piloto X") == 0.1


def test_reliability_rolling_e_prequential():
    t = ReliabilityTracker(window=3)
    for dnf in (True, True, False, False, False):
        rate_antes = t.rate("A")
        t.update("A", dnf)
    # janela de 3: só as 3 últimas (False, False, False) contam
    assert t.rate("A") == 0.0


def test_reliability_janela_limitada():
    t = ReliabilityTracker(window=2)
    t.update("A", True)
    t.update("A", True)
    t.update("A", False)     # janela=2: esquece o primeiro True
    assert t.rate("A") == 0.5


# ---------- pit efficiency ----------

def test_race_pitstop_summary_agrega_por_piloto():
    pits = [{"driver_id": "a", "duration_s": 20.0},
           {"driver_id": "a", "duration_s": 22.0},
           {"driver_id": "b", "duration_s": 30.0}]
    summ = race_pitstop_summary(pits)
    assert summ == {"a": 21.0, "b": 30.0}


def test_pit_efficiency_z_score_neutro_sem_historico():
    t = PitEfficiencyTracker()
    assert t.z("EquipeX") == 0.0


def test_pit_efficiency_z_score_equipe_rapida_e_negativo():
    t = PitEfficiencyTracker()
    # constrói dispersão histórica do campo: a maioria das equipes ~25s
    for i, dur in enumerate([25.0, 26.0, 24.0, 27.0, 23.0, 25.5]):
        t.update(f"Equipe{i}", dur)
    t.update("EquipeRapida", 20.0)     # bem mais rápida que a dispersão vista
    assert t.z("EquipeRapida") < 0     # mais rápida que o histórico → z negativo (bom)


def test_pit_efficiency_z_score_usa_so_historico_anterior():
    """z() nunca deve usar a duração da corrida CORRENTE — só o que já
    foi `update`-ado antes. Sem chamar update() para a equipe/corrida de
    agora, o z fica baseado apenas no passado."""
    t = PitEfficiencyTracker()
    for dur in [25.0, 25.0, 25.0]:
        t.update("EquipeA", dur)
    z_antes = t.z("EquipeA")
    # nao chama update com a duracao de "hoje" antes de reconsultar
    assert t.z("EquipeA") == z_antes


# ---------- choque de volatilidade (sintético) ----------

def test_volatility_shock_multiplica_k_por_n_corridas():
    shock = VolatilityShock()
    shock.trigger("EquipeX", races=2, multiplier=3.0)
    assert shock.k_multiplier("EquipeX") == 3.0
    shock.tick("EquipeX")
    assert shock.k_multiplier("EquipeX") == 3.0     # ainda 1 restante
    shock.tick("EquipeX")
    assert shock.k_multiplier("EquipeX") == 1.0     # esgotado


def test_volatility_shock_sem_trigger_e_neutro():
    shock = VolatilityShock()
    assert shock.k_multiplier("Ninguem") == 1.0


def test_volatility_shock_valida_entrada():
    shock = VolatilityShock()
    with pytest.raises(ValueError):
        shock.trigger("A", races=0, multiplier=2.0)
    with pytest.raises(ValueError):
        shock.trigger("A", races=2, multiplier=0.0)
