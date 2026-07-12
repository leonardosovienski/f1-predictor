# RELATÓRIO — Fase 1 do f1-predictor (backtest prequential ordinal)

> Executado em 2026-07-12. Primeiro backtest ORDINAL do ecossistema —
> estreia do `metrics.rps`, do `nullref` e do Diebold-Mariano do core em
> um domínio de ordenação completa (22 posições).

## Veredito das hipóteses pré-registradas

| Hipótese | Veredito | Evidência |
|---|---|---|
| **H1-F1** — Elo/PL bate o grid de largada no RPS (DM p<0.05 + nulo) | **REFUTADA** | RPS modelo 0.1410 vs grid **0.1303**; DM +4.43, p=0.00003 — o grid é **significativamente melhor** |
| **H2-F1** — H2H entre companheiros: acerto > 50% (Wilson 95% > 0.5) | **COMPROVADA** | 253/404 = **62.6%**, IC95 [0.578, 0.672] inteiro acima de 0.5 |

O fluxo de governança rodou NA ORDEM: controle positivo do harness
(atestado emitido) → pré-registro em `data/trials.json` → backtest →
resultados gravados nas mesmas trials. Nenhuma configuração extra foi
avaliada além das duas pré-registradas.

## Protocolo (como pré-registrado)

- **Dados**: 101 corridas reais 2022–2026 (Jolpica, cache imutável em
  `data/raw/`, SQLite `data/f1.db`). Burn-in: 2022 (22 corridas);
  avaliação: **79 corridas** (2023–2026 R9).
- **Prequential estrito**: prever (Plackett-Luce/Gumbel, 10k sims,
  determinístico) → só depois atualizar o Elo com a ordem real. Teste de
  ausência de lookahead na suíte.
- **Semente**: todos os pilotos partem de 1400 — a semente 2025 da Fase 0
  seria lookahead. K novato 40 (menos de 22 corridas vistas), base 24.
- **DNF**: leitura primária usa a classificação oficial (abandonos no fim
  do grupo, por voltas); o update de Elo exclui DNFs (contrato da Fase 0).
- **Baselines** com a MESMA máquina probabilística (escada declarada
  1750→1350 + Plackett-Luce; zero tuning): grid de largada, standings
  correntes, e o previsor uniforme.
- **Nulo (nullref)**: teste de permutação — as previsões do próprio modelo
  com atribuição previsão→piloto sorteada (1000 amostras). Preserva
  assertividade, destrói informação. *(Um nulo de ordenações one-hot foi
  testado e DESCARTADO no harness: qualquer previsor flat o vence — o
  controle positivo pegou exatamente essa armadilha.)*

## Resultados

### RPS (79 corridas, média por corrida)

| Previsor | RPS | DM vs modelo | p |
|---|---|---|---|
| **Grid de largada** | **0.1303** | +4.43 (grid melhor) | 0.00003 |
| Standings correntes | 0.1356 | +2.73 (standings melhor) | 0.008 |
| **Modelo (Elo/PL)** | 0.1410 | — | — |
| Uniforme (sem informação) | 0.1749 | −10.72 (modelo melhor) | <10⁻¹⁶ |
| Nulo de permutação (média) | 0.2071 | modelo no percentil 0 | tail_p ≈ 0 |

O modelo **carrega informação real** — está abaixo do percentil 5 do nulo
(0.1410 ≪ 0.2023) e esmaga o uniforme — mas **não bate as ordenações
"gratuitas"** da F1: o grid de largada e a tabela do campeonato preveem a
chegada melhor que o Elo puro. Não há edge demonstrado sobre o baseline
relevante. **Nenhuma aposta.**

### Estratos (corte de regulamento)

| Estrato | n | RPS modelo | RPS grid | DM | p |
|---|---|---|---|---|---|
| 2023 | 22 | 0.1396 | 0.1384 | +0.31 | 0.76 (empate) |
| 2024 | 24 | 0.1309 | 0.1206 | +2.25 | 0.034 |
| 2025 | 24 | 0.1429 | 0.1312 | +3.37 | 0.003 |
| **2026 (regulamento novo)** | 9 | **0.1662** | 0.1339 | +4.08 | 0.004 |

O pior estrato do modelo é exatamente **2026**: o choque de regulamento
(Antonelli líder, Verstappen 7º nos standings) derrubou a informação
acumulada do Elo, enquanto o grid reflete o carro ATUAL a cada corrida. Em
2023 o modelo empata com o grid; a vantagem do grid cresce a cada ano.

### Leituras secundárias

- **Vencedor** (multiclasse): Brier modelo 0.831 < grid 0.846 < standings
  0.857; log-loss idem (2.171 < 2.209 < 2.251). Na CABEÇA da corrida o Elo
  é competitivo — ele perde do grid no MEIO do pelotão, onde a posição de
  largada domina.
- **Sensibilidade DNF**: excluindo abandonos, RPS do modelo cai para
  0.1239 — DNFs são ruído não-modelado (a Fase 2 pode modelar
  confiabilidade por equipe).
- **Calibração do pódio** (Brier 0.098, base rate 0.149): o modelo é
  **subconfiante nas faixas altas** — quando prevê P(pódio) 0.3–0.5, o
  realizado é 0.45–0.70. Platt/isotônica é candidata REAL para o headline,
  mas é tentativa N+1: fica pré-registrável para a Fase 2, não aplicada.
- **H2H entre companheiros** (o mercado das casas): 62.6% de acerto com IC
  fora do zero — o único sinal com hipótese COMPROVADA. Consistente com o
  Elo ser bom em ORDENAR PILOTOS de força próxima (mesmo carro) e ruim em
  ordenar o pelotão inteiro (dominado pelo carro/grid).

### Elo vivido (pós-backtest, grid 2026)

Top-5: Verstappen 1696, Norris 1680, Russell 1637, Piastri 1615, Leclerc
1597. Gravado em `data/ratings.json` (só grid 2026) — o serving da Fase 0
agora usa o Elo VIVIDO, não a semente do campeonato 2025.

## Decisão e recomendação

1. **GO/NO-GO de aposta: NO-GO.** H1 refutada — sem edge sobre o grid.
   O gate da Fase 3 (operação) continua fechado.
2. **Fase 2 tem alvo claro**: incorporar o **grid de largada como feature**
   (o modelo só faz sentido como Elo + grid, não Elo vs grid) e
   confiabilidade/DNF por equipe. Cada variação = trial N+1 pré-registrada.
3. **H2H é o caminho de mercado**: a única hipótese comprovada é
   exatamente o mercado mais líquido das casas (matchups). A Fase 1b pode
   pré-registrar H3 (H2H geral, não só companheiros) e sondar odds reais —
   a The Odds API lista F1 como `motorsport_f1`? **Confirmar no /v4/sports
   quando houver chave** (não confirmado nesta fase).
4. **Calibração**: medir Platt no P(pódio)/P(win) como trial da Fase 2.

## Reprodução

```bash
.venv\Scripts\python.exe scripts/build_db.py        # Jolpica → data/f1.db
.venv\Scripts\python.exe scripts/run_backtest.py    # governança completa
.venv\Scripts\python.exe -m pytest tests/ -q        # 50 verdes
```

Artefatos versionados: `data/trials.json`,
`data/trials.harness_attestation.json`, `data/backtest_fase1.json`.
Runtime (rebuildáveis): `data/raw/`, `data/f1.db`, `data/ratings.json`.
