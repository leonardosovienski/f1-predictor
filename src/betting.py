"""Operação — Fase 3. GATED: nenhuma aposta REAL sai daqui sem GO.

O gate lê o VEREDITO pré-registrado de H1-F1 (`data/backtest_fase1.json`)
— "o Elo bate o grid de largada no RPS" — porque é a barra real de edge
sobre o preditor gratuito da F1, não H3-F1b (que só mede se o grid ajuda
o Elo A SE MESMO; não estabelece edge sobre o mercado). H1-F1 está
REFUTADA (RELATORIO_FASE1.md) → o gate é NO-GO por padrão. `record_bet`
recusa `real=True` enquanto o gate não abrir; **não é ferramenta de
investimento** (declarado desde a Fase 0).

Kelly fracionário (1/4) com teto de 5% do bankroll — controle de risco
padrão mesmo com edge comprovado (edge medido tem incerteza; full Kelly
sobre-alavanca).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT
from .closure import require_real_money_allowed
from .manual_approval import bet_fingerprint, require_manual_approval

KELLY_SHRINK = 0.25          # quarto de Kelly
KELLY_CAP_FRACTION = 0.05    # nunca mais que 5% do bankroll numa aposta


def _bets_log_path() -> Path:
    return Path(os.environ.get("BETS_LOG_PATH", ROOT / "data" / "bets.jsonl"))


def kelly_fraction(prob: float, decimal_odds: float) -> float:
    """Fração de Kelly PURA: f* = (p·b - (1-p)) / b, b = odds decimal - 1.
    Negativa (sem edge) vira 0 — nunca aposta contra o próprio modelo."""
    if not (0.0 < prob < 1.0):
        raise ValueError("prob precisa estar em (0, 1)")
    b = decimal_odds - 1.0
    if b <= 0:
        raise ValueError("decimal_odds precisa ser > 1.0")
    f = (prob * b - (1.0 - prob)) / b
    return max(0.0, f)


def kelly_stake(prob: float, decimal_odds: float, bankroll: float,
                shrink: float = KELLY_SHRINK,
                cap: float = KELLY_CAP_FRACTION) -> float:
    """Stake em unidades monetárias: Kelly fracionário, com teto absoluto
    de `cap` do bankroll (o teto pode dominar o fracionário quando o edge
    aparente é grande — disciplina contra overconfidence do modelo)."""
    if bankroll <= 0:
        raise ValueError("bankroll precisa ser positivo")
    f = min(kelly_fraction(prob, decimal_odds) * shrink, cap)
    return round(f * bankroll, 2)


def go_gate(path: Path | str | None = None) -> dict:
    """Decisão GO/NO-GO: lê o veredito de H1-F1 (Elo vs grid, RPS, DM) do
    backtest da Fase 1. Sem o arquivo (backtest nunca rodou) ou veredito
    diferente de COMPROVADA → NO-GO. Único portão para apostas reais."""
    p = Path(path or ROOT / "data" / "backtest_fase1.json")
    if not p.exists():
        return {"decision": "NO-GO", "h1_verdict": None,
                "reason": "backtest_fase1.json ausente — rode "
                          "scripts/run_backtest.py"}
    data = json.loads(p.read_text(encoding="utf-8"))
    v1 = data.get("verdicts", {}).get("H1-F1", {}).get("verdict")
    decision = "GO" if v1 == "COMPROVADA" else "NO-GO"
    return {"decision": decision, "h1_verdict": v1,
            "reason": ("H1-F1 comprovada: Elo bate o grid no RPS" if decision == "GO"
                      else f"H1-F1 = {v1!r} — sem edge demonstrado sobre "
                           "o grid de largada (RELATORIO_FASE1.md)")}


def record_bet(*, market: str, selection: str, prob_model: float,
              decimal_odds: float, bankroll: float, real: bool = False,
              now: datetime | None = None,
              path: Path | str | None = None,
              gate_path: Path | str | None = None,
              approval_path: Path | str | None = None, **extra) -> dict:
    """Registra uma aposta (log append-only). `real=True` exige GO —
    levanta PermissionError caso contrário. `real=False` (default) é
    PAPER: útil para acompanhar o modelo sem apostar de verdade."""
    if real:
        require_real_money_allowed()
        gate = go_gate(gate_path)
        if gate["decision"] != "GO":
            raise PermissionError(
                f"aposta REAL bloqueada pelo gate ({gate['decision']}): "
                f"{gate['reason']}")
        approval = require_manual_approval(
            approval_path,
            fingerprint=bet_fingerprint(market=market, selection=selection,
                                        prob_model=prob_model,
                                        decimal_odds=decimal_odds,
                                        bankroll=bankroll), now=now)
        extra = {**extra, "manual_approval": approval}
    edge = prob_model * decimal_odds - 1.0
    stake = kelly_stake(prob_model, decimal_odds, bankroll)
    now = now or datetime.now(timezone.utc)
    record = {"id": now.strftime("%Y%m%dT%H%M%S%f"),
              "placed_at": now.isoformat(timespec="seconds"),
              "market": market, "selection": selection,
              "prob_model": round(prob_model, 4),
              "decimal_odds": decimal_odds, "edge": round(edge, 4),
              "bankroll_at_bet": bankroll, "stake": stake,
              "real": real, "settled": False, **extra}
    log = Path(path or _bets_log_path())
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def settle_bet(bet: dict, won: bool, *, now: datetime | None = None,
              path: Path | str | None = None) -> dict:
    """Liquidação: pnl = stake·(odds-1) se ganhou, -stake se perdeu.
    Append-only — grava um evento de SETTLEMENT novo (mesmo `id` do bet
    original), nunca reescreve o registro da aposta."""
    pnl = (bet["stake"] * (bet["decimal_odds"] - 1.0) if won
          else -bet["stake"])
    now = now or datetime.now(timezone.utc)
    settlement = {"id": bet["id"], "event": "settlement",
                 "settled_at": now.isoformat(timespec="seconds"),
                 "won": won, "pnl": round(pnl, 2)}
    log = Path(path or _bets_log_path())
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(settlement, ensure_ascii=False) + "\n")
    return settlement
