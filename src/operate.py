"""CLI de operação — Fase 3. GATED por padrão (NO-GO: veja betting.go_gate).

Uso:
    python -m src.operate --status
    python -m src.operate --paper-bet --h2h Verstappen Hamilton --circuit Monza --odds 1.80 --bankroll 1000
    python -m src.operate --paper-bet --h2h Verstappen Hamilton --circuit Monza --odds 1.80 --bankroll 1000 --real

O gate é por estratégia (`--strategy-id`, veja `data/strategy_gates.json`).
O padrão para o fluxo `--h2h` é `f1/h2h-post-qualifying/v1`, que HOJE não
está registrada — H2H contra preço de mercado nunca foi testada
economicamente, então o gate corretamente devolve NO-GO por falta de
trial, não pelo veredito de uma hipótese diferente (H1-F1, que é sobre
vencedor pré-evento, não H2H).

`--real` sem GO levanta PermissionError (comportamento intencional — não
é bypass, é a demonstração de que o gate está em vigor).
"""
import argparse
import json
import sys

from .betting import go_gate, record_bet
from .closure import require_open
from .model import F1EloModel

DEFAULT_H2H_STRATEGY_ID = "f1/h2h-post-qualifying/v1"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Operação de apostas — Fase 3 (gated)")
    ap.add_argument("--status", action="store_true",
                    help="mostra a decisão GO/NO-GO e sai")
    ap.add_argument("--paper-bet", action="store_true",
                    help="registra uma aposta (paper por padrão)")
    ap.add_argument("--h2h", nargs=2, metavar=("PILOTO_A", "PILOTO_B"))
    ap.add_argument("--circuit", default=None)
    ap.add_argument("--odds", type=float, help="odds decimal do mercado")
    ap.add_argument("--bankroll", type=float, default=1000.0)
    ap.add_argument("--real", action="store_true",
                    help="tenta registrar como aposta REAL (bloqueado sem GO)")
    ap.add_argument("--strategy-id", default=DEFAULT_H2H_STRATEGY_ID,
                    help="estratégia a consultar/usar no gate (ver "
                         "data/strategy_gates.json); padrão: "
                         f"{DEFAULT_H2H_STRATEGY_ID}")
    ap.add_argument("--approval-file",
                    help="JSON de aprovação manual, obrigatório junto com --real")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.status or not args.paper_bet:
        gate = go_gate(args.strategy_id)
        if args.json:
            print(json.dumps(gate, ensure_ascii=False, indent=2))
        else:
            print(f"Gate [{gate['strategy_id']}]: {gate['decision']} — {gate['reason']}")
        return 0

    if not (args.h2h and args.circuit and args.odds):
        print("--paper-bet exige --h2h A B --circuit C --odds O", file=sys.stderr)
        return 2

    model = F1EloModel()
    try:
        # H2H research is human-closed independently of the real-money gate.
        # Keep the pure model reusable for offline analysis, but no operation
        # (including paper logging) may execute a closed market.
        require_open("H2H")
        pred = model.predict_head_to_head(args.h2h[0], args.h2h[1], args.circuit)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 2

    try:
        bet = record_bet(market="h2h", selection=pred["driver_a"],
                         prob_model=pred["prob_a_beats_b"],
                         decimal_odds=args.odds, bankroll=args.bankroll,
                         real=args.real, strategy_id=args.strategy_id,
                         approval_path=args.approval_file,
                         circuit=pred["circuit"], driver_b=pred["driver_b"])
    except PermissionError as e:
        print(str(e), file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(bet, ensure_ascii=False, indent=2))
    else:
        modo = "REAL" if bet["real"] else "PAPER"
        print(f"[{modo}] {bet['selection']} @ {bet['decimal_odds']} "
              f"(P modelo {bet['prob_model']:.1%}, edge {bet['edge']:+.1%}) "
              f"— stake {bet['stake']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
