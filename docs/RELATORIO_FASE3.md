# RELATÓRIO — Fase 3 do f1-predictor (operação gated)

## Decisão

**NO-GO.** A Fase 3 construiu apenas a superfície operacional: Kelly
fracionário, teto de stake, log append-only e liquidação. Ela não introduziu
nem reavaliou hipótese científica.

O gate consulta H1-F1 em `data/backtest_fase1.json`. H1-F1 está REFUTADA:
o Elo não supera o grid de largada no RPS. Consequentemente, qualquer aposta
real é bloqueada. O fechamento humano posterior em
`data/authorized_closure.json` também bloqueia permanentemente dinheiro real.

## Escopo e limites

- Paper logging não constitui evidência de edge nem libera operação real.
- Mercado H2H está `CLOSED_BY_HUMAN_DECISION` e não deve ser executado.
- `MARKET_H2H_NOT_FEASIBLE`: zero fontes e zero quotes históricos aceitos.
- The Odds API não é fonte de odds de F1 neste projeto.

Este relatório é o documento canônico da Fase 3; ver também
`docs/RELATORIO_MARKET_H2H_FEASIBILITY.md` e `HANDOFF.md`.
