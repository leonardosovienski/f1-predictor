# Diligência de provedores de odds — 2026-07-28

Levantamento das três fontes marcadas como `SOURCE_REQUIRES_HUMAN_DECISION` em
`data/market_h2h_feasibility.json`. Baseado apenas em documentação pública dos
fornecedores. Nenhuma conta foi criada, nenhum dado foi comprado, nenhum site
protegido foi automatizado.

**Este documento é evidência, não decisão.** Ele não altera status de fonte, não
cria Market DB, não toca gate e não reabre H1, H8 ou H2H. O
`market_h2h_feasibility.json` permanece `MARKET_H2H_NOT_FEASIBLE`, com 0 fontes
aceitas e 0 cotações. Mudança de status exige decisão humana registrada.

## Veredito

| Provedor | Status em 2026-07-21 | Recomendação | Fator decisivo |
|---|---|---|---|
| Sportradar/Betradar | `REQUIRES_HUMAN_DECISION` | rejeitar | API de F1 é stats-only e cobre só a temporada atual e a anterior |
| SportsDataIO | `REQUIRES_HUMAN_DECISION` | manter, sinal negativo | F1 ausente da lista de cobertura do produto de odds |
| Betfair Historical | `REQUIRES_HUMAN_DECISION` | único que avança | Motorsport confirmado no pacote e regra de liquidação H2H publicada |

## 1. Sportradar / Betradar — recomendo rejeitar

A API de racing/F1 é estatística, não de odds. Os endpoints são Competitor
Profile, Seasons, Stage Probabilities, Stage Schedule, Stage Summary e Team
Profile. "Stage Probabilities" são probabilidades de outright, não preços de
mercado; usar isso como proxy de odds seria a contaminação que o
`PAST_ATTEMPT_LEDGER.md` proíbe.

Matador: a documentação declara que a informação de temporada é limitada à
temporada atual e à anterior. Sem profundidade histórica não existe backtest.

A página de F1 da Betradar cita odds para treino, classificação e corrida e
"enhanced markets", mas não itemiza mercado nenhum, não menciona histórico, não
menciona liquidação e não publica preço. Produto B2B para operadores, não venda
para pessoa física.

## 2. SportsDataIO — mantém, com sinal pior

A favor: o Odds API declara exatamente os campos do nosso contrato — linhas de
abertura e fechamento mais todas as mudanças intermediárias, múltiplos
sportsbooks, timestamps de movimento de linha, feeds de verificação de
liquidação, e o motor deles trata mercados exóticos incluindo Head2Heads.

Contra: a lista de cobertura do produto de odds é NFL, MLB, NBA, NHL, CFB, CBB,
PGA, NASCAR, Soccer, UFC/MMA, Tennis e Olympics. F1 não aparece. Na página de
odds históricos (2019+, props e futures 2020+) F1 também não aparece. F1 existe
no catálogo apenas como API de estatística. A doc pública do F1 API não renderiza
conteúdo (shell JS), então não foi possível confirmar sequer a existência de
endpoint de odds para F1.

Preço não publicado; comercial gated. Estimativa não verificada: 4 a 5 dígitos
por ano.

## 3. Betfair Historical Data — o único caminho real

Confirmado em documentação oficial:

- Motorsports está explicitamente no pacote "Other Sports", que inclui **todos**
  os mercados liquidados na Exchange no mês, filtráveis por `MarketType`.
- Dados desde abril de 2015 (mercados AU/NZ desde outubro de 2016).
- Três tiers: BASIC gratuito (odds a cada 1 minuto, sem volume), ADVANCED (1
  segundo, com volume) e PRO (50 ms, com volume). JSON dentro de TAR.
- Regra de liquidação de H2H publicada nas regras de Motor Sport: em match bets
  vence quem termina à frente ou completa mais voltas. Isso resolve o tratamento
  de DNF, item 9 do contrato do ledger. Nenhum outro provedor entregou isso.

Três ressalvas duras:

1. **Liquidez desconhecida.** H2H de F1 na Exchange é nicho; o volume casado pode
   ser irrisório ou nulo na maioria das corridas. Não está documentado em lugar
   nenhum — só medindo.
2. **Uma casa, não três.** Todos os thresholds de
   `market_h2h_feasibility.json` exigem múltiplos bookmakers: 2 para o piloto
   diagnóstico, 3 para candidatura a Stage 1. Betfair sozinha é uma fonte. Mesmo
   completa, **nem o threshold mais frouxo é atendido** sem uma segunda fonte com
   F1 H2H comprovado — que nenhuma das outras duas comprovou.
3. **Geo e comissão.** O acesso a partir do Brasil é redirecionado para
   `betfair.bet.br`; `historicdata.betfair.com` não resolve DNS daqui e a página
   de regras retorna 404 no domínio BR. A comissão da entidade brasileira é 6,5%
   sobre o lucro líquido por mercado (fonte secundária, não confirmada em T&C
   oficial).

## 4. Achado não previsto: o mercado ficou mais difícil

A F1 nomeou a ALT Sports Data como fornecedora oficial de dados de apostas, com
odds precificadas entregues via OpenBet aos sportsbooks para a temporada 2026,
incluindo micro-mercados in-play (janelas de volta mais rápida, pit stops,
ultrapassagens, abandonos por faixa de voltas). Sportradar/ISG também entrou para
viabilizar in-play.

Leitura: quem está do outro lado da aposta em 2026 tem dados oficiais e latência
que nós não temos. Isso é evidência **contra** edge. Sugere-se registrar ALT
Sports Data como `SOURCE_NOT_APPLICABLE` (B2B para operadores).

## 5. A barra econômica, quantificada

O gate atual (`go_gate`) pergunta se o Elo bate a grid de largada. Essa é a barra
errada para dinheiro: o que autoriza aposta é bater o **preço**, líquido de
comissão. Num H2H de exchange precificado em 2,00 com comissão de 6,5%:

    p_break_even = 1 / (1 + (d-1)(1-c)) = 1 / 1,935 = 51,68%

É preciso acertar 51,7% num mercado que o preço diz ser 50/50 apenas para
empatar — ou seja, +1,7 ponto percentual de edge verdadeiro sobre a linha de
fechamento de uma exchange, que já embute a grid, o histórico público e, desde
2026, os dados oficiais.

Medição preservada em `data/backtest_fase1.json`: RPS do modelo 0,1399 contra
0,1303 da grid, DM p=0,00024, `modelo_melhor: false`. O modelo é pior que uma
informação pública e gratuita que o preço já contém.

## 6. O que continua sem resposta

Nenhum dos três comprova publicamente o item central: série histórica de
`race_h2h` de F1, com abertura e fechamento timestampados, dos dois lados, de
duas ou mais casas, com regra de liquidação versionada.

## 7. Próxima ação mínima (custo zero)

1. Medir a liquidez antes de gastar. O BASIC da Betfair é gratuito e cobre motor
   sport desde 2015; contar quantos mercados H2H de F1 existiram e com que volume
   decide sozinho se a trilha vive. Exige login em conta própria — ação humana,
   sem scraping.
2. Três e-mails de pré-venda com perguntas fechadas (sim/não sobre os 11 itens do
   contrato do ledger) para SportsDataIO, Sportradar e Betfair.

## Fontes

- https://sportsdata.io/live-odds-api
- https://sportsdata.io/historical-odds
- https://sportsdata.io/developers/api-documentation/f1
- https://developer.sportradar.com/racing/reference/f1-overview
- https://betradar.com/formula-1/
- https://support.developer.betfair.com/hc/en-us/articles/8085210924957-Which-Sports-Are-Included-in-the-Other-Sports-package
- https://support.developer.betfair.com/hc/en-us/articles/360002407732-What-data-is-provided-by-the-Historical-Data-service
- https://betfair-datascientists.github.io/modelling/dataSources/
- https://support.betfair.com/app/answers/detail/exchange-motor-sport-exchange-rules/
- https://corp.formula1.com/formula-1-appoints-alt-sports-data-as-official-betting-data-supplier-to-drive-growth-in-sports-betting/
- https://www.openbet.com/news/openbet-and-alt-sports-data-accelerate-new-official-formula-1-offering-for-sportsbooks
