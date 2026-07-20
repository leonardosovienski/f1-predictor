# H8 — validação histórica auxiliar

Executado em 2026-07-20 conforme protocolo congelado e commitado em
`57336fd`, antes da coleta histórica desta rodada.

## Resultado primário

| Medida | Resultado |
|---|---:|
| Transições | 2014, 2017, 2022 |
| Corridas | 24 (8 por transição) |
| RPS com choque | 0,158475 |
| RPS Elo comum | 0,150776 |
| Diferença (choque − comum) | +0,007699 |
| DM | 2,2909 |
| p bilateral | 0,03147 |
| Classificação pré-definida | `NOT_SUPPORTED_HISTORICALLY` |

O choque estrutural de fator 0,8 **piorou** o RPS histórico de forma
estatisticamente detectável no agregado. Não há base para ativá-lo.

## Heterogeneidade obrigatória

| Transição | n | RPS choque | RPS comum | Diferença | p DM |
|---:|---:|---:|---:|---:|---:|
| 2014 | 8 | 0,155497 | 0,148681 | +0,006816 | 0,2859 |
| 2017 | 8 | 0,159456 | 0,146023 | +0,013433 | 0,0681 |
| 2022 | 8 | 0,160472 | 0,157623 | +0,002849 | 0,6161 |

As três transições apontaram na mesma direção desfavorável. Isoladamente,
nenhuma atingiu `p<0,05`; o resultado primário foi definido como agregado.

## Integridade e limites

- fator, transições, janela, seed, métrica e alpha não foram recalibrados;
- 188 caches de entrada têm SHA-256 no artefato;
- replay com cache reproduziu exatamente todas as métricas;
- estudo retrospectivo: pode apoiar/refutar robustez histórica, mas não
  substitui evidência temporal forward;
- contador H8 forward permanece 0/15 e o gate permanece fechado;
- `data/fase5_params.json` continua com choque desativado.

Artefato: `data/backtest_h8_historical.json`.
