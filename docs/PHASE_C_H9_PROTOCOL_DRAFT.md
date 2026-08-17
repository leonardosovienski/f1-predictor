# Protocolo candidato — `f1/h2h-post-qualifying/v1`

> **DRAFT v1 — NÃO APROVADO, NÃO CONGELADO E NÃO EXECUTÁVEL.**
> Este documento prepara uma decisão humana; não reabre `tracks.H2H`, não
> registra a estratégia em `data/strategy_gates.json` e não autoriza apostas.
> O freeze exige fonte aceita, revisão humana, commit e SHA-256 anteriores ao
> primeiro acesso a retornos fora da amostra.

## 1. Unidade governada e hipótese

- `strategy_id`: `f1/h2h-post-qualifying/v1`;
- mercado: `race_h2h`, nunca qualifying/sprint;
- decisão: depois do grid oficial e antes da corrida;
- unidade estatística primária: corrida, com duelos agrupados dentro dela;
- resultado econômico: retorno líquido de comissão, spread, slippage e voids.

Hipótese confirmatória: informação de Elo e grid, congelada antes do evento,
contém sinal residual sobre a probabilidade sem margem do preço executável e
esse sinal produz retorno líquido esperado positivo fora da amostra.

- H0 científica: o candidato não melhora log loss/Brier sobre o mercado.
- H0 econômica: retorno líquido esperado por aposta é menor ou igual a zero.
- GO exige rejeitar ambas; superar Elo ou grid isoladamente nunca basta.

H9 é independente de H1–H8. H1-F1 e H6-F1c permanecem refutadas.

## 2. Pré-condições de mercado

Nenhuma análise modelo-versus-mercado pode começar antes de:

1. ao menos uma fonte passar integralmente o contrato `SOURCE_ACCEPTED`;
2. uma decisão humana reabrir `tracks.H2H` somente para o protocolo aprovado;
3. existir export reproduzível com IDs, ambos os lados, timestamps, preços,
   comissão, liquidez, regra versionada e settlement;
4. a opção de qualidade ser escolhida antes de observar retornos;
5. nenhuma identidade canônica permanecer ambígua.

O marco `intermediate_descriptive_only` atual (250 duelos, 70% das corridas,
97% temporal, duas casas) permite apenas descrição. Não autoriza Stage 1. Para
candidatura a Stage 1, o piso existente é 500 duelos, 80% das corridas, 98%
temporal e três bookmakers, além de limites humanos ainda a congelar para
`both_sides_coverage`, `settlement_coverage` e `volume_coverage`.

## 3. População e causalidade

- somente pilotos canônicos inscritos na mesma corrida;
- universo de pares definido sem consultar resultado ou retorno;
- pares de companheiros são a população primária; ampliar a adversários de
  equipes diferentes cria outra versão;
- `decision_at`: instante fixo a congelar, posterior à publicação do grid e
  anterior ao `scheduled_start_utc`;
- quote elegível: integralmente publicada e disponível até `decision_at`;
- closing: última quote integralmente disponível antes do início, usada como
  baseline/CLV, nunca como informação da decisão;
- in-play e pós-evento permanecem arquivadas, mas inelegíveis;
- correção de grid, adiamento ou mudança de horário segue regra versionada;
- DNF/DNS/DSQ/cancelamento segue exclusivamente a regra da fonte, sem inferência.

## 4. Comparadores obrigatórios

Todos usam exatamente a mesma população, cutoff e settlement:

1. **Elo puro**: marginal H2H prequential existente;
2. **grid puro**: probabilidades H2H da escada de grid/Plackett–Luce congelada;
3. **blend Elo + grid**: peso aprendido somente no desenvolvimento temporal;
4. **mercado sem margem**: probabilidades dos dois lados normalizadas; exchange
   usa preço executável e comissão separada, sem inventar overround;
5. **candidato**: modelo pós-classificação especificado e hasheado no freeze.

O candidato não pode ser escolhido pela performance OOS. Feature, interação,
calibrador ou threshold novo depois de observar OOS cria `v2`.

## 5. Calibração e incerteza

Para cada comparador: Brier, log loss, reliability diagram, ECE com bins
congelados e calibração por faixa de preço. Acurácia não prova calibração.

A simulação Plackett–Luce/Gumbel mede incerteza de resultado condicionada aos
parâmetros. Ela **não** mede incerteza de Elo, peso do grid ou calibrador.
Incerteza de parâmetros deve ser estimada separadamente por refits prequential
dentro de bootstrap em blocos de corrida ou outro método aprovado no freeze.
As duas fontes de incerteza nunca serão somadas ou descritas como equivalentes.

## 6. Preço, execução e retorno

Para odds decimais executáveis `o` e comissão `c` sobre lucro:

```text
net_win = (o - 1) * (1 - c)
p_break_even = 1 / (1 + net_win)
edge = p_model - p_break_even
```

Spread, profundidade disponível, slippage, moeda/câmbio e limite de stake são
inputs obrigatórios. Quote sem capacidade executável suficiente é bloqueada,
não preenchida artificialmente. A análise primária usa stake fixa de uma
unidade; Kelly e reinvestimento são proibidos na confirmação.

O threshold de aposta, inclusive a opção de não apostar, será escolhido apenas
no desenvolvimento temporal e congelado. Se ambos os lados parecerem elegíveis,
o mercado é bloqueado como inconsistência.

## 7. Split temporal e prevenção de tuning

- sem split aleatório;
- burn-in anterior ao desenvolvimento apenas inicializa ratings;
- desenvolvimento escolhe blend, calibrador e threshold;
- validação temporal confirma sanidade uma única vez;
- teste OOS permanece lacrado até hashes, código e protocolo estarem congelados;
- temporadas concretas dependem da cobertura real e serão escolhidas sem olhar
  retornos, por regra de calendário registrada no freeze;
- duelos da mesma corrida nunca atravessam folds diferentes.

## 8. Testes confirmatórios

Primário científico: diferença pareada de log loss do candidato contra mercado
sem margem, com IC 95% e teste em blocos de corrida. Brier é coprimário somente
se assim aprovado antes do freeze; caso contrário, secundário.

Primário econômico: retorno médio líquido por unidade, com IC 95% por bootstrap
em blocos de corrida e teste unicaudal definido antes do OOS. Reportar ainda:

- P/L, número de apostas, corridas e duelos;
- CLV e calibração;
- drawdown máximo;
- Sharpe de retornos agregados por corrida, sem transformar corridas em apostas;
- resultados por fonte somente como diagnóstico, sem escolher a melhor depois.

O tamanho confirmatório não será fixado pela fórmula i.i.d. de apostas. Antes
do freeze, uma análise de poder sintética deve usar clusters de corrida, taxa de
void, frequência de aposta e custos conservadores. Amostra inferior ao número
congelado produz `INSUFFICIENT_POWER`, nunca GO.

## 9. Critério de continuidade e GO

Continuidade para paper trading exige cumulativamente:

- candidato melhor que Elo e grid em calibração/log loss;
- candidato melhor que mercado no teste confirmatório congelado;
- limite inferior do IC 95% do retorno líquido maior que zero;
- tamanho/poder, cobertura, settlement e liquidez aprovados;
- nenhum desvio crítico, lookahead ou identidade ambígua;
- revisão humana do pacote completo.

Qualquer falha é NO-GO. GO retrospectivo autoriza no máximo paper trading e
não altera `real_money_operation`. Paper trading terá janela, checkpoints e
stopping rules congelados em documento separado.

## 10. Artefatos exigidos no freeze

- protocolo aprovado, commit e SHA-256;
- `strategy_id`, versão do modelo e hashes de código/parâmetros;
- manifesto/licença e hashes do lote de mercado;
- regra de identidade, cutoff, closing e settlement;
- splits temporais e seeds;
- especificação de custos, liquidez e sizing;
- plano estatístico e análise de poder sintética;
- lista de exclusões permitidas e template de desvios;
- assinatura humana que reabre somente o escopo necessário.

Enquanto qualquer item estiver pendente, `f1/h2h-post-qualifying/v1` permanece
ausente de `data/strategy_gates.json` e o sistema retorna NO-GO.
