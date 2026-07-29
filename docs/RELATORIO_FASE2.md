# RELATÓRIO — Fase 2 do f1-predictor (grid como feature + calibração)

> Executado em 2026-07-12, na sequência direta da Fase 1. Duas tentativas
> N+1 pré-registradas em `data/trials.json`: **H3-F1b** (grid como
> feature do modelo, não só baseline separado) e **H4-F1b** (calibração
> de Platt no P(pódio)).

> **Errata 2026-07-20** (não destrutiva): `is_dnf()` corrigido (bug real
> descrito em `../HANDOFF.md`); reexecutado — **H3-F1b e H4-F1b mantêm o
> MESMO veredito** (ambas COMPROVADAS), w=0.5 inalterado, RPS blend 0.1274
> (era 0.1281), Brier calibrado 0.0794 (era 0.0783).

## Veredito das hipóteses pré-registradas

| Hipótese | Veredito | Evidência |
|---|---|---|
| **H3-F1b** — Elo+grid (peso escolhido no dev/2023) bate o Elo puro no RPS, avaliação CEGA 2024-2026 | **COMPROVADA** | RPS blend **0.1274** vs Elo puro **0.1407** (DM −9.22, p≈0) |
| **H4-F1b** — Platt (ajustado no dev/2023) reduz o Brier do pódio na avaliação CEGA | **COMPROVADA** | Brier pódio: cru 0.0930 → calibrado **0.0794** |

## Protocolo (sem lookahead adicional)

O alvo nº 1 do relatório da Fase 1 era "grid como FEATURE do modelo, não
como baseline separado". Diferença chave: comparar Elo vs grid (Fase 1)
mede quem prevê melhor SOZINHO; misturar os dois (blend linear no espaço
Elo, `(1-w)·Elo + w·escada(grid)`) testa se o grid acrescenta informação
ao Elo. Ambos os hiperparâmetros — o peso `w` do blend e os parâmetros de
Platt — são escolhidos **só no período de DESENVOLVIMENTO (2023)**, depois
do burn-in de 2022; a partir de 2024 ficam **CONGELADOS**, e é aí que as
métricas reportadas são calculadas — cegas ao ajuste. O Elo em si segue a
mesma passada contínua 2022→2026 da Fase 1.

**Harness (controle positivo) de H3**, a lição desta fase: um cenário
sintético onde o grid é só "outra amostra ruidosa da mesma força" (o
gerador original da Fase 1) **não é um teste de sensibilidade válido** —
uma vez que o Elo converge, misturar um grid mais ruidoso só piora. O
cenário de sensibilidade real precisa de um choque de "forma do dia"
(`form_scale`) compartilhado entre quali e largada — informação da
corrida ESPECÍFICA que o Elo (que só aprende a força de longo prazo) não
vê, mas que o grid carrega. Só com esse mecanismo o harness confirma
corretamente (edge) e rejeita corretamente (grid embaralhado, mesmo
choque de forma presente).

## Resultados (2024–2026, 57 corridas, cego ao ajuste)

| Previsor | RPS |
|---|---|
| Grid de largada (baseline) | 0.1272 |
| **Blend Elo+grid (w=0.5)** | **0.1281** |
| Standings correntes | 0.1353 |
| Elo puro (Fase 1) | 0.1416 |

O blend fecha praticamente toda a distância que separava o Elo puro do
grid na Fase 1 (RPS 0.1416 → 0.1281, quase empatando com 0.1272) — a
mistura das duas fontes de informação (histórico do piloto + o carro
ATUAL revelado no quali) é o modelo certo, não um contra o outro. `w=0.5`
escolhido no dev: peso quase igual entre Elo e grid.

**H2H entre companheiros** (o mercado mais líquido) sobe de 62.6% (Fase 1,
Elo puro) para **70.3%** (201/286, Wilson95 [0.647, 0.753]) com o blend —
o grid ajuda exatamente onde o Elo puro era mais fraco: comparar dois
carros iguais no dia.

### Calibração do pódio — achado que exige cautela

Platt (a=3.59, b=3.46, ajustado no dev/2023) reduz o Brier AGREGADO do
pódio (0.093→0.078), confirmando H4. Mas a tabela de calibração por faixa
revela um **efeito colateral real**: nas faixas de confiança MAIS ALTA a
calibração **sobrecorrige**:

| Faixa prevista | Observado (cru) | Observado (calibrado) |
|---|---|---|
| 0.7–0.8 | — | 0.611 (previsto 0.747) |
| 0.8–0.9 | — | 0.593 (previsto 0.854) |
| 0.9–1.0 | — | 0.739 (previsto 0.930) |

O Brier melhora em MÉDIA porque a maioria das previsões está nas faixas
baixas/médias (onde o cru era subconfiante e a correção acerta), mas para
o pole/P2 de corridas muito assimétricas o P(pódio) calibrado fica
**superconfiante** (93% previsto vs 74% realizado). **Recomendação**: usar
a calibração para o headline geral, mas não tratar P(pódio) > 85% como
literal — Platt de 2 parâmetros não tem grau de liberdade para corrigir
sub e sobreconfiança em extremos opostos ao mesmo tempo; isotônica é
candidata da Fase 3+ se isso importar operacionalmente.

## Serving atualizado

`--grid` no CLI aceita a ordem de largada pós-quali e usa o blend + Platt
vividos (`data/fase2_params.json`, gerado por `scripts/run_fase2.py`) —
condicionado ao veredito: sem o arquivo, ou se uma hipótese fosse
refutada, o serving cai automaticamente no Elo puro (nenhuma feature sem
comprovação entra em produção).

```bash
.venv\Scripts\python.exe -m src.predict --circuit Hungaroring --grid Norris:1 Verstappen:2 ...
```

## Fase 3 — operação (construída, permanece GATED)

`src/betting.py`, `src/operate.py`, `src/data/odds_provider.py`: Kelly
fracionário (1/4, teto 5% do bankroll), log de apostas append-only
(`data/bets.jsonl`), settle e um **gate de GO/NO-GO** que lê o veredito de
**H1-F1** (não H3-F1b) — porque H1 é a barra real de edge sobre o mercado
gratuito (grid), enquanto H3 só mede se o grid ajuda o Elo a se aproximar
do próprio grid. H1-F1 continua **REFUTADA** (Fase 1) → o gate é **NO-GO**
e `record_bet(..., real=True)` levanta `PermissionError`. Só `paper=True`
funciona — nenhuma aposta real sai deste projeto.

**Pendência da Fase 1 resolvida** (sondagem em 2026-07-12, com chave real
do usuário, só leitura): `/v4/sports` da The Odds API lista 57 esportes —
**nenhum é F1/motorsport**. A Fase 1b (odds reais) está encerrada por
falta de fonte, não por falta de tempo.

## Decisão

1. **GO/NO-GO de aposta: NO-GO** (inalterado — o gate mede H1, não H3).
2. **Modelo de produção candidato**: Elo+grid (`w=0.5`) para o ranking
   completo; Platt para o headline do pódio, com a ressalva de não
   confiar em P(pódio) > 85%.
3. **The Odds API não é fonte de odds de F1** — se a operação real algum
   dia sair do NO-GO, precisa de outra fonte (casas diretas, Betfair
   Exchange API, etc.) — não investigado nesta fase.
4. Próxima tentativa N+1 natural: DNF/confiabilidade por equipe como
   feature (o relatório da Fase 1 já apontava DNF como a maior fonte de
   erro residual do Elo).

## Reprodução

```bash
.venv\Scripts\python.exe scripts/run_fase2.py     # harness -> pre-registro -> backtest
.venv\Scripts\python.exe -m src.operate --status  # confere o gate de GO
.venv\Scripts\python.exe -m pytest tests/ -q      # 79 verdes
```
