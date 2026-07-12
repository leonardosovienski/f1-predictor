# RELATÓRIO — Fase 4 do f1-predictor (empréstimos cross-ecossistema)

> Executado em 2026-07-12, a pedido explícito de importar padrões de
> outros consumidores do `predictor_core`: baseline H0 formal
> (brasileirao-predictor), rating por contexto (CS/LoL), decomposição de
> fatores (NBA), purging/embargo (previsao-cripto) e intensidade
> não-homogênea (wc-predictor-v2).

## Levantamento — o que existia de verdade para copiar

Antes de implementar, uma auditoria factual dos 6 projetos-irmãos (sem
inventar pontes): de 7 itens pedidos, **1 era cópia direta** de código
pronto (`PrequentialEvaluator` + bootstrap pareado do
brasileirao-predictor) e **1 já estava feito** (Plackett-Luce do core,
usado desde a Fase 0). Os outros 5 exigiam desenho novo — nenhum outro
domínio do ecossistema tinha `RatingBook` por contexto em uso, choque de
volatilidade pós-patch, Four Factors, ou intensidade não-homogênea
implementados. O vendor local do core também estava desatualizado
(v1.1.0 → v1.3.0) — sincronizado manualmente, ISOLADO a este worktree
(sem tocar os outros consumidores nem o checkout principal), antes de
qualquer coisa. A v1.3.0 trouxe `kernel/rating.py` (RatingBook genérico),
`testing/prequential.py` e `measurement/calibration.py` — usados aqui.

## Veredito das hipóteses pré-registradas

| Hipótese | Veredito | Evidência |
|---|---|---|
| **H0-F1-formal** — grid (H0) bate Elo puro, via `PrequentialEvaluator` + bootstrap pareado (caminho INDEPENDENTE da Fase 1) | **COMPROVADA** | RPS grid 0.1304 vs Elo 0.1410; bootstrap IC95 **[-0.0153, -0.0061]** (inteiro negativo); DM p=0.00003 |
| **H5-F1c** — bônus de contexto de circuito (`RatingBook` do core, power/downforce/balanced) bate Elo+grid | **REFUTADA** | RPS piorou: 0.1299 vs 0.1282 (p=0.25) |
| **H6-F1c** — penalidade de Reliability (DNF rolling) bate o blend anterior | **REFUTADA** | RPS 0.1289 vs 0.1299 (melhora, mas p=0.19 — não significativo) |
| **H7-F1c** — penalidade de Pit Efficiency bate o blend anterior | **REFUTADA** | w_pit=0 escolhido no dev — nenhum peso positivo ajudou |

O item 1 (grid como H0 formal) **reconfirma** a Fase 1 por um instrumento
diferente. Os itens 2/3/4 (contexto, reliability, pit) têm **mecanismo
validado em sintético** (sensibilidade e especificidade corretas no
harness) mas **não sobrevivem ao dado real** nesta janela de avaliação.

## Item 1 — H0 formal (brasileirao-predictor → f1-predictor)

Portamos `GridBaselineEvaluator` e `EloPlackettLuceEvaluator`, ambos
herdando de `predictor_core.testing.prequential.PrequentialEvaluator` —
o motor ABC controla o fatiamento temporal por CONSTRUÇÃO (anti-leakage
garantido, não por disciplina). Rodados sobre a MESMA lista de
observações (pareamento por índice garantido), o veredito usa bootstrap
pareado do ΔRPS por corrida (2000 reamostras), exatamente como o
`h4_verdict_bootstrap.py` do brasileirão. Harness próprio confirma
sensibilidade (grid informativo → COMPROVADA) e especificidade (grid
ruído → REFUTADA). **O resultado bate a Fase 1 no dígito** (RPS grid
0.1303→0.1304, Elo 0.1410) — dois instrumentos, mesma conclusão: **o
grid de largada é o piso oficial (H0) e nenhum modelo desta fase o
supera.**

## Itens 2-4 — rating por contexto + Four Factors (CS/LoL/NBA)

**Lição metodológica principal desta fase, descoberta duas vezes** (H6 e
H7 falharam da mesma forma na primeira tentativa do harness): se a
força/habilidade nova varia pelo MESMO canal que já determina a
ordem de chegada historicamente, **o Elo aprende sozinho** via as
próprias atualizações pareadas — o fator explícito só tem valor
incremental genuíno quando (a) a informação é PERSISTENTE mas o Elo,
limitado por K e por poucas corridas na janela real (~57-79), ainda não
convergiu a ela, e um estimador direto (taxa rolling, z-score) converge
mais rápido; ou (b) a informação é do "dia" (como o grid da Fase 2) e o
Elo, que só memoriza médias históricas, não pode vê-la de jeito nenhum.
Depois de isolar essa confusão nos geradores sintéticos (skill
totalmente FLAT + efeito binário/persistente independente), os três
harnesses (H5/H6/H7) confirmam CORRETAMENTE sensibilidade e
especificidade — a MECÂNICA está provada.

- **Contexto de circuito** (H5): `ContextRatingBook` usa
  `predictor_core.kernel.rating.RatingBook` de verdade — um por tipo
  (power/downforce/balanced), classificado a partir dos metadados
  qualitativos já declarados em `data/circuits_f1.json` desde a Fase 0 e
  NUNCA consumidos até aqui. Casamento do nome longo da Jolpica com o
  catálogo curto: 89/101 corridas (88%) — as 12 não casadas são 4 venues
  fora do calendário 2026 (Ímola, Barein, Jeddah, Paul Ricard). No dado
  real, o bônus de contexto **piora** o RPS — o sinal de especialização
  por tipo de circuito, se existe, é menor que o ruído da nossa amostra.
- **Reliability** (H6): taxa de DNF rolling (janela 12) por piloto. Ajuda
  DIRECIONALMENTE (RPS melhora vs contexto sozinho) mas não passa do
  limiar de significância (p=0.19) — não é REFUTADA por falta de
  mecanismo, é por falta de POTÊNCIA estatística na amostra real.
- **Pit Efficiency** (H7): duração rolling por equipe (z-score contra
  dispersão HISTÓRICA — nunca a da corrida corrente, que seria
  lookahead, já que o pit stop acontece DURANTE a corrida). Achado
  operacional: a Jolpica TEM esse dado real (`/pitstops.json`, cobertura
  92-101 de 101 corridas, após corrigir dois formatos de duração
  inconsistentes — `"M:SS.sss"` para paradas >60s e strings vazias em
  corridas antigas). No dado real, w_pit=0 no dev — nenhum peso ajudou.

**Nenhuma das três entra no serving**: o `fase4_params.json` grava
w=0 para as três (gate condicionado ao veredito, mesma disciplina da
Fase 2) — o serving continua no Elo+grid+Platt da Fase 2.

## Item CS/LoL — choque de volatilidade pós-patch

`VolatilityShock` (K temporariamente multiplicado por N corridas)
plugado no `BacktestElo` via parâmetro opcional. **Validado SÓ em
sintético**: um piloto sintético recebe um salto de força no meio da
série; com o choque disparado exatamente no salto, o RPS na janela
pós-salto cai de 0.1831 para 0.1801. **NÃO aplicado a dados reais** — a
Jolpica não tem calendário de atualizações aerodinâmicas por equipe, e
inventar datas de upgrade violaria a regra de ouro do projeto ("nada
inventado"). Fica documentado e testado como capacidade disponível para
o dia em que essa fonte existir.

## Item previsao-cripto — purging e embargo

`run_fase4` aceita `purge_races` (descarta as ÚLTIMAS corridas do dev da
BUSCA de peso) e `embargo_races` (descarta as PRIMEIRAS corridas da
avaliação das MÉTRICAS reportadas, mas o Elo/trackers continuam
atualizando por elas). Checagem de robustez no dado real: com
`purge_races=3, embargo_races=2`, os pesos escolhidos ficam **idênticos**
(w_ctx=1.5, w_rel=1.0, w_pit=0.0) e o RPS agregado varia menos que 0.001
— a conclusão da Fase 4 **não depende** de detalhes finos da fronteira
dev/eval.

## Item wc-predictor-v2 — intensidade não-homogênea (FORA DE ESCOPO)

**Não implementado, honestamente.** Intensidade não-homogênea de
DNF/Safety Car por FASE da corrida exigiria dado por VOLTA (quando cada
incidente aconteceu dentro da corrida) — a Jolpica só dá a classificação
FINAL (`results.json`) e paradas agregadas (`pitstops.json`, sem contexto
de por que a parada aconteceu). Isso exigiria uma fonte nova (FastF1, com
telemetria e mensagens de Safety Car por volta) — infraestrutura de
ingestão inteira, fora do escopo desta fase. Fica registrado como
capacidade candidata da Fase 5+, condicionada a essa fonte existir.

## Decisão

1. **GO/NO-GO de aposta: NO-GO** (inalterado — H0-formal reafirma H1-F1;
   nenhuma das novas features mudou isso).
2. **Modelo de produção**: continua o Elo+grid+Platt da Fase 2 — nenhuma
   feature da Fase 4 se qualificou.
3. **Mecânica validada, à espera de mais dado ou mais dados-fonte**:
   contexto de circuito, reliability e choque de volatilidade têm código
   testado e pronto; reavaliar quando houver mais temporadas no
   histórico (mais poder estatístico) ou uma fonte de calendário de
   upgrades.
4. **Achado factual reaproveitável**: a The Odds API foi confirmada (Fase
   2) como sem cobertura de F1; a Jolpica TEM pit stops reais (descoberta
   nesta fase) — útil para qualquer feature futura de boxe.

## Reprodução

```bash
.venv\Scripts\python.exe scripts/build_db.py        # já inclui pitstops
.venv\Scripts\python.exe scripts/run_fase4.py        # harness -> pre-registro -> backtest
.venv\Scripts\python.exe -m pytest tests/ -q         # 106 verdes
```

Artefatos versionados: `data/backtest_fase4.json`. Runtime (gitignored,
rebuildável): `data/fase4_params.json` (todos os pesos em 0 — nenhuma
feature comprovada).
