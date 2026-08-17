"""require_manual_approval / bet_fingerprint — o último portão antes de uma
aposta real. Antes deste arquivo, nenhum teste alcançava esta lógica: em
tests/test_betting.py, record_bet(real=True) sempre bate primeiro no closure
global do projeto (PERMANENTLY_BLOCKED), que existe antes de chegar aqui —
então require_manual_approval nunca era exercitada de ponta a ponta."""
from datetime import datetime, timedelta, timezone

import pytest

from src.manual_approval import bet_fingerprint, require_manual_approval

FP = bet_fingerprint(market="h2h", selection="Piloto A", prob_model=0.6,
                     decimal_odds=2.0, bankroll=1000.0)
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _write(tmp_path, **overrides):
    approval = {"schema_version": 1, "status": "APPROVED", "approval_id": "manual-1",
               "approved_by": "operator", "approved_at": (NOW - timedelta(hours=1)).isoformat(),
               "expires_at": (NOW + timedelta(hours=1)).isoformat(), "bet_fingerprint": FP,
               **overrides}
    path = tmp_path / "approval.json"
    import json
    path.write_text(json.dumps(approval), encoding="utf-8")
    return path


# ---------- bet_fingerprint ----------

def test_bet_fingerprint_e_deterministico():
    a = bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.0, bankroll=1000.0)
    b = bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.0, bankroll=1000.0)
    assert a == b


def test_bet_fingerprint_muda_com_qualquer_campo():
    base = bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.0, bankroll=1000.0)
    assert base != bet_fingerprint(market="h2h", selection="Y", prob_model=0.6, decimal_odds=2.0, bankroll=1000.0)
    assert base != bet_fingerprint(market="h2h", selection="X", prob_model=0.61, decimal_odds=2.0, bankroll=1000.0)
    assert base != bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.01, bankroll=1000.0)
    assert base != bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.0, bankroll=1000.01)


def test_bet_fingerprint_vincula_strategy_id():
    winner = bet_fingerprint(market="h2h", selection="X", prob_model=0.6,
                             decimal_odds=2.0, bankroll=1000.0,
                             strategy_id="f1/winner-pre-event/v1")
    h2h = bet_fingerprint(market="h2h", selection="X", prob_model=0.6,
                          decimal_odds=2.0, bankroll=1000.0,
                          strategy_id="f1/h2h-post-qualifying/v1")
    assert winner != h2h


def test_bet_fingerprint_ignora_kwargs_extras():
    """record_bet passa **extra (circuit, driver_b, ...) — não deve afetar o fingerprint."""
    a = bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.0, bankroll=1000.0)
    b = bet_fingerprint(market="h2h", selection="X", prob_model=0.6, decimal_odds=2.0, bankroll=1000.0,
                        circuit="Monza", driver_b="Hamilton")
    assert a == b


# ---------- require_manual_approval: caminho feliz ----------

def test_aprovacao_valida_retorna_metadados(tmp_path):
    path = _write(tmp_path)
    out = require_manual_approval(path, fingerprint=FP, now=NOW)
    assert out["approval_id"] == "manual-1"
    assert out["approved_by"] == "operator"


# ---------- ausência / arquivo inválido ----------

def test_path_none_e_recusado():
    with pytest.raises(PermissionError, match="arquivo de aprovação"):
        require_manual_approval(None, fingerprint=FP, now=NOW)


def test_arquivo_ausente_e_recusado(tmp_path):
    with pytest.raises(PermissionError, match="ausente"):
        require_manual_approval(tmp_path / "nao_existe.json", fingerprint=FP, now=NOW)


def test_json_malformado_e_recusado(tmp_path):
    path = tmp_path / "approval.json"
    path.write_text("{ nao e json valido", encoding="utf-8")
    with pytest.raises(PermissionError, match="inválido"):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_campos_de_data_ausentes_sao_recusados(tmp_path):
    path = _write(tmp_path, approved_at="")
    with pytest.raises(PermissionError, match="inválido"):
        require_manual_approval(path, fingerprint=FP, now=NOW)


# ---------- schema / status ----------

def test_schema_version_errada_e_recusada(tmp_path):
    path = _write(tmp_path, schema_version=2)
    with pytest.raises(PermissionError, match="não é válida"):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_status_diferente_de_approved_e_recusado(tmp_path):
    path = _write(tmp_path, status="PENDING")
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_approval_id_vazio_e_recusado(tmp_path):
    """Regressão: approval_id="" antes passava no isinstance(str) sem checar
    conteúdo — o mesmo padrão que approved_by já exigia."""
    path = _write(tmp_path, approval_id="")
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_approval_id_nao_string_e_recusado(tmp_path):
    path = _write(tmp_path, approval_id=42)
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_approved_by_vazio_ou_espacos_e_recusado(tmp_path):
    with pytest.raises(PermissionError):
        require_manual_approval(_write(tmp_path, approved_by=""), fingerprint=FP, now=NOW)
    with pytest.raises(PermissionError):
        require_manual_approval(_write(tmp_path, approved_by="   "), fingerprint=FP, now=NOW)


# ---------- fingerprint ----------

def test_fingerprint_diferente_e_recusado(tmp_path):
    path = _write(tmp_path, bet_fingerprint="outro-fingerprint")
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_fingerprint_ausente_e_recusado(tmp_path):
    path = _write(tmp_path, bet_fingerprint=None)
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


# ---------- validade temporal ----------

def test_aprovacao_futura_e_recusada(tmp_path):
    path = _write(tmp_path, approved_at=(NOW + timedelta(minutes=1)).isoformat())
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_aprovacao_expirada_e_recusada(tmp_path):
    path = _write(tmp_path, expires_at=(NOW - timedelta(minutes=1)).isoformat())
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_expiracao_exatamente_agora_e_recusada(tmp_path):
    """Limite: expires_at == now conta como expirada (checagem é <=)."""
    path = _write(tmp_path, expires_at=NOW.isoformat())
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_datas_sem_timezone_sao_recusadas(tmp_path):
    naive = datetime(2026, 8, 14, 11, 0).isoformat()  # sem tzinfo
    path = _write(tmp_path, approved_at=naive)
    with pytest.raises(PermissionError):
        require_manual_approval(path, fingerprint=FP, now=NOW)


def test_now_ingenuo_e_recusado_sem_crashar(tmp_path):
    """Regressão: 'now' sem timezone comparado a approved_at/expires_at
    (timezone-aware) levantava TypeError não capturado em vez de
    PermissionError — quebrava o contrato de falha limpa que
    record_bet/operate.py dependem (`except PermissionError`)."""
    path = _write(tmp_path)
    now_ingenuo = datetime(2026, 8, 14, 12, 0)  # sem tzinfo
    with pytest.raises(PermissionError, match="timezone-aware"):
        require_manual_approval(path, fingerprint=FP, now=now_ingenuo)


def test_now_default_e_timezone_aware(tmp_path):
    """Sem 'now' explícito, o default (datetime.now(UTC)) não deve disparar
    o novo guard de timezone."""
    path = _write(tmp_path, approved_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                 expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    out = require_manual_approval(path, fingerprint=FP)
    assert out["approval_id"] == "manual-1"
