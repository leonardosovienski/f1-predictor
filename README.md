# f1-predictor

> **Status: Fase 0 — esqueleto funcional (2026-07-11).** Modelo Elo ordinal
> rodando, CI verde, vendor no predictor_core v1.1.0. **Backtest e operação
> real ainda NÃO existem** — nenhuma previsão daqui tem edge demonstrado.
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

# Testes e CI
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe scripts/ci_check.py
```

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
  data/f1_provider.py       # stub Jolpica (via validada; Fase 1 implementa)
data/drivers_f1.json        # grid 2026 real (22/11) com Elo semente
data/circuits_f1.json       # calendário 2026 real + características (metadados)
scripts/ci_check.py         # 3 barreiras: pytest, .ps1 ASCII, parse+smoke
tests/                      # 25 testes
vendor/predictor_core/      # v1.1.0 via sync_core (NÃO editar à mão)
```

## Roadmap

| Fase | Escopo | Status |
|---|---|---|
| 0 | Esqueleto: Elo ordinal, serving (race/h2h), CI | ✅ |
| 1 | Histórico via Jolpica + backtest prequential ordinal (RPS + nullref) | ⏳ prompt separado |
| 2 | Extensões: circuito, clima, grid de largada | ⏳ (cada uma = N+1) |
| 3 | Operação: odds, bet_log, settle | ⏳ (só após GO) |
