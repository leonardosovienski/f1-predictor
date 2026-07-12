# f1-predictor

> 🔒 **Laboratório SELADO em 2026-07-12** (commit `9415c7b`, branch
> único `main`, árvore limpa) — em espera por mais corridas de 2026
> antes de qualquer nova tentativa. Nenhuma pendência aberta.

> **Status: Fases 0-5 concluídas (2026-07-12).** Fase 1: **H1 REFUTADA**
> (Elo puro não bate o grid, RPS 0.1410 vs 0.1303). Fase 2: **H3-F1b** e
> **H4-F1b COMPROVADAS** — Elo+grid bate o Elo puro (RPS 0.1281 vs
> 0.1416) e Platt reduz o Brier do pódio (0.093→0.078, com ressalva de
> sobreconfiança nos extremos). Fase 3: operação (Kelly, bet_log, odds)
> construída mas **NO-GO** — o gate lê H1-F1, ainda refutada; The Odds
> API foi sondada e **não cobre F1**. Fase 4 (empréstimos
> cross-ecossistema): **H0-F1-formal COMPROVADA** (grid como piso
> oficial, reconfirmado via `PrequentialEvaluator` + bootstrap pareado
> do core); **H5/H6/H7-F1c REFUTADAS** (contexto de circuito, DNF
> rolling, pit efficiency — mecanismo validado em sintético, sem sinal
> suficiente no dado real). Fase 5: **H8-F1 REFUTADA** (choque estrutural
> de transição de regulamento, calibrado às cegas em sintético — direção
> certa em 2026 real, mas sem poder estatístico com só 9 corridas).
> Choque de volatilidade pós-patch (CS/LoL): mecanismo implementado, só
> validado em sintético — sem calendário real de upgrades. Também há um
> protocolo de validação viva (`docs/PROMPT_VALIDACAO_2026.md` +
> `scripts/validate_2026.py`) que retrodiz cada corrida de 2026 e prevê a
> próxima. Ver `docs/RELATORIO_FASE1.md` a `docs/RELATORIO_FASE5.md`.
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
data/drivers_f1.json        # grid 2026 real (22/11) com Elo semente
data/circuits_f1.json       # calendário 2026 real + características (metadados)
data/trials.json            # tentativas PRÉ-REGISTRADAS (versionado!)
data/backtest_fase1.json    # resultado completo do backtest Fase 1 (versionado)
data/backtest_fase2.json    # resultado completo do backtest Fase 2 (versionado)
data/backtest_fase4.json    # resultado completo do backtest Fase 4 (versionado)
scripts/build_db.py         # Jolpica → data/raw/ → data/f1.db (races+results+pitstops)
scripts/run_backtest.py     # Fase 1: harness → pré-registro → backtest → trials
scripts/run_fase2.py        # Fase 2: idem, para H3-F1b/H4-F1b
scripts/run_fase4.py        # Fase 4: idem, para H0-formal/H5/H6/H7-F1c
scripts/ci_check.py         # 3 barreiras: pytest, .ps1 ASCII, parse+smoke
docs/RELATORIO_FASE1.md     # RPS vs baselines, estratos, vereditos
docs/RELATORIO_FASE2.md     # blend, calibração, sondagem de odds, gate
docs/RELATORIO_FASE4.md     # H0-formal, contexto/reliability/pit, choque de patch, purge/embargo
tests/                      # 106 testes
vendor/predictor_core/      # v1.3.0 via sync manual escopado a este worktree (NÃO editar à mão)
```

## Roadmap

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: Elo ordinal, serving (race/h2h), CI | ✅ |
| 1 | Histórico via Jolpica + backtest prequential ordinal (RPS + nullref) | ✅ H1 refutada, H2 comprovada |
| 2 | Grid de largada como feature (blend), calibração Platt | ✅ H3-F1b e H4-F1b comprovadas |
| 3 | Operação: Kelly, bet_log, settle, odds | ✅ construída — 🔒 **NO-GO** (gate lê H1-F1, ainda refutada) |
| 4 | H0 formal, contexto de circuito, reliability, pit efficiency, choque de patch, purge/embargo | ✅ H0-formal comprovada; H5/H6/H7-F1c refutadas (mecanismo validado, sem sinal real) |
| 5 | Choque estrutural de transição de regulamento (H8-F1), calibrado às cegas em sintético | ✅ REFUTADA (direção certa, sem poder estatístico — reavaliar com mais corridas de 2026) |
| 6 | Intensidade não-homogênea de DNF/Safety Car (exige dado por volta — FastF1) | ⏳ (fonte não confirmada) |
