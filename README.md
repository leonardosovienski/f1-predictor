# f1-predictor

## Coleta forward automática

`scripts/capture_next_forward_snapshot.py` consulta a agenda/classificação da
Jolpica, mas só publica um snapshot na janela iniciada duas horas após o quali
e encerrada exatamente na largada. Fora da janela é um no-op; resultado já
existente, grid incompleto, identidade divergente ou checkout/proveniência
inválidos continuam fail-closed. Instalação opcional no Task Scheduler:
`powershell -File scripts/install_forward_snapshot_task.ps1 -RunNow`.

> 🧪 **Validação histórica auxiliar H8 — 2026-07-20:** protocolo congelado
> no commit `57336fd` antes da coleta; 24 corridas nas transições 2014,
> 2017 e 2022. O choque de fator 0,8 piorou o RPS (`0,158475` contra
> `0,150776`; delta `+0,007699`; DM `p=0,03147`):
> **`NOT_SUPPORTED_HISTORICALLY`**. O mecanismo permanece desativado.
> Isto reforça a refutação, mas não é amostra forward: H8 segue 0/15.

> ✅ **Fechamento técnico local — 2026-07-20**: auditoria final confirmou
> `H8_REQUIRED_RACES = 15`, **10 corridas disputadas/retropreditas** e
> **0 corridas forward maturadas válidas para H8**. Três bugs operacionais
> foram corrigidos sem mudar ciência: publicação de snapshot agora é
> realmente atômica e limpa falhas parciais; maturação anterior à largada é
> rejeitada e revalidada na elegibilidade; replay de resultado oficial
> corrigido remove linhas obsoletas. Ratings e parâmetros não finitos
> (NaN/Inf) também passam a falhar fechados. A ingestão valida o lote
> completo antes de substituir uma corrida (identidade, posições, grid,
> DNF, pontos e pitstops); payload inválido não apaga o resultado anterior.
> Suíte: **152 testes verdes**;
> `scripts/ci_check.py`: 3/3 barreiras verdes. Veredito: **PASS LOCAL COM
> GATE CIENTÍFICO FECHADO**.

> 🐛 **Bug de ingestão corrigido em 2026-07-20**: a Jolpica usa `"Lapped"`
> (2023+) em vez de `"+N Lap(s)"` (só 2022) para o mesmo conceito
> (classificado, voltas atrás do líder); `is_dnf()` só reconhecia o
> formato antigo e marcava 363 resultados reais como DNF indevidamente.
> Corrigido; banco reconstruído do cache local e **todo** o pipeline
> científico (Fases 1,2,4,5) reexecutado — os 9 vereditos permaneceram
> idênticos, só os números mudaram. Ver `HANDOFF.md` para a tabela
> completa antes/depois.

> 🔒 **Coleta científica forward iniciada em 2026-07-15** (commit de base
> `19e3ec4`; `main` e branch atual reconciliadas). R1–R10 permanecem apenas
> retropredições reproduzíveis (R10 = GP da Bélgica, ingerido 2026-07-19):
> há **0 corridas temporalmente válidas para H8** — o diretório `snapshots/`
> ainda não existe, a coleta forward declarada não produziu nenhum snapshot
> real ainda. Novas corridas usam snapshots PRE_EVENT imutáveis; o gate
> real segue **NO-GO** e H8 permanece bloqueada até 15 corridas com par
> PRE_EVENT→MATURED válido (não 15 corridas disputadas).

> **Status: Fases 0-5 concluídas (2026-07-12), reexecutadas com dado
> corrigido em 2026-07-20** (ver banner acima). Fase 1: **H1 REFUTADA**
> (Elo puro não bate o grid, RPS 0.1399 vs 0.1303). Fase 2: **H3-F1b** e
> **H4-F1b COMPROVADAS** — Elo+grid bate o Elo puro (RPS 0.1274 vs
> 0.1407) e Platt reduz o Brier do pódio (0.0930→0.0794, com ressalva de
> sobreconfiança nos extremos). Fase 3: operação (Kelly, bet_log, odds)
> construída mas **NO-GO** — o gate lê H1-F1, ainda refutada; The Odds
> API foi sondada e **não cobre F1**. Fase 4 (empréstimos
> cross-ecossistema): **H0-F1-formal COMPROVADA** (grid como piso
> oficial, reconfirmado via `PrequentialEvaluator` + bootstrap pareado
> do core); **H5/H6/H7-F1c REFUTADAS** (contexto de circuito, DNF
> rolling, pit efficiency — mecanismo validado em sintético, sem sinal
> suficiente no dado real). Fase 5: a reavaliação **H8-F1 está
> `CLOSED_BY_HUMAN_DECISION`**, com contador final 0/15 `VALID_FOR_H8`; ela
> não foi aprovada nem refutada e não reabre H1-F1. Choque de volatilidade
> pós-patch (CS/LoL): mecanismo
> implementado, só validado em sintético — sem calendário real de
> upgrades. Também há um protocolo de validação viva
> (`docs/PROMPT_VALIDACAO_2026.md` + `scripts/validate_2026.py`) que
> retrodiz cada corrida de 2026 e prevê a próxima. Ver
> `docs/RELATORIO_FASE1.md` a `docs/RELATORIO_FASE5.md`.
> Não é ferramenta de investimento.

Laboratório de previsão de corridas de **Fórmula 1** (vencedor, pódio, top6
e head-to-head), oitavo consumidor do ecossistema `predictor_core` — e o
**primeiro domínio ORDINAL**: o resultado é uma ordenação de 22 posições,
exatamente o problema para o qual o core tem `metrics.rps` e `nullref.py`
esperando cliente (Fase 1).

## Modelo (Fase 0)

- **Elo por piloto**; força `s_i = 10^(elo/400)` (Bradley-Terry).
- **Ordenação da corrida ~ Plackett-Luce** com essas forças — a extensão
  multiclasse natural do Elo: a marginal P(i à frente de j) é a logística
  clássica. Win/pódio/top6 saem de 20.000 simulações via truque de Gumbel
  (determinístico com a seed do config).
- **Head-to-head** (o mercado mais comum das casas): fórmula fechada,
  consistente com a marginal do Plackett-Luce.
- **update_ratings**: comparações pareadas da ordem de chegada (todo par),
  K/(n−1) por par com **K de novato maior** (40 vs 24), soma zero,
  persistido em `data/ratings.json`. DNF/ausente não pontua nem perde.
- `circuit`/`weather` são validados mas **não ajustam na Fase 0** (declarado)
  — as características por circuito já vivem em `data/circuits_f1.json`
  como metadados da extensão.

**Dados reais (Jolpica, sucessor do Ergast — sondado em 2026-07-11):**
grid 2026 = **22 pilotos / 11 equipes** (a Cadillac entrou; o prompt de
criação assumia 20/10 — a realidade venceu). Elo semeado pelo campeonato
FINAL de 2025: Norris campeão → 1750, linear até 1350; Lindblad (novato) →
1300; Bottas/Pérez (retornantes pela Cadillac) → 1400 declarado. Calendário
2026 real com 22 rodadas.

## Uso

```bash
.venv\Scripts\python.exe -m src.predict --circuit Monza --weather dry
.venv\Scripts\python.exe -m src.predict --circuit Monza --market podium
.venv\Scripts\python.exe -m src.predict --head-to-head Verstappen Hamilton --circuit Monaco --json

# pós-quali (Fase 2): grid como feature (blend Elo+grid, w vivido)
.venv\Scripts\python.exe -m src.predict --circuit Hungaroring --grid Norris:1 Verstappen:2 ...

# Fase 1: histórico + backtest (governança: harness → trials → resultados)
.venv\Scripts\python.exe scripts/build_db.py       # Jolpica → data/f1.db
.venv\Scripts\python.exe scripts/run_backtest.py   # atesta, pré-registra, roda

# Fase 2: grid como feature + calibração Platt (N+1)
.venv\Scripts\python.exe scripts/run_fase2.py

# Fase 3: operação (GATED — leia antes de usar)
.venv\Scripts\python.exe -m src.operate --status
.venv\Scripts\python.exe -m src.operate --paper-bet --h2h Verstappen Hamilton --circuit Monza --odds 1.80

# Fase 4: H0 formal + contexto de circuito + reliability + pit efficiency
.venv\Scripts\python.exe scripts/run_fase4.py

# Fase 5: H8-F1, choque estrutural de transição de regulamento
.venv\Scripts\python.exe scripts/run_fase5.py

# Validação viva: retrodiz 2026 disputado + prevê a próxima corrida
.venv\Scripts\python.exe scripts/validate_2026.py

# Testes e CI
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe scripts/ci_check.py
```

O serving usa o **Elo VIVIDO** do backtest quando `data/ratings.json`
existe (Verstappen no topo, não a semente 2025); sem ele, cai na semente
declarada da Fase 0. Com `--grid`, usa o **blend Elo+grid** vivido
(`data/fase2_params.json`) — sem esse arquivo, ou se o veredito tivesse
sido refutado, cai automaticamente no Elo puro.

Toda previsão é carimbada com `PredictionPoint` (matures_at = largada + 2h30;
para o ranking completo o `value` é a ORDENAÇÃO — o formato que o RPS
consome na Fase 1), registrada em log append-only (override por env) e
emitida na telemetria (domínio `f1`).

## Estrutura

```
config.yaml                 # sport, season, K base/novato, n_sims/seed
src/
  config.py                 # loaders + resolve_driver/resolve_circuit
  model.py                  # F1EloModel (race/h2h/update_ratings/grid-blend)
  predict.py                # CLI de serving + PredictionPoint + telemetria
  backtest.py               # prequential ordinal: RPS/nullref/DM + blend + Platt + H0-formal + Fase4 + harnesses
  context_factors.py         # RatingBook por contexto, Reliability, Pit Efficiency, VolatilityShock
  betting.py                 # Kelly, gate de GO, bet_log append-only, settle
  operate.py                 # CLI de operação (GATED)
  data/f1_provider.py       # cliente Jolpica (cache imutável, rate limit, pitstops)
  data/db.py                # SQLite races/results/pitstops (WAL, leitura read-only)
  data/odds_provider.py     # cliente The Odds API (sondado: sem F1)
  snapshots.py               # cadeia forward PRE_EVENT/MATURED imutável (snapshot pré-corrida, maturação sem reexecutar o modelo)
data/drivers_f1.json        # grid 2026 real (22/11) com Elo semente
data/circuits_f1.json       # calendário 2026 real + características (metadados)
data/trials.json            # tentativas PRÉ-REGISTRADAS (versionado!)
data/backtest_fase1.json    # resultado completo do backtest Fase 1 (versionado)
data/backtest_fase2.json    # resultado completo do backtest Fase 2 (versionado)
data/backtest_fase4.json    # resultado completo do backtest Fase 4 (versionado)
data/backtest_fase5.json    # resultado completo do backtest Fase 5 — H8-F1 (versionado)
data/backtest_h8_historical.json # robustez histórica auxiliar (24 corridas; não conta forward)
data/fase2_params.json      # w do blend + Platt vividos (runtime, gitignored)
data/fase5_params.json      # fator de choque calibrado — shrink_factor=0.0 no serving (runtime, gitignored)
data/validacao_2026_ultima.json  # última rodada de validate_2026.py (runtime, gitignored)
scripts/build_db.py         # Jolpica → data/raw/ → data/f1.db (races+results+pitstops)
scripts/run_backtest.py     # Fase 1: harness → pré-registro → backtest → trials
scripts/run_fase2.py        # Fase 2: idem, para H3-F1b/H4-F1b
scripts/run_fase4.py        # Fase 4: idem, para H0-formal/H5/H6/H7-F1c
scripts/run_fase5.py        # Fase 5: idem, para H8-F1 (idempotente)
scripts/run_h8_historical.py # replay congelado 2014/2017/2022
scripts/validate_2026.py    # validação viva: retrodiz 2026 + prevê a próxima corrida
scripts/ci_check.py         # 3 barreiras: pytest, .ps1 ASCII, parse+smoke
docs/RELATORIO_FASE1.md     # RPS vs baselines, estratos, vereditos
docs/RELATORIO_FASE2.md     # blend, calibração, sondagem de odds, gate
docs/RELATORIO_FASE4.md     # H0-formal, contexto/reliability/pit, choque de patch, purge/embargo
docs/RELATORIO_FASE5.md     # H8-F1, protocolo sintético, leitura honesta sem poder estatístico
docs/PROTOCOLO_H8_HISTORICO.md / RELATORIO_H8_HISTORICO.md # pré-registro e resultado auxiliar
docs/PROMPT_VALIDACAO_2026.md  # protocolo da validação viva
tests/                      # 155 testes
vendor/predictor_core/      # v1.3.1 via sync manual escopado a este worktree (NÃO editar à mão)
```

## Roadmap

> ## Stage 0 — viabilidade de mercado H2H (2026-07-21)
>
> **MARKET_H2H_NOT_FEASIBLE.** O modelo H2H é capacidade técnica, não
> evidência econômica: há 0 fontes aceitas e 0 odds históricas elegíveis. O
> contrato fail-closed exige fonte licenciada, timestamp, preço bilateral,
> margem, proveniência e regra de settlement. Nenhuma aposta real, ROI/Sharpe
> ou trial modelo-vs-mercado é autorizado. Consulte
> `docs/RELATORIO_MARKET_H2H_FEASIBILITY.md`. H1-F1 segue refutada e não pode
> ser reaproveitada como prova de edge de mercado.
> O inventário não destrutivo das tentativas está em
> `docs/PAST_ATTEMPT_LEDGER.md`; o gate apresenta opções mínima,
> intermediária e conservadora, mas aguarda escolha humana.

> ## Fechamento autorizado — 2026-07-23
>
> O registro único `data/authorized_closure.json` encerra **H2H** e a
> reavaliação **H8** como `CLOSED_BY_HUMAN_DECISION`. H1-F1 permanece
> `HYPOTHESIS_REFUTED`; a operação original é `NO_GO_CONFIRMED`; operação com
> dinheiro real é permanentemente bloqueada. H2H/H8 não foram aprovadas nem
> refutadas por este encerramento. O job exclusivo `f1-forward-snapshot` foi
> desabilitado; o monitor transversal de outros preditores não foi tocado.

> ## Coleta arquivística COLLECTION_ONLY (2026-07-23)
>
> `scripts/run_archival_collection.py` e o job semanal
> `f1-archival-collection` arquivam somente calendário e resultados oficiais
> em `data/collection_only/`. Não executam H1/H8/H2H, não criam pares, trials,
> gates, avaliações, Market DB ou dados de apostas. Operação:
> `docs/COLLECTION_ONLY_HANDOFF.md`.

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: Elo ordinal, serving (race/h2h), CI | ✅ |
| 1 | Histórico via Jolpica + backtest prequential ordinal (RPS + nullref) | ✅ H1 refutada, H2 comprovada |
| 2 | Grid de largada como feature (blend), calibração Platt | ✅ H3-F1b e H4-F1b comprovadas |
| 3 | Operação: Kelly, bet_log, settle, odds | ✅ construída — 🔒 **NO-GO** (gate lê H1-F1, ainda refutada) |
| 4 | H0 formal, contexto de circuito, reliability, pit efficiency, choque de patch, purge/embargo | ✅ H0-formal comprovada; H5/H6/H7-F1c refutadas (mecanismo validado, sem sinal real) |
| 5 | Reavaliação de choque estrutural de transição de regulamento (H8-F1) | 🔒 `CLOSED_BY_HUMAN_DECISION`; 0/15 `VALID_FOR_H8`, sem aprovação, refutação ou edge econômico |
| 6 | Intensidade não-homogênea de DNF/Safety Car (exige dado por volta — FastF1) | ⏳ (fonte não confirmada) |
