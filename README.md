# f1-predictor

> **Status: Fase 1 — backtestado (2026-07-12).** Backtest prequential
> ordinal sobre 101 corridas reais (2022–2026): **H1 REFUTADA** — o Elo
> puro NÃO bate o grid de largada no RPS (0.1410 vs 0.1303, DM p=0.00003);
> **H2 COMPROVADA** — H2H entre companheiros acerta 62.6% (IC95 fora do
> zero). **NO-GO para apostas**; ver `docs/RELATORIO_FASE1.md`.
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

# Fase 1: histórico + backtest (governança: harness → trials → resultados)
.venv\Scripts\python.exe scripts/build_db.py       # Jolpica → data/f1.db
.venv\Scripts\python.exe scripts/run_backtest.py   # atesta, pré-registra, roda

# Testes e CI
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe scripts/ci_check.py
```

O serving usa o **Elo VIVIDO** do backtest quando `data/ratings.json`
existe (Verstappen 1696 no topo, não a semente 2025); sem ele, cai na
semente declarada da Fase 0.

Toda previsão é carimbada com `PredictionPoint` (matures_at = largada + 2h30;
para o ranking completo o `value` é a ORDENAÇÃO — o formato que o RPS
consome na Fase 1), registrada em log append-only (override por env) e
emitida na telemetria (domínio `f1`).

## Estrutura

```
config.yaml                 # sport, season, K base/novato, n_sims/seed
src/
  config.py                 # loaders + resolve_driver/resolve_circuit
  model.py                  # F1EloModel (race/h2h/update_ratings)
  predict.py                # CLI de serving + PredictionPoint + telemetria
  backtest.py               # prequential ordinal: RPS/nullref/DM + harness
  data/f1_provider.py       # cliente Jolpica (cache imutável, rate limit)
  data/db.py                # SQLite races/results (WAL, leitura read-only)
data/drivers_f1.json        # grid 2026 real (22/11) com Elo semente
data/circuits_f1.json       # calendário 2026 real + características (metadados)
data/trials.json            # tentativas PRÉ-REGISTRADAS (versionado!)
data/backtest_fase1.json    # resultado completo do backtest (versionado)
scripts/build_db.py         # Jolpica → data/raw/ → data/f1.db
scripts/run_backtest.py     # harness → pré-registro → backtest → trials
scripts/ci_check.py         # 3 barreiras: pytest, .ps1 ASCII, parse+smoke
docs/RELATORIO_FASE1.md     # RPS vs baselines, estratos, vereditos
tests/                      # 50 testes
vendor/predictor_core/      # v1.1.0 via sync_core (NÃO editar à mão)
```

## Roadmap

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: Elo ordinal, serving (race/h2h), CI | ✅ |
| 1 | Histórico via Jolpica + backtest prequential ordinal (RPS + nullref) | ✅ H1 refutada, H2 comprovada |
| 2 | Extensões: **grid de largada como feature** (alvo nº 1 do relatório), DNF/confiabilidade, calibração Platt | ⏳ (cada uma = N+1) |
| 3 | Operação: odds, bet_log, settle | 🔒 (NO-GO — sem edge sobre o grid) |
