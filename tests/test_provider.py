"""Provider Jolpica — parsing, cache imutável, offline e corrida futura."""
import json

import pytest

from src.data.f1_provider import F1Provider, is_dnf

from predictor_core.data.contracts import DataUnavailableError

_RESULTS_FIXTURE = {"MRData": {"RaceTable": {"Races": [{
    "season": "2022", "round": "1", "raceName": "Bahrain Grand Prix",
    "Results": [
        {"position": "1", "grid": "1", "status": "Finished", "points": "26",
         "Driver": {"driverId": "leclerc", "givenName": "Charles",
                    "familyName": "Leclerc"},
         "Constructor": {"name": "Ferrari"}},
        {"position": "2", "grid": "3", "status": "+1 Lap", "points": "18",
         "Driver": {"driverId": "sainz", "givenName": "Carlos",
                    "familyName": "Sainz"},
         "Constructor": {"name": "Ferrari"}},
        {"position": "3", "grid": "0", "status": "Power Unit", "points": "0",
         "Driver": {"driverId": "max_verstappen", "givenName": "Max",
                    "familyName": "Verstappen"},
         "Constructor": {"name": "Red Bull"}},
    ]}]}}}

_SCHEDULE_FIXTURE = {"MRData": {"RaceTable": {"Races": [
    {"season": "2022", "round": "1", "raceName": "Bahrain Grand Prix",
     "date": "2022-03-20", "Circuit": {"circuitName": "Bahrain International Circuit"}},
    {"season": "2022", "round": "2", "raceName": "Saudi Arabian Grand Prix",
     "date": "2022-03-27", "Circuit": {"circuitName": "Jeddah Corniche Circuit"}},
]}}}

_QUALIFYING_FIXTURE = {"MRData": {"RaceTable": {"Races": [{
    "season": "2026", "round": "10",
    "QualifyingResults": [
        {"position": "1", "Driver": {"driverId": "antonelli", "givenName": "Andrea Kimi",
                                     "familyName": "Antonelli"},
         "Constructor": {"name": "Mercedes"}},
        {"position": "2", "Driver": {"driverId": "max_verstappen", "givenName": "Max",
                                     "familyName": "Verstappen"},
         "Constructor": {"name": "Red Bull"}},
    ]}]}}}

_EMPTY_FIXTURE = {"MRData": {"RaceTable": {"Races": []}}}


@pytest.fixture
def provider(tmp_path):
    """Offline com cache em tmp — teste nunca toca a rede."""
    return F1Provider(cache_dir=tmp_path, offline=True)


def test_is_dnf_convencao():
    assert not is_dnf("Finished")
    assert not is_dnf("+1 Lap")
    assert not is_dnf("+2 Laps")
    assert is_dnf("Accident")
    assert is_dnf("Power Unit")
    assert is_dnf("Retired")


def test_fetch_results_parse_do_cache(provider, tmp_path):
    (tmp_path / "results_2022_01.json").write_text(
        json.dumps(_RESULTS_FIXTURE), encoding="utf-8")
    rows = provider.fetch_results(2022, 1)
    assert len(rows) == 3
    r1 = rows[0]
    assert r1["driver"] == "Charles Leclerc"
    assert r1["driver_id"] == "leclerc"
    assert (r1["position"], r1["grid"], r1["dnf"]) == (1, 1, False)
    assert r1["points"] == 26.0
    assert rows[1]["dnf"] is False                 # '+1 Lap' é classificado
    assert rows[2]["dnf"] is True                  # 'Power Unit' é DNF
    assert rows[2]["grid"] == 0                    # pit lane preservado


def test_fetch_schedule_parse_do_cache(provider, tmp_path):
    (tmp_path / "schedule_2022.json").write_text(
        json.dumps(_SCHEDULE_FIXTURE), encoding="utf-8")
    sched = provider.fetch_schedule(2022)
    assert [r["round"] for r in sched] == [1, 2]
    assert sched[0]["circuit"] == "Bahrain International Circuit"
    assert sched[0]["date"] == "2022-03-20"


def test_fetch_qualifying_parse_do_cache(provider, tmp_path):
    (tmp_path / "qualifying_2026_10.json").write_text(
        json.dumps(_QUALIFYING_FIXTURE), encoding="utf-8")
    grid = provider.fetch_qualifying(2026, 10)
    assert len(grid) == 2
    assert grid[0]["driver"] == "Andrea Kimi Antonelli"
    assert grid[0]["position"] == 1
    assert grid[1]["driver"] == "Max Verstappen"
    assert grid[1]["constructor"] == "Red Bull"


def test_fetch_qualifying_vazia_antes_do_quali(provider, tmp_path):
    (tmp_path / "qualifying_2026_11.json").write_text(
        json.dumps({"MRData": {"RaceTable": {"Races": []}}}), encoding="utf-8")
    assert provider.fetch_qualifying(2026, 11) == []


def test_offline_sem_cache_levanta(provider):
    with pytest.raises(DataUnavailableError):
        provider.fetch_results(2022, 9)


def test_corrida_futura_nao_vira_cache_imutavel(tmp_path, monkeypatch):
    """Resposta VAZIA (corrida ainda não aconteceu) não pode ser cacheada —
    o cache é imutável e congelaria o resultado para sempre."""
    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    respostas = [_EMPTY_FIXTURE, _RESULTS_FIXTURE]
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout: _Resp(respostas.pop(0)))
    monkeypatch.setattr("time.sleep", lambda s: None)
    p = F1Provider(cache_dir=tmp_path, offline=False)

    assert p.fetch_results(2026, 22) == []                    # futura: vazia
    assert not (tmp_path / "results_2026_22.json").exists()   # NÃO cacheou
    rows = p.fetch_results(2026, 22)                          # pós-corrida
    assert len(rows) == 3
    assert (tmp_path / "results_2026_22.json").exists()       # agora sim
