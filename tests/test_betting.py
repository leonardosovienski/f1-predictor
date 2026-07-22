"""Fase 3 — Kelly, gate de GO, bet log append-only, settle, odds provider."""
import json

import pytest

from src.betting import (KELLY_CAP_FRACTION, go_gate, kelly_fraction,
                         kelly_stake, record_bet, settle_bet)
from src.data.odds_provider import OddsProvider
from src.manual_approval import bet_fingerprint

from predictor_core.data.contracts import DataUnavailableError


# ---------- Kelly ----------

def test_kelly_fraction_sem_edge_e_zero():
    """Odds justas para a prob do modelo (p=1/odds): edge zero, f*=0."""
    assert kelly_fraction(0.5, 2.0) == 0.0


def test_kelly_fraction_com_edge_conhecido():
    """p=0.6, odds decimal 2.0 (b=1): f* = (0.6·1 - 0.4)/1 = 0.2."""
    assert abs(kelly_fraction(0.6, 2.0) - 0.2) < 1e-9


def test_kelly_fraction_nunca_negativa():
    assert kelly_fraction(0.3, 2.0) == 0.0     # p < 1/odds → sem edge


def test_kelly_stake_respeita_teto():
    """Edge grande: o teto de 5% do bankroll tem que dominar o fracionário."""
    stake = kelly_stake(0.95, 5.0, bankroll=1000.0)
    assert stake == round(KELLY_CAP_FRACTION * 1000.0, 2)


def test_kelly_stake_erros():
    with pytest.raises(ValueError):
        kelly_stake(0.5, 2.0, bankroll=0)
    with pytest.raises(ValueError):
        kelly_fraction(1.5, 2.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.5, 1.0)               # odds <= 1


# ---------- gate ----------

def test_go_gate_sem_arquivo(tmp_path):
    g = go_gate(tmp_path / "nao_existe.json")
    assert g["decision"] == "NO-GO"


def test_go_gate_le_veredito_refutada(tmp_path):
    p = tmp_path / "backtest_fase1.json"
    p.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "REFUTADA"}}}),
                encoding="utf-8")
    g = go_gate(p)
    assert g["decision"] == "NO-GO"
    assert g["h1_verdict"] == "REFUTADA"


def test_go_gate_le_veredito_comprovada(tmp_path):
    p = tmp_path / "backtest_fase1.json"
    p.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "COMPROVADA"}}}),
                encoding="utf-8")
    g = go_gate(p)
    assert g["decision"] == "GO"


def test_go_gate_real_do_projeto_e_no_go():
    """O backtest real (Fase 1) rodou e H1-F1 foi REFUTADA — o gate do
    projeto de verdade tem que refletir isso (nenhuma aposta real)."""
    g = go_gate()
    assert g["decision"] == "NO-GO"
    assert g["h1_verdict"] == "REFUTADA"


# ---------- record_bet / settle_bet ----------

def test_record_bet_paper(tmp_path):
    bet = record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                     decimal_odds=2.0, bankroll=1000.0, real=False,
                     path=tmp_path / "bets.jsonl")
    assert bet["real"] is False
    assert abs(bet["edge"] - 0.2) < 1e-9         # 0.6*2 - 1
    assert bet["stake"] > 0
    linhas = (tmp_path / "bets.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1
    assert json.loads(linhas[0])["id"] == bet["id"]


def test_record_bet_real_bloqueado_sem_go(tmp_path):
    gate_path = tmp_path / "backtest_fase1.json"
    gate_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "REFUTADA"}}}),
                         encoding="utf-8")
    with pytest.raises(PermissionError):
        record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                  decimal_odds=2.0, bankroll=1000.0, real=True,
                  path=tmp_path / "bets.jsonl", gate_path=gate_path)
    assert not (tmp_path / "bets.jsonl").exists()   # nada foi gravado


def test_record_bet_real_permitido_com_go(tmp_path):
    gate_path = tmp_path / "backtest_fase1.json"
    gate_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "COMPROVADA"}}}),
                         encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps({
        "schema_version": 1, "status": "APPROVED", "approval_id": "manual-1",
        "approved_by": "operator", "approved_at": "2020-01-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "bet_fingerprint": bet_fingerprint(market="h2h", selection="Piloto A",
            prob_model=.6, decimal_odds=2., bankroll=1000.)}), encoding="utf-8")
    bet = record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                     decimal_odds=2.0, bankroll=1000.0, real=True,
                     path=tmp_path / "bets.jsonl", gate_path=gate_path,
                     approval_path=approval_path)
    assert bet["real"] is True
    assert bet["manual_approval"]["approval_id"] == "manual-1"


def test_record_bet_real_requires_matching_manual_approval(tmp_path):
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "COMPROVADA"}}}))
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({"schema_version": 1, "status": "APPROVED",
        "approval_id": "manual-1", "approved_by": "operator",
        "approved_at": "2020-01-01T00:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00",
        "bet_fingerprint": "wrong"}))
    with pytest.raises(PermissionError):
        record_bet(market="h2h", selection="Piloto A", prob_model=.6, decimal_odds=2,
                   bankroll=1000, real=True, gate_path=gate, approval_path=approval)


def test_settle_bet_ganhou_e_perdeu(tmp_path):
    bet = record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                     decimal_odds=2.0, bankroll=1000.0,
                     path=tmp_path / "bets.jsonl")
    ganhou = settle_bet(bet, won=True, path=tmp_path / "bets.jsonl")
    assert abs(ganhou["pnl"] - bet["stake"]) < 1e-9   # odds 2.0 → pnl=stake
    perdeu = settle_bet(bet, won=False, path=tmp_path / "bets.jsonl")
    assert abs(perdeu["pnl"] + bet["stake"]) < 1e-9
    linhas = (tmp_path / "bets.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 3                            # bet + 2 settlements (append-only)


# ---------- odds provider ----------

def test_odds_provider_sem_chave_levanta(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    p = OddsProvider()
    assert p.api_key is None
    assert p.health_check() is False
    with pytest.raises(DataUnavailableError):
        p.list_sports()
    with pytest.raises(DataUnavailableError):
        p.fetch_h2h_odds()


def test_odds_provider_com_chave_ainda_recusa_fetch(monkeypatch):
    """Mesmo COM chave, fetch_h2h_odds recusa: a sondagem real de
    /v4/sports (2026-07-12) confirmou que a The Odds API não cobre F1 —
    não há endpoint para integrar."""
    monkeypatch.setenv("ODDS_API_KEY", "fake-key-for-test")
    p = OddsProvider()
    assert p.health_check() is True
    with pytest.raises(DataUnavailableError):
        p.fetch_h2h_odds()
