"""Config, grid 2026 e calendário — identidade do domínio F1."""
import pytest

from src.config import (load_circuits, load_config, load_drivers,
                        resolve_circuit, resolve_driver)


def test_config_dominio_f1():
    cfg = load_config()
    assert cfg["sport"] == "Formula 1" and cfg["season"] == 2026
    assert cfg["k_factor_base"] == 24 and cfg["k_factor_rookie"] == 40
    assert cfg["bankroll"] == 1000 and cfg["stake_unit"] == 50


def test_grid_2026_real():
    drivers = load_drivers()
    assert len(drivers) == 22                      # Cadillac entrou em 2026
    assert len({d["name"] for d in drivers}) == 22
    assert len({d["team"] for d in drivers}) == 11
    # semente = campeonato 2025: Norris (campeão) no topo
    top = max(drivers, key=lambda d: d["initial_elo"])
    assert top["name"] == "Lando Norris" and top["initial_elo"] == 1750
    rookies = [d for d in drivers if d.get("rookie")]
    assert [d["name"] for d in rookies] == ["Arvid Lindblad"]
    assert rookies[0]["initial_elo"] == 1300


def test_calendario_2026():
    circuits = load_circuits()
    assert len(circuits) == 22
    assert {c["round"] for c in circuits} == set(range(1, 23))
    for c in circuits:
        for k in ("power_sensitivity", "downforce_sensitivity", "tire_wear"):
            assert 0.0 <= c[k] <= 1.0


def test_resolucao_por_substring():
    assert resolve_driver("Verstappen")["team"] == "Red Bull"
    assert resolve_driver("antonelli")["team"] == "Mercedes"
    assert resolve_circuit("Monza")["country"] == "Italy"
    assert resolve_circuit("americas")["round"] == 17
    with pytest.raises(ValueError):
        resolve_driver("Senna")            # não está no grid 2026
    with pytest.raises(ValueError):
        resolve_circuit("Imola")           # fora do calendário 2026
