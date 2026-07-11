# HANDOFF.md — f1-predictor

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
