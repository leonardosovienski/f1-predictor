"""Operação — Fase 3. GATED: nenhuma aposta REAL sai daqui sem GO.

O gate é por ESTRATÉGIA (`strategy_id`), registrada em
`data/strategy_gates.json`. Cada entrada aponta para o veredito
pré-registrado que autoriza aquela estratégia especificamente — nunca um
veredito genérico do projeto. Ex.: `f1-winner-pre-event-elo-v1` lê H1-F1
("o Elo bate o grid de largada no RPS") de `data/backtest_fase1.json`; H1-F1
está REFUTADA (RELATORIO_FASE1.md) → essa estratégia é NO-GO. Uma estratégia
não registrada, ou sem `strategy_id`, é sempre NO-GO — o veredito de uma
estratégia nunca autoriza outra (mercados, regras de settlement e hipóteses
diferentes exigem trials econômicos independentes). `record_bet` recusa
`real=True` enquanto a estratégia informada não tiver GO; **não é ferramenta
de investimento** (declarado desde a Fase 0).

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


def _strategy_registry_path() -> Path:
    return ROOT / "data" / "strategy_gates.json"


def go_gate(strategy_id: str | None, *,
           registry_path: Path | str | None = None) -> dict:
    """Decisão GO/NO-GO para UMA estratégia registrada. Fail-closed em cada
    etapa: sem `strategy_id`, sem registro, estratégia não cadastrada, ou
    veredito ausente/diferente de COMPROVADA → NO-GO. O veredito de uma
    estratégia nunca é lido para autorizar outra — cada `strategy_id` só
    enxerga o `verdict_path`/`verdict_key` da sua própria entrada no
    registro (`data/strategy_gates.json`)."""
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        return {"decision": "NO-GO", "strategy_id": strategy_id, "verdict": None,
                "reason": "strategy_id é obrigatório — nenhum veredito "
                          "autoriza uma estratégia sem nome"}
    registry_file = Path(registry_path or _strategy_registry_path())
    if not registry_file.exists():
        return {"decision": "NO-GO", "strategy_id": strategy_id, "verdict": None,
                "reason": f"registro de estratégias ausente: {registry_file}"}
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"decision": "NO-GO", "strategy_id": strategy_id, "verdict": None,
                "reason": f"registro de estratégias ilegível: {exc}"}
    entry = registry.get("strategies", {}).get(strategy_id)
    if entry is None:
        return {"decision": "NO-GO", "strategy_id": strategy_id, "verdict": None,
                "reason": f"{strategy_id!r} não é uma estratégia registrada — "
                          "nenhum trial econômico a autoriza"}
    verdict_path = Path(entry["verdict_path"])
    if not verdict_path.is_absolute():
        verdict_path = ROOT / verdict_path
    verdict_key = entry["verdict_key"]
    if not verdict_path.exists():
        return {"decision": "NO-GO", "strategy_id": strategy_id, "verdict": None,
                "reason": f"veredito ausente para {strategy_id!r}: "
                          f"{verdict_path} não existe"}
    try:
        data = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"decision": "NO-GO", "strategy_id": strategy_id, "verdict": None,
                "reason": f"veredito ilegível para {strategy_id!r}: {exc}"}
    verdict = data.get("verdicts", {}).get(verdict_key, {}).get("verdict")
    decision = "GO" if verdict == "COMPROVADA" else "NO-GO"
    reason = (f"{verdict_key} comprovada: edge demonstrado para {strategy_id!r}"
              if decision == "GO" else
              f"{verdict_key} = {verdict!r} — sem edge demonstrado para "
              f"{strategy_id!r}")
    return {"decision": decision, "strategy_id": strategy_id, "verdict": verdict,
            "reason": reason}


def record_bet(*, market: str, selection: str, prob_model: float,
              decimal_odds: float, bankroll: float, real: bool = False,
              strategy_id: str | None = None,
              now: datetime | None = None,
              path: Path | str | None = None,
              registry_path: Path | str | None = None,
              approval_path: Path | str | None = None, **extra) -> dict:
    """Registra uma aposta (log append-only). `real=True` exige `strategy_id`
    E que a estratégia informada tenha GO — levanta PermissionError caso
    contrário. `real=False` (default) é PAPER: útil para acompanhar o
    modelo sem apostar de verdade (não exige `strategy_id`)."""
    if real:
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise PermissionError(
                "aposta REAL exige strategy_id — nenhum veredito autoriza "
                "uma estratégia sem nome")
        require_real_money_allowed()
        gate = go_gate(strategy_id, registry_path=registry_path)
        if gate["decision"] != "GO":
            raise PermissionError(
                f"aposta REAL bloqueada pelo gate ({gate['decision']}) para "
                f"estratégia {strategy_id!r}: {gate['reason']}")
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
              "strategy_id": strategy_id,
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
