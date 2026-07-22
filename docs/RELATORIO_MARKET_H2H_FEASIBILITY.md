# Gate de viabilidade de mercado H2H — Stage 0

Data da auditoria: 2026-07-21. Veredito: **MARKET_H2H_NOT_FEASIBLE**.

O projeto possui previsão H2H entre companheiros como capacidade técnica, mas
não possui uma base histórica de odds H2H de corrida, licenciada, reprodutível
e datada que permita testar edge econômico. Portanto não há backtest contra
mercado, ROI, Sharpe ou hipótese de mercado aprovada.

## Evidência de fontes

| Fonte | Estado | Decisão |
|---|---|---|
| The Odds API | `SOURCE_REJECTED` | A sonda autenticada já registrada listou 57 esportes sem F1/motorsport; não há endpoint F1 a integrar. |
| SportsDataIO | `SOURCE_REQUIRES_HUMAN_DECISION` | A documentação descreve F1 e warehouse histórico, porém preço, licença e H2H de corrida não foram confirmados. |
| Sportradar/Betradar | `SOURCE_REQUIRES_HUMAN_DECISION` | Material empresarial menciona H2H de F1, sem exportação/contrato compatível no workspace. |
| Betfair Historical Data | `SOURCE_REQUIRES_HUMAN_DECISION` | Feed histórico licenciado existe; cobertura F1 H2H e regra de liquidação não foram comprovadas. |

Nenhuma fonte é `SOURCE_ACCEPTED`; consequentemente existem **0 quotes**,
**0 duelos** e **0 corridas cobertas** no Market DB. Dados de OpenF1/FastF1
podem ser auxiliares de corrida, mas não são odds de mercado.

## Contratos implementados

`src/data/market_h2h.py` mantém banco SQLite separado (`market_h2h.db`) e
aceita somente `race_h2h` na sessão `race`, com IDs canônicos, timestamp UTC,
odds decimais finitas, par de oponentes, preço de abertura/fechamento dos dois
lados, margem, versão de regra de liquidação, batch e hash de proveniência.
Fonte não aceita não entra no banco. A regra de DNF/DNS/DSQ nunca é inferida:
sem regra de bookmaker compatível, o resultado é `BLOCKED`.

`src/data/fastf1_contract.py` é apenas contrato de exploração ponto-no-tempo:
exige versão/cache/download, cutoff, disponibilidade de clima/penalidades,
exclusões e correções. Dado posterior ao cutoff é rejeitado; combustível é
explicitamente latente. FastF1 não está instalado e não houve coleta.

## Opções de gate (não selecionadas automaticamente)

| Opção | Duelos | Cobertura de corridas | Timestamps | Casas | Efeito |
|---|---:|---:|---:|---:|---|
| Piloto diagnóstico | 100 | 60% | 95% | 2 | Não autoriza Stage 1. |
| Candidata a autorização Stage 1 | 500 | 80% | 98% | 3 | Só pode ser escolhida por decisão humana após aceitação de fonte. |

Mesmo a opção piloto não passa: a cobertura observada é zero. Nenhum limite
foi ajustado para produzir aprovação.

## Próxima janela legítima

Uma decisão humana pode contratar/autorizar uma fonte e fornecer um pequeno
export de teste. Antes de qualquer ingestão, validar licença, cobertura de
`race_h2h` (não quali/sprint), timestamps de captura, preços opening/closing,
regras DNF/DNS/DSQ, IDs de piloto/equipe, correções e proveniência. Somente
então escolher explicitamente uma opção de cobertura e considerar uma trial
N+1 de modelo versus mercado.
