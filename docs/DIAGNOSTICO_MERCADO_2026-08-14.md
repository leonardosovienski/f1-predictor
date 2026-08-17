# Diagnóstico corrigido — modelo, mercado e governança (2026-08-14)

Este documento consolida uma revisão do estado real do projeto contra o
código (não contra os docs de fase), incluindo um achado arquitetural que
motivou uma correção de código no mesmo commit: o gate de aposta real era
acoplado a uma única hipótese (H1-F1) em vez de por estratégia. Ver
`data/strategy_gates.json` e `src/betting.py`.

## O que existe

**Modelo e previsão**: Elo por piloto; Plackett–Luce; Monte Carlo com 20.000
simulações via truque de Gumbel; probabilidades de vencedor, pódio, top 6 e
H2H; combinatória de ranking; previsão pré-evento; previsão pós-classificação
(`--grid`); blend Elo+grid; snapshots pré-evento; maturação; ledger; hashes;
cutoff temporal.

**Mercado**: contratos `QuoteRecord`/`SettlementRecord`/`MarketRecord`
(`src/market_collection/contracts.py`, Pydantic `extra="forbid"`); ordem
causal de timestamps; identidade canônica rígida (`f1-{season}-r{round}-race`);
classificação de elegibilidade; preservação de cotações in-play/pós-evento
com inelegibilidade explícita para decisão; arquivo isolado de mercado
(Zona 1, `COLLECTION_ONLY`); relatório de qualidade; regras de settlement
(`src/data/market_h2h.py`, Zona 2 — regras de DNF/DNS/DSQ nunca inferidas).

**Governança e capital**: closure → gate científico → aprovação manual
ligada ao fingerprint exato da ordem; Kelly fracionário (1/4) com teto de 5%
do bankroll; paper bet; capital real fechado; quotes pós-evento não podem
ser promovidas; aprovação manual não contorna closure nem gate.

## Incerteza: duas coisas diferentes

| | Estado |
|---|---|
| Incerteza de resultado | existe (20.000 simulações Monte Carlo) |
| Incerteza de parâmetros | não existe |

As simulações representam a distribuição dos resultados possíveis
condicionada aos parâmetros ATUAIS. Não representam incerteza sobre o
próprio rating Elo, peso do grid, força do construtor, efeito de circuito,
mudança regulatória ou qualidade dos parâmetros estimados. 20.000 simulações
reduzem erro de Monte Carlo, não corrigem confiança excessiva no modelo
subjacente.

## Estágios de previsão

| Estágio | Estado |
|---|---|
| Pré-evento | existe |
| Pós-classificação | existe |
| Pós-treinos (FP1/FP2/FP3) | não existe |

O gap real não é "não existem previsões progressivas" — pré-evento e
pós-quali já existem. É a ausência específica de uma camada pós-treino, que
exigiria dado por volta, pneu, stint, condições e tratamento da variável
latente de combustível. `src/data/fastf1_contract.py` é contrato de
exploração ponto-no-tempo, não integração operacional (FastF1 não está
instalado; nenhuma coleta ocorreu).

## Disponibilidade real de mercado

| | Contagem |
|---|---:|
| Fontes aceitas | 0 |
| Quotes persistidas | 0 |
| Corridas cobertas | 0 |
| Mercados avaliados | 0 |

Não existe hoje dataset real de mercado de F1 no projeto. `OddsProvider`
(`src/data/odds_provider.py`) não é integração parcial — é bloqueio
explícito: sem chave, `DataUnavailableError`; com chave, continua recusando,
porque a sondagem de 2026-07-12 encontrou zero cobertura de motorsport na
The Odds API.

## Regras de liquidação

| Fonte | Estado |
|---|---|
| Betfair, H2H motorsport | regra confirmada publicamente |
| Outras fontes (SportsDataIO, Sportradar) | não confirmadas |
| Comparação cross-book | ausente |

Não falta uma definição universal de settlement — existe uma definição
para Betfair. Falta: obter acesso e quotes reais, preservar a versão da
regra, validar outras fontes, reconciliar diferenças entre casas, e decidir
se mercados aparentemente equivalentes entre provedores são de fato
comparáveis.

## DNF e confiabilidade: hipótese testada, não lacuna operacional

`H6-F1c` testou confiabilidade via taxa de DNF rolling e foi **refutada**
(peso calibrado = 0, RPS sem melhora, nenhuma evidência incremental —
`data/trials.json`). O modelo vivo não tem DNF explícito, mas isso não é
uma lacuna nunca explorada — é um resultado negativo já registrado. Não há
razão para repetir a mesma feature. Uma nova hipótese de confiabilidade só
faria sentido com informação genuinamente nova (componentes trocados,
quilometragem de power unit, falhas por componente, upgrades, telemetria
precursora, mudança de regulamento) — dado prospectivo indisponível no teste
anterior.

## O problema arquitetural: gate acoplado a uma hipótese específica

Antes deste commit, `go_gate()` lia incondicionalmente o veredito de H1-F1
(`data/backtest_fase1.json`) para QUALQUER `record_bet(real=True)`,
independente do `market`/`selection` passados. Isso funcionava por acidente
feliz — H1-F1 está refutada, então tudo ficava NO-GO — mas não era seguro
por design: se `backtest_fase1.json` um dia lesse `COMPROVADA` (reexecução,
bug, ou arquivo trocado por engano), **qualquer** estratégia passaria no
gate, incluindo uma nunca testada. `operate.py --h2h` já exercia esse bug em
produção: apostas H2H eram gateadas pelo veredito de uma hipótese de
vencedor pré-evento, não por qualquer trial de H2H contra preço de mercado
(que nunca existiu).

**Correção aplicada nesta sessão**: `go_gate(strategy_id, ...)` agora lê um
registro (`data/strategy_gates.json`) que mapeia cada `strategy_id` ao seu
próprio `verdict_path`/`verdict_key`. Fail-closed em cada etapa: sem
`strategy_id`, sem registro, estratégia não cadastrada, ou veredito ausente
→ NO-GO. `record_bet(real=True)` agora exige `strategy_id` explicitamente.
`operate.py --h2h` usa por padrão `f1/h2h-post-qualifying/v1`, que **não
está registrada** — o NO-GO resultante agora é pelo motivo certo ("nenhum
trial autoriza esta estratégia"), não pelo veredito de uma hipótese
diferente. Testes de regressão em `tests/test_betting.py` provam que o
veredito de uma estratégia nunca vaza para outra no mesmo registro.

Isso não é uma proteção adicional além do closure global
(`real_money_operation: PERMANENTLY_BLOCKED`) — é uma camada independente.
O closure continua sendo o bloqueio mais externo e não foi alterado.

## Os dois bloqueios independentes

**Bloqueio A — Mercado.** Falta descobrir se é possível obter quotes H2H
com timestamps de abertura/fechamento, spread, liquidez, regra de
settlement e cobertura contínua a preço efetivamente acessível. Sem isso,
não há como testar edge econômico.

**Bloqueio B — Modelo.** O modelo atual perdeu para o grid público em
H1-F1, nunca foi avaliado contra preço de mercado (por ausência de quotes),
e não pode ser promovido só porque a infraestrutura de odds passe a
existir. Uma fonte de odds perfeita torna o teste possível — não produz
edge.

## Estratégia candidata e baselines obrigatórios

A estratégia mais próxima de ser testável é H2H pós-classificação: o
projeto já prevê H2H, o grid está disponível, a comparação é binária, a
regra de settlement da Betfair já foi diligenciada, e o estado pós-quali já
existe. Isso não significa que tenha edge — significa que é a hipótese
economicamente testável com menor distância do que já existe.

Uma futura avaliação H2H deveria comparar, no mínimo: Elo puro, grid puro,
blend Elo+grid, probabilidade implícita de mercado sem margem, e o modelo
candidato pós-quali. Superar apenas o Elo não é suficiente; superar apenas
o grid também não prova lucro — o teste real é contra o preço, líquido de
comissão.

## Estado canônico

| Dimensão | Estado real |
|---|---|
| Modelo ordinal | Avançado (metodologia), sem edge demonstrado contra grid ou mercado |
| Monte Carlo de resultados | Implementado |
| Incerteza de resultado | Implementada |
| Incerteza de parâmetros | Ausente |
| Pré-evento | Implementado |
| Pós-classificação | Implementado |
| Pós-treinos | Ausente |
| FastF1 operacional | Ausente |
| Contratos de mercado | Avançados |
| Regra Betfair H2H | Confirmada |
| Regras de outras casas | Não confirmadas |
| Fontes de odds aceitas | Zero |
| Quotes reais | Zero |
| Cobertura de corridas | Zero |
| Closing line | Ausente |
| Modelo de DNF vivo | Ausente (testado e refutado) |
| Gate de aposta real | Por estratégia (corrigido nesta sessão); antes, acoplado a H1-F1 globalmente |
| Edge contra grid | Não demonstrado; H1-F1 refutada |
| Edge contra mercado | Nunca testado (sem quotes) |
| Paper betting | Implementado |
| Capital real | Bloqueado (`PERMANENTLY_BLOCKED`) |
| Execução real | Ausente |
| Risco integrado | Ausente |

## Veredito

O projeto tem boa infraestrutura temporal, probabilística e de governança,
mas não possui nenhum dado real de mercado aceito. Em paralelo, seu modelo
atual não demonstrou edge: H1-F1 perdeu para o grid público, e nunca foi
testado contra preço por ausência de odds. A prioridade é desenvolver duas
trilhas independentes — aquisição de mercado (`docs/BETFAIR_BASIC_SAMPLE_HOWTO.md`,
`docs/SPORTSDATAIO_PRESALE_QUESTIONS_DRAFT.md`) e definição de uma
estratégia H2H pós-quali específica — que só se encontram no teste
econômico conjunto. Obter odds torna o teste possível; não torna o modelo
lucrativo. O gate agora reflete essa separação por construção: cada
estratégia futura precisa do seu próprio trial pré-registrado antes de
qualquer GO, e o veredito de uma nunca autoriza outra.
