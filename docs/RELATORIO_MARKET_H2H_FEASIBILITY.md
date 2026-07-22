# Gate de viabilidade de mercado H2H — Stage 0

Data da auditoria: 2026-07-21. Veredito: **MARKET_H2H_NOT_FEASIBLE**.

O projeto possui previsão H2H entre companheiros como capacidade técnica, mas
não possui uma base histórica de odds H2H de corrida, licenciada, reprodutível
e datada que permita testar edge econômico. Portanto não há backtest contra
mercado, ROI, Sharpe ou hipótese de mercado aprovada.

## Evidência de fontes

| Fonte | Estado | Licença/export/cobertura e limitações |
|---|---|---|
| The Odds API | `SOURCE_REJECTED` | Sonda autenticada local: 57 esportes, sem F1/motorsport. Docs atuais também não listam F1 na cobertura histórica. Sem export elegível. |
| SportsDataIO | `SOURCE_REQUIRES_HUMAN_DECISION` | Docs descrevem F1, GET e warehouse de odds >30 dias; preço/licença, H2H de corrida, número de duelos, casas, timestamps, settlement e export precisam de confirmação comercial. |
| Sportradar/Betradar | `SOURCE_REQUIRES_HUMAN_DECISION` | Material empresarial menciona F1/H2H/histórico, sem contrato, custo ou amostra de export no workspace. Cobertura e viés de seleção desconhecidos. |
| Betfair Historical Data | `SOURCE_REQUIRES_HUMAN_DECISION` | Especificação confirma feed histórico e campos de preço/runner; F1 H2H, cobertura, comissão/settlement e formato utilizável precisam de confirmação. |
| OddsPapi | `SOURCE_PARTIALLY_ACCEPTED` | Docs declaram API, snapshots e histórico multi-bookmaker, mas não comprovam F1, H2H de corrida, período, custo, opening/closing, settlement ou termos para este uso. Diligência apenas. |

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

| Opção | Duelos | Cobertura de corridas | Timestamps | Casas | Impacto e limitação |
|---|---:|---:|---:|---:|---|
| Mínima exploratória | 100 | 60% | 95% | 2 | Diagnóstico de integridade somente; pouca potência e não autoriza Stage 1. |
| Intermediária | 250 | 70% | 97% | 2 | Permite medir estabilidade descritiva; ainda vulnerável a concentração de pilotos/equipes. |
| Conservadora (recomendada) | 500 | 80% | 98% | 3 | Melhor base para autorizar shadow prospectivo; ainda não libera capital nem escolhe hipótese. |

Mesmo a opção mínima não passa: a cobertura observada é zero. Nenhum limite
foi ajustado para produzir aprovação. A escolha entre as três opções é decisão
humana obrigatória; só depois dela poderá ser registrada uma trial N+1.

## Ledger e contrato detalhado

O histórico completo de grid, posição final, H1, H8, ratings, DNF, FastF1,
telemetria, treino, classificação, ritmo, H2H, datasets, fontes, cobertura,
gates e backtests está em `docs/PAST_ATTEMPT_LEDGER.md`. O contrato de mercado
exige provenance e tratamento explícito de DNF/DNS/DSQ, ambos DNF, corrida
cancelada e resultado corrigido; nenhum desses casos é inferido da classificação
esportiva para uma casa de aposta.

## Próxima janela legítima

Uma decisão humana pode contratar/autorizar uma fonte e fornecer um pequeno
export de teste. Antes de qualquer ingestão, validar licença, cobertura de
`race_h2h` (não quali/sprint), timestamps de captura, preços opening/closing,
regras DNF/DNS/DSQ, IDs de piloto/equipe, correções e proveniência. Somente
então escolher explicitamente uma opção de cobertura e considerar uma trial
N+1 de modelo versus mercado.
