# HANDOFF.md — f1-predictor

> ## 🏁 FASE 1 — BACKTEST ORDINAL (2026-07-12)
>
> **Backtest prequential rodado sobre 101 corridas reais (2022–2026 R9).
> H1-F1 REFUTADA: o Elo puro NÃO bate o grid de largada (RPS 0.1410 vs
> 0.1303, DM +4.43, p=0.00003). H2-F1 COMPROVADA: H2H entre companheiros
> 62.6% (253/404, Wilson95 [0.578, 0.672]). NO-GO para apostas.**
>
> Primeiro backtest ORDINAL do ecossistema — `metrics.rps`, `nullref` e
> Diebold-Mariano do core estrearam com cliente real. Fluxo de governança
> completo NA ORDEM: harness (controle positivo) → atestado → pré-registro
> (`data/trials.json`, versionado) → backtest → resultados nas trials.
>
> Decisões e lições da Fase 1:
> - **Semente do backtest = 1400 para todos** (a semente 2025 da Fase 0
>   seria lookahead dentro de 2022-2025); burn-in 2022, avaliação 79
>   corridas 2023–2026. K novato 40 (<22 corridas vistas), base 24.
> - **Nulo one-hot é armadilha**: o harness pegou — qualquer previsor flat
>   vence ordenações one-hot no RPS (especificidade falhou na 1ª versão).
>   O nulo correto é o **teste de PERMUTAÇÃO** (previsões do próprio
>   modelo, atribuição sorteada): preserva assertividade, destrói
>   informação. Ficou barato via matriz de custo RPS (equivalência com o
>   core testada).
> - **Baselines justos**: grid/standings viram forças pela escada
>   declarada da Fase 0 (1750→1350) e passam pelo MESMO Plackett-Luce.
> - O modelo carrega informação real (percentil 0 do nulo; esmaga o
>   uniforme) e é MELHOR que o grid no vencedor (Brier 0.831 vs 0.846) —
>   perde no meio do pelotão. Pior estrato: 2026 (choque de regulamento).
>   Pódio subconfiante nas faixas altas (Platt = candidata N+1, Fase 2).
> - **Jolpica**: 429 na primeira carga (retry/backoff implementado);
>   resposta vazia de corrida futura NÃO pode virar cache imutável (bug
>   corrigido + teste). Rate limit cortês 1s; cache `data/raw/` gitignored.
> - Serving agora usa o **Elo vivido** (`data/ratings.json`, só grid 2026;
>   filtro no model.py impede aposentados de entrar no grid do serving).
>   Novo topo: Verstappen 1696 > Norris 1680 (a semente 2025 dava Norris).
> - Suíte: **50 verdes** (25 novos); CI 3/3. Relatório:
>   `docs/RELATORIO_FASE1.md`.
>
> Próximo passo (Fase 2, cada variação = trial N+1 pré-registrada): grid
> de largada como FEATURE do modelo (Elo + grid, não Elo vs grid — alvo
> nº 1 do relatório), DNF/confiabilidade por equipe, Platt no headline.
> Fase 1b (odds): H2H é o único sinal comprovado — sondar `motorsport_f1`
> na The Odds API quando houver chave. Fase 3 segue 🔒 NO-GO.

> ## 🏎️ CRIAÇÃO (2026-07-11)
>
> **Projeto criado. Modelo Elo para pilotos implementado. Diferencial:
> previsão ordinal com RPS (métricas do core). Backtest e operação real
> pendentes.**
>
> Oitavo consumidor do predictor_core (v1.1.0, vendor via `sync_core
> --write`). Python 3.13 em `.venv`. PRIMEIRO domínio ordinal do ecossistema
> — o RPS e o nullref.py do core ganham cliente na Fase 1.
>
> Decisões da Fase 0:
> - **Plackett-Luce = extensão multiclasse do Elo**: forças 10^(elo/400),
>   ordenação simulada via truque de Gumbel (20k sims, seed 13,
>   determinístico); H2H em fórmula fechada CONSISTENTE com a marginal do
>   PL (mesma logística). Testes verificam Σwin=1, Σpódio=3, Σtop6=6.
> - **update_ratings pareado**: todo par da ordem de chegada, K/(n−1) por
>   par, K médio do par com novato=40 vs base=24 (progressão rápida),
>   soma zero. DNF/ausente fica de fora (não pontua nem perde).
> - **Dados REAIS via Jolpica** (api.jolpi.ca, sucessor mantido do Ergast,
>   sem chave — sondagem 2026-07-11): grid 2026 tem **22 pilotos/11 equipes**
>   (Cadillac entrou: Bottas+Pérez; o prompt assumia 20/10 — corrigido com
>   fonte). Standings 2026 correntes mostram a sacudida do regulamento novo
>   (Antonelli líder, Verstappen 7º) — mas a SEMENTE segue a regra do
>   prompt: campeonato FINAL de 2025 (Norris 1750 → linear → 1350;
>   Lindblad novato 1300; Bottas/Pérez retornantes 1400 declarado).
> - **Calendário 2026 real** (22 rodadas, incl. Madring novo). As
>   características de circuito (power/downforce/tire_wear) são estimativa
>   qualitativa DECLARADA — metadados para a Fase 1+; o modelo da Fase 0
>   não as consome (circuit/weather só são validados).
> - Governança desde o dia zero: PredictionPoint com value=ORDENAÇÃO
>   (formato do RPS), telemetria domínio `f1`, log append-only com override
>   por env; CI 3 barreiras; integridade do vendor + higiene de repo;
>   `.gitattributes` eol=lf.
> - Suíte: **25 verdes**.
>
> Próximo passo (Fase 1, prompt separado): histórico de corridas via
> Jolpica (`/f1/<season>/<round>/results.json`), backtest prequential
> ordinal — RPS do ranking previsto vs realizado, nullref (seletores
> aleatórios) como piso de significância, Diebold-Mariano vs baseline
> "grid de largada" — e o fluxo de governança da plataforma (harness →
> TrialRegistry → GO/NO-GO) antes de qualquer aposta.

## O que é o projeto

Laboratório de previsão de corridas de F1 (vencedor, pódio, top6,
head-to-head) — Fase 0. Roda 100% local. Idioma do projeto: português.
NÃO é ferramenta de investimento; nenhum edge foi demonstrado.

Máquina do Leo: Windows, `C:\Claude-projetos\Claude\f1-predictor`,
venv `.venv` (Python 3.13.14), atrás de proxy corporativo Volvo.
