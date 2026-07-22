# PAST_ATTEMPT_LEDGER — f1-predictor

Registro não destrutivo em 2026-07-22. Um resultado negativo não pode ser
apagado, reinterpretado como edge, nem reaberto trocando métrica, limiar ou
população depois do fato.

| Pergunta/área | Dados e método | Resultado preservado | Decisão |
|---|---|---|---|
| Grid e posição final | 101 corridas 2022–2026; Elo/PL versus grid, RPS/DM | H1-F1 refutada: Elo RPS 0,1399 vs grid 0,1303; p=0,0002 | Não reabrir como hipótese de edge. |
| Ratings e H2H | Elo prequential; pares de companheiros | H2-F1 tem acerto técnico, mas não contém preços de mercado | Capacidade de previsão não é edge econômico. |
| Grid como feature | H3/H4, desenvolvimento separado e avaliação cega | Grid melhora/calibra o modelo; não supera mercado | Não autoriza aposta. |
| DNF/reliability e pit | H5/H6/H7 | Refutadas ou efeito nulo no histórico disponível | Não ajustar para salvar hipótese. |
| H8/regulamento | Forward exige 15 pares PRE_EVENT→MATURED; replay histórico auxiliar | 0/15 forward; replay auxiliar desfavorável | Trilha separada, sem efeito no NO-GO econômico. |
| FastF1/telemetria/treino/classificação/ritmo | Nenhum dataset FastF1 aceito; combustível é latente | Sem coleta e sem features para backtest econômico | Somente contrato ponto-no-tempo; não modelar. |
| Odds/The Odds API | Sonda autenticada local anterior | Sem F1/motorsport no catálogo observado | `SOURCE_REJECTED`; não repetir sem evidência nova. |
| Odds/SportsDataIO | Docs públicas: F1, GET, warehouse histórico | Licença, preço, H2H de corrida e export não comprovados | `SOURCE_REQUIRES_HUMAN_DECISION`. |
| Odds/Sportradar/Betradar | Material público empresarial | Menção de F1/H2H; sem contrato/export no workspace | `SOURCE_REQUIRES_HUMAN_DECISION`. |
| Odds/Betfair Historical | Especificação pública de feed | Feed licenciado; cobertura F1 H2H/settlement não comprovados | `SOURCE_REQUIRES_HUMAN_DECISION`. |
| Odds/OddsPapi | Docs públicas de API/histórico | API e snapshots existem; F1, H2H, período, licença e settlement não comprovados | `SOURCE_PARTIALLY_ACCEPTED` para diligência, não ingestão. |
| Datasets e Market DB | 0 fontes aceitas, 0 quotes | Sem população, cobertura, pilotos, equipes, casas ou margens observáveis | `MARKET_H2H_NOT_FEASIBLE`. |
| Gates e backtests econômicos | Gate ainda sem escolha humana; nenhuma série de odds | Nenhum trial N+1 ou walk-forward modelo-vs-mercado foi executado | Proibido até Stage 0 viável. |

## Contrato de decisão

Para uma fonte passar de diligência a `SOURCE_ACCEPTED`, ela deve fornecer,
sob licença compatível: export reprodutível, identificação de corrida/pilotos,
mercado `race_h2h` (não qualifying/sprint), bookmaker, opening/closing e seus
timestamps, odds dos dois lados, margem, regra versionada de liquidação,
tratamento DNF/DNS/DSQ/corrida cancelada/correção, batch e hash de proveniência.
Ausência de qualquer item deixa a fonte fora do Market DB.
