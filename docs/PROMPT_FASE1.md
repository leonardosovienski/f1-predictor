# PROMPT — Fase 1 do f1-predictor (backtest ordinal com RPS/nullref)

> Rascunho preparado em 2026-07-11, informado pelos ciclos de CS/LoL
> (prequential + governança) e pelas sinergias do ecossistema. Revisar
> antes de disparar.

**Projeto**: evoluir o f1-predictor da Fase 0 (Elo ordinal semeado) para um
modelo backtestado com corridas reais — o PRIMEIRO backtest ordinal do
ecossistema: RPS (`metrics.rps`) e `nullref.py` do core estreiam aqui.

**Contexto do que já existe**: F1EloModel (Plackett-Luce via Gumbel, H2H
fechado, update pareado com K de novato), grid 2026 real (22/11), calendário
2026, suíte 25 verdes, Jolpica validado como fonte (sem chave).

**Regras**: as de sempre — nada inventado, governança antes de resultado,
nenhuma aposta real nesta fase.

---

## PASSO 0 — Fonte (já validada; implementar)

`src/data/f1_provider.py` sai de stub: `fetch_results(season, round)` via
Jolpica (`/ergast/f1/<season>/<round>/results.json` — posição final, grid de
largada, status DNF) e `fetch_schedule(season)`. Cache local em `data/raw/`
(JSON por corrida; imutável pós-corrida). Rate limit de cortesia (Jolpica é
projeto comunitário: 1s entre chamadas, cache agressivo).

## PASSO 1 — Dados históricos

- Janela: **temporadas 2022–2026** (~100+ corridas; 2022-2025 = regulamento
  antigo, 2026 = novo — o corte de regulamento é um estrato do relatório).
- SQLite `data/f1.db`: tabela `races` (season, round, circuit, date) e
  `results` (season, round, driver, constructor, grid, position, status).
  Padrão db.py da plataforma (WAL, read-only P12).
- Pilotos fora do grid 2026 entram no Elo dinamicamente (semente default
  1400, como nos e-sports) — o Elo precisa do histórico completo de quem
  correu no período.

## PASSO 2 — Backtest prequential ORDINAL

Prever ANTES de atualizar, corrida a corrida:
- **Previsão**: ordenação completa via Plackett-Luce (o predict_race de
  hoje) restrita aos inscritos da corrida.
- **Métricas ordinais (core)**:
  - **RPS** da distribuição de posição prevista por piloto vs posição real
    (classes ordinais 1..N);
  - Brier/log-loss do VENCEDOR e do PÓDIO (binários derivados);
  - **nullref**: distribuição nula de ordenações aleatórias (e de
    "ordenação = grid de largada permutado") como piso — o RPS do modelo
    precisa estar abaixo do percentil 5 do nulo.
- **Baselines para Diebold-Mariano**:
  1. ordenação aleatória (nullref);
  2. **grid de largada** (o preditor forte e gratuito da F1 — se o Elo não
     bate o grid, não há modelo);
  3. ordenação pelo campeonato corrente (standings).
- DNF: piloto que abandona conta como última posição do grupo (declarar) —
  sensibilidade com exclusão de DNFs como leitura secundária.
- Burn-in: temporada 2022. K por corrida: base 24 / novato 40 (contrato do
  modelo). Update usa a ordem REAL de chegada.

## PASSO 3 — Governança

1. Harness do critério ordinal: campo sintético com forças verdadeiras
   conhecidas → RPS do modelo informado tem que bater o nulo e o baseline
   (sensibilidade); modelo sem informação (forças embaralhadas) tem que ser
   rejeitado (especificidade). Atestado emitido.
2. Pré-registro (`data/trials.json`, VERSIONADO):
   - **H1-F1**: "Elo/Plackett-Luce prequential tem RPS menor que o baseline
     de GRID DE LARGADA com DM p<0,05 (2023–2026, burn-in 2022)".
   - **H2-F1** (opcional): "Head-to-head entre companheiros de equipe:
     acerto > 50% com IC binomial fora do zero" — o H2H é o mercado real.
3. Backtest SÓ depois; resultados gravados nas trials.

## PASSO 4 — Recalibração e serving

- `data/ratings.json` da passada completa (Elo vivido — inclui o choque de
  regulamento 2026, que os standings atuais mostram: Antonelli líder,
  Verstappen 7º).
- Avaliar Platt no headline P(win)/P(pódio) SÓ SE a calibração medida
  justificar (lição do ecossistema: no CS comprovou, no LoL refutou — cada
  domínio decide com dado, e é tentativa N+1).

## PASSO 5 — Testes e entrega

- Novos testes: provider/parsers, prequential sem lookahead, RPS/nullref
  plumbing, DNF como última posição.
- Suíte ≥ 35 verdes, CI 3/3, tree limpa.
- Relatório `docs/RELATORIO_FASE1.md`: RPS vs nulo vs grid vs standings,
  estrato regulamento antigo × 2026, veredito H1-F1 (e H2-F1), e
  recomendação sobre Fase 1b (odds de F1 existem na The Odds API —
  `motorsport_f1`? confirmar no /v4/sports quando houver chave).
