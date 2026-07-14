# PROMPT — Testar o modelo no GP da Bélgica 2026 (Rodada 10, Spa-Francorchamps)

> Autocontido: cole isto numa sessão nova (ou siga na mão) sem precisar
> ler o resto do projeto. Corrida: **domingo 2026-07-19**, quali no
> sábado (2026-07-18). Não é pesquisa nova — é acompanhamento
> operacional do modelo já validado (Fases 1-5).

## Antes do quali (qualquer dia até sábado)

```bash
.venv\Scripts\python.exe scripts\build_db.py
.venv\Scripts\python.exe -m src.predict --circuit Spa --json
```

Dá o ranking completo via **Elo puro vivido** (sem informação do fim de
semana ainda). Favorito de referência no momento deste prompt:
Verstappen ~14.5% win / 39.5% pódio, Norris ~12.4%/35.6%.

## Depois do quali de sábado

A Jolpica publica o resultado do quali como dado estruturado
(`fetch_qualifying`, novo nesta sessão). Rodar:

```bash
.venv\Scripts\python.exe scripts\validate_2026.py
```

Ele detecta sozinho se o quali da próxima corrida já saiu: se sim, usa
o **blend Elo+grid+Platt** (comprovado na Fase 2, RPS 0.1281 vs 0.1416
do Elo puro) automaticamente; se não, cai no Elo puro. Não precisa
digitar a ordem de largada na mão.

Se preferir rodar só a previsão pós-quali (sem o resto do relatório),
com a ordem de largada manual:

```bash
.venv\Scripts\python.exe -m src.predict --circuit Spa --grid Verstappen:1 Norris:2 Piastri:3 ...
```

## Depois da corrida de domingo

```bash
.venv\Scripts\python.exe scripts\build_db.py       # traz o resultado real
.venv\Scripts\python.exe scripts\validate_2026.py   # retrodiz Spa com Elo/grid/blend, compara com o real
```

A saída mostra, para Spa: RPS de cada previsor (Elo/grid/blend), quem o
modelo apontou como favorito vs quem venceu de verdade, e atualiza o
acumulado de 2026 (RPS médio do ano, acerto de vencedor — hoje 2/9,
grid batendo o modelo, choque de regulamento ainda pesando).

## O que checar ao ler o resultado

- **Grid ainda deve bater o modelo em 2026** (achado da Fase 1/5,
  confirmado corrida a corrida) — não é bug se isso se repetir em Spa.
- **Gate de operação continua NO-GO**: `python -m src.operate --status`
  — nada nesta corrida muda H1-F1 (precisaria de muitas corridas a mais
  para reverter um veredito estatístico).
- **H2H de companheiros** é o único mercado com edge comprovado —
  vale conferir os pares reais de Spa:
  `python -m src.predict --head-to-head Norris Piastri --circuit Spa --json`
  (e o mesmo para os outros 10 pares do grid 2026).

## Suíte e CI (sempre que mexer em algo)

```bash
.venv\Scripts\python.exe -m pytest tests/ -q   # 118+ verdes
.venv\Scripts\python.exe scripts\ci_check.py   # 3 barreiras
```
