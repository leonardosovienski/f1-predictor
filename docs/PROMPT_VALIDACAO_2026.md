# PROMPT — Validação viva: retrodição de 2026 + previsão da próxima corrida

> Rascunho para rodar a qualquer momento da temporada 2026 — atualiza o
> histórico, retrodiz TODAS as corridas já disputadas no ano (comparando
> a previsão que o modelo TERIA dado, sem lookahead, com o resultado
> real) e prevê a próxima corrida do calendário. É um teste de sanidade
> operacional, NÃO um backtest novo — as Fases 1-5 já mediram RPS vs
> baselines com rigor estatístico; isto aqui é "o modelo, ao vivo,
> continua se comportando como o backtest disse que se comportaria?".
>
> **Estado do projeto em 2026-07-12: laboratório SELADO** (commit
> `9415c7b`, branch único `main`, árvore limpa) — nenhuma fase nova
> corre sem gatilho de dado novo ou pedido explícito. Este prompt É o
> gatilho de rotina enquanto a temporada 2026 avança.

**Projeto**: f1-predictor. **Regras de sempre**: nada inventado (só dado
real da Jolpica), sem lookahead (a previsão de cada corrida só pode usar
o que era conhecido ANTES dela), NO-GO de aposta real continua valendo
(o gate lê H1-F1, que segue REFUTADA — nada aqui muda isso).

---

## PASSO 0 — Atualizar o histórico

```bash
.venv\Scripts\python.exe scripts\build_db.py
```

Idempotente (INSERT OR REPLACE); corridas novas de 2026 desde a última
atualização entram automaticamente. Conferir a contagem de corridas com
resultado antes/depois.

## PASSO 1 — Retrodição de TODAS as corridas de 2026 já disputadas

Para cada corrida de 2026 com resultado no banco, reconstruir o Elo
EXATAMENTE como estava ANTES dela (prequential — reusar `BacktestElo` e
`run_fase2`/`run_backtest` do próprio `src/backtest.py`, filtrando
`season == 2026`) e registrar:

- **RPS** da corrida (comparar com o RPS médio da avaliação 2024-2026
  já medido nas Fases 1/2 — 0.1410 Elo puro, 0.1281 Elo+grid);
- **vencedor**: o modelo acertou o P1 previsto (maior P(win))?
- **pódio**: quantos dos 3 do pódio real estavam nos 3 primeiros do
  ranking previsto?
- **erro médio de posição** (2026-07-20, adicionado a pedido do usuário):
  |posição prevista − posição real| médio por piloto, comparando as DUAS
  ordens de chegada completas (22 pilotos), não só quem ficou em 1º — o
  RPS já pontua isso internamente, esta é só a versão legível por
  humano. Referência de contexto: duas ordens aleatórias independentes
  erram, em média, ~n/3 posições (≈7,3 para n=22) — o modelo fica bem
  abaixo disso, mas ainda longe de exato.
- comparação lado a lado com o que o **grid de largada sozinho** teria
  previsto (o baseline H0 — sempre relatar os dois).

Isso não é uma corrida de hipótese nova (não precisa de pré-registro em
trials.json — é validação operacional, não uma tentativa de pesquisa).
Produzir uma tabela corrida-a-corrida.

## PASSO 2 — Próxima corrida do calendário

Achar a próxima corrida com `date >= hoje` no calendário 2026
(`fetch_schedule`/`data/raw/schedule_2026.json`). Rodar:

```bash
.venv\Scripts\python.exe -m src.predict --circuit <CIRCUITO> --json
```

Se a ordem de largada real já existir (pós-quali, sábado), rodar de novo
com `--grid PILOTO:POSICAO ...` (Elo+grid+Platt da Fase 2) e reportar
os dois: a previsão pré-quali (Elo puro/vivido) e a pós-quali (blend).

## PASSO 3 — Testes de estresse adicionais (tudo que dá)

- **Determinismo**: rodar a mesma previsão 2x, confirmar ranking
  idêntico (mesma seed).
- **H2H real**: rodar `--head-to-head` para os pares de companheiros de
  equipe do grid 2026 (o único mercado com hipótese comprovada — H2-F1 e
  H3-F1b elevaram a acurácia de 62.6%→70.3%).
- **Erros esperados**: piloto/circuito inexistente devolve exit code 2;
  `--grid` com posições repetidas levanta erro.
- **Gate de operação**: `python -m src.operate --status` — confirmar que
  segue NO-GO (H1-F1 continua REFUTADA; nada nesta validação muda isso).
- **CI completo**: `scripts\ci_check.py` — 3 barreiras verdes.
- **Suíte completa**: `pytest tests/ -q` — todos os testes (116+) verdes.

## PASSO 3.5 — Reavaliar H8-F1 (opcional, só quando 2026 tiver bem mais corridas)

A Fase 5 (`scripts/run_fase5.py`) mediu o choque estrutural de
transição de regulamento e REFUTOU por falta de poder estatístico (só 9
corridas em 2026, RPS na direção certa mas p=0.907). É idempotente —
rodar de novo a cada bloco relevante de corridas novas (ex.: a cada 5-6
corridas) para checar se a significância aparece. Não rodar a cada
atualização de rotina — só quando o calendário justificar.

## PASSO 4 — Relatório

`docs/VALIDACAO_2026_<data>.md` (ou atualizar o mais recente): tabela de
retrodição corrida-a-corrida de 2026, RPS acumulado do ano vs baseline
grid, previsão da próxima corrida (pré e pós-quali se disponível),
resultado dos testes de estresse, e status do gate. **Nenhuma conclusão
nova de pesquisa aqui** — isso é acompanhamento operacional do modelo já
validado nas Fases 1-5.

## Reprodução rápida (tudo de uma vez)

```bash
.venv\Scripts\python.exe scripts\build_db.py
.venv\Scripts\python.exe scripts\validate_2026.py   # implementa os passos 1-3
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe scripts\ci_check.py
```
