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


# ---------- gate (por estratégia) ----------

def _registry(tmp_path, strategy_id, verdict_key, verdict_path, extra_strategies=None):
    registry_path = tmp_path / "strategy_gates.json"
    strategies = {strategy_id: {"verdict_path": str(verdict_path),
                                "verdict_key": verdict_key}}
    if extra_strategies:
        strategies.update(extra_strategies)
    registry_path.write_text(json.dumps({"schema_version": 1, "strategies": strategies}),
                             encoding="utf-8")
    return registry_path


def test_go_gate_sem_strategy_id():
    assert go_gate(None)["decision"] == "NO-GO"
    assert go_gate("")["decision"] == "NO-GO"
    assert go_gate("   ")["decision"] == "NO-GO"


def test_go_gate_sem_registro(tmp_path):
    g = go_gate("qualquer-estrategia", registry_path=tmp_path / "nao_existe.json")
    assert g["decision"] == "NO-GO"


def test_go_gate_estrategia_nao_cadastrada(tmp_path):
    registry_path = tmp_path / "strategy_gates.json"
    registry_path.write_text(json.dumps({"schema_version": 1, "strategies": {}}),
                             encoding="utf-8")
    g = go_gate("f1-nao-existe-v1", registry_path=registry_path)
    assert g["decision"] == "NO-GO"
    assert "não é uma estratégia registrada" in g["reason"]


def test_go_gate_veredito_ausente(tmp_path):
    registry_path = _registry(tmp_path, "estrategia-x", "HX",
                              tmp_path / "nao_existe.json")
    g = go_gate("estrategia-x", registry_path=registry_path)
    assert g["decision"] == "NO-GO"


def test_go_gate_le_veredito_refutada(tmp_path):
    verdict_path = tmp_path / "backtest_fase1.json"
    verdict_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "REFUTADA"}}}),
                            encoding="utf-8")
    registry_path = _registry(tmp_path, "f1-winner-pre-event-elo-v1", "H1-F1", verdict_path)
    g = go_gate("f1-winner-pre-event-elo-v1", registry_path=registry_path)
    assert g["decision"] == "NO-GO"
    assert g["verdict"] == "REFUTADA"
    assert g["strategy_id"] == "f1-winner-pre-event-elo-v1"


def test_go_gate_le_veredito_comprovada(tmp_path):
    verdict_path = tmp_path / "backtest_x.json"
    verdict_path.write_text(json.dumps({"verdicts": {"HX": {"verdict": "COMPROVADA"}}}),
                            encoding="utf-8")
    registry_path = _registry(tmp_path, "f1-h2h-post-qualifying-v1", "HX", verdict_path)
    g = go_gate("f1-h2h-post-qualifying-v1", registry_path=registry_path)
    assert g["decision"] == "GO"


def test_go_gate_veredito_de_uma_estrategia_nao_vaza_para_outra(tmp_path):
    """Prova regressiva do bug de acoplamento: duas estratégias no MESMO
    registro, com vereditos opostos — cada uma só pode receber a SUA
    decisão, nunca a da outra (era exatamente esse acoplamento que existia
    quando go_gate() lia H1-F1 incondicionalmente, inclusive para apostas
    de estratégias H2H que nunca foram testadas contra H1-F1)."""
    refutada = tmp_path / "backtest_a.json"
    refutada.write_text(json.dumps({"verdicts": {"HA": {"verdict": "REFUTADA"}}}),
                        encoding="utf-8")
    comprovada = tmp_path / "backtest_b.json"
    comprovada.write_text(json.dumps({"verdicts": {"HB": {"verdict": "COMPROVADA"}}}),
                          encoding="utf-8")
    registry_path = _registry(tmp_path, "estrategia-a", "HA", refutada,
                              extra_strategies={"estrategia-b": {
                                  "verdict_path": str(comprovada), "verdict_key": "HB"}})
    assert go_gate("estrategia-a", registry_path=registry_path)["decision"] == "NO-GO"
    assert go_gate("estrategia-b", registry_path=registry_path)["decision"] == "GO"


def test_go_gate_real_do_projeto_e_no_go():
    """O registro real do projeto (data/strategy_gates.json) tem que
    refletir H1-F1 REFUTADA para a única estratégia hoje cadastrada."""
    g = go_gate("f1-winner-pre-event-elo-v1")
    assert g["decision"] == "NO-GO"
    assert g["verdict"] == "REFUTADA"


def test_go_gate_real_do_projeto_estrategia_h2h_nao_cadastrada():
    """H2H contra preço de mercado nunca foi testada — a estratégia usada
    por padrão em operate.py --h2h não deve estar registrada hoje, e o
    motivo do NO-GO tem que ser 'não registrada', não o veredito de uma
    hipótese diferente."""
    g = go_gate("f1-h2h-post-qualifying-v1")
    assert g["decision"] == "NO-GO"
    assert g["verdict"] is None
    assert "não é uma estratégia registrada" in g["reason"]


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


def test_record_bet_real_bloqueado_sem_strategy_id(tmp_path):
    """strategy_id é obrigatório pra real=True, e é checado ANTES do
    closure/gate — reachable independente do estado de fechamento real do
    projeto (que já bloqueia tudo por outro motivo)."""
    with pytest.raises(PermissionError, match="strategy_id"):
        record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                  decimal_odds=2.0, bankroll=1000.0, real=True,
                  path=tmp_path / "bets.jsonl")
    assert not (tmp_path / "bets.jsonl").exists()


def test_record_bet_real_bloqueado_sem_go(tmp_path):
    verdict_path = tmp_path / "backtest_fase1.json"
    verdict_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "REFUTADA"}}}),
                            encoding="utf-8")
    registry_path = _registry(tmp_path, "f1-winner-pre-event-elo-v1", "H1-F1", verdict_path)
    with pytest.raises(PermissionError):
        record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                  decimal_odds=2.0, bankroll=1000.0, real=True,
                  strategy_id="f1-winner-pre-event-elo-v1",
                  path=tmp_path / "bets.jsonl", registry_path=registry_path)
    assert not (tmp_path / "bets.jsonl").exists()   # nada foi gravado


def test_record_bet_real_permitido_com_go(tmp_path):
    """Mesmo com estratégia registrada, veredito COMPROVADA e aprovação
    manual válida, o closure global (real_money_operation) do projeto real
    ainda bloqueia — é a camada mais externa e independente do gate por
    estratégia."""
    verdict_path = tmp_path / "backtest_fase1.json"
    verdict_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "COMPROVADA"}}}),
                            encoding="utf-8")
    registry_path = _registry(tmp_path, "f1-winner-pre-event-elo-v1", "H1-F1", verdict_path)
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps({
        "schema_version": 1, "status": "APPROVED", "approval_id": "manual-1",
        "approved_by": "operator", "approved_at": "2020-01-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "bet_fingerprint": bet_fingerprint(market="h2h", selection="Piloto A",
            prob_model=.6, decimal_odds=2., bankroll=1000.)}), encoding="utf-8")
    with pytest.raises(PermissionError, match="PERMANENTLY_BLOCKED"):
        record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                   decimal_odds=2.0, bankroll=1000.0, real=True,
                   strategy_id="f1-winner-pre-event-elo-v1",
                   path=tmp_path / "bets.jsonl", registry_path=registry_path,
                   approval_path=approval_path)


def test_record_bet_real_requires_matching_manual_approval(tmp_path):
    verdict_path = tmp_path / "gate.json"
    verdict_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "COMPROVADA"}}}))
    registry_path = _registry(tmp_path, "f1-winner-pre-event-elo-v1", "H1-F1", verdict_path)
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({"schema_version": 1, "status": "APPROVED",
        "approval_id": "manual-1", "approved_by": "operator",
        "approved_at": "2020-01-01T00:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00",
        "bet_fingerprint": "wrong"}))
    with pytest.raises(PermissionError):
        record_bet(market="h2h", selection="Piloto A", prob_model=.6, decimal_odds=2,
                   bankroll=1000, real=True, strategy_id="f1-winner-pre-event-elo-v1",
                   registry_path=registry_path, approval_path=approval)


def test_record_bet_estrategia_nao_registrada_e_bloqueada(tmp_path):
    """record_bet(real=True) sempre bate primeiro no closure global real do
    projeto (PERMANENTLY_BLOCKED) — a prova isolada de que o veredito de
    UMA estratégia não vaza para outra está em
    test_go_gate_veredito_de_uma_estrategia_nao_vaza_para_outra, que testa
    go_gate() diretamente sem o closure no caminho. Aqui só confirmamos que
    uma estratégia H2H sem trial próprio também é rejeitada end-to-end."""
    verdict_path = tmp_path / "backtest_fase1.json"
    verdict_path.write_text(json.dumps({"verdicts": {"H1-F1": {"verdict": "COMPROVADA"}}}),
                            encoding="utf-8")
    registry_path = _registry(tmp_path, "f1-winner-pre-event-elo-v1", "H1-F1", verdict_path)
    with pytest.raises(PermissionError):
        record_bet(market="h2h", selection="Piloto A", prob_model=0.6,
                  decimal_odds=2.0, bankroll=1000.0, real=True,
                  strategy_id="f1-h2h-post-qualifying-v1",
                  path=tmp_path / "bets.jsonl", registry_path=registry_path)
    assert not (tmp_path / "bets.jsonl").exists()


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
