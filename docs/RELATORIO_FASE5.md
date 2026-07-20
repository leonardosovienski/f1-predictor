# RELATÓRIO — Fase 5 do f1-predictor (choque estrutural de transição de regulamento)

> Executado em 2026-07-12, a pedido explícito do usuário, com protocolo
> científico próprio dele: calibração cega em uma transição histórica,
> aplicação cega em 2026. Adaptação necessária documentada abaixo.

> **Errata 2026-07-20** (não destrutiva): `is_dnf()` corrigido (bug real
> descrito em `../HANDOFF.md`); reexecutado — **H8-F1 mantém o MESMO
> veredito** (REFUTADA, direção certa sem significância), fator=0.8
> inalterado, RPS 2026 com_choque=0.1576 vs sem_choque=0.1631 (era
> 0.1651 vs 0.1662; DM p=0.5035, era p=0.9072).

## O pedido original e o obstáculo real

O protocolo pedido: calibrar um fator de choque na transição real
2021→2022 e aplicá-lo cegamente em 2026 (mesma lógica de regulamento
mudando drasticamente). **Nosso histórico começa em 2022** (burn-in da
Fase 1) — não existe Elo acumulado de 2021 para chocar, e a virada de
2022 em si é um no-op (todo mundo já parte de 1400 na primeira corrida).
Calibrar em 2026 e aplicar em 2026 violaria o próprio espírito "cego" do
protocolo. **Adaptação adotada**: a calibração usa um cenário
**sintético** — reembaralhamento do campo inteiro numa fronteira de
temporada conhecida, a mesma disciplina de harness usada desde a Fase 2
— e o fator resultante é aplicado às cegas ao histórico real. 2026 nunca
influencia a escolha do fator.

## Mecanismo

`BacktestElo.shrink_to_mean(factor)`: encolhe TODOS os ratings vistos em
direção à semente (1400) — `new = 1400 + (1-factor)·(rating-1400)`.
Aplicado UMA VEZ no primeiro round de cada temporada declarada como
transição de regulamento real: **2022 e 2026** (mudanças técnicas
documentadas da F1, não inventadas). Diferente do `VolatilityShock` da
Fase 4 (K temporário, um piloto/equipe só): aqui o campo INTEIRO é
afetado, porque um regulamento novo muda o jogo pra todo mundo, não só
para quem trouxe upgrade.

## Calibração cega (sintético)

Cenário: 3 temporadas com força estável, depois uma fronteira onde o
campo inteiro é reembaralhado. Busca em grade do fator (0.0 a 1.0):

| Fator | RPS na janela pós-fronteira |
|---|---|
| 0.0 (sem choque) | 0.1804 |
| 0.2 | 0.1749 |
| 0.4 | 0.1704 |
| 0.6 | 0.1676 |
| **0.8** | **0.1668** (vencedor) |
| 1.0 (reset total) | 0.1681 |

**Fator escolhido: 0.8.** Harness confirma sensibilidade (reembaralhamento
real → choque ajuda) e especificidade (força estável → choque atrapalha,
`ajuda=False`) — a mecânica está provada antes de tocar em dado real.

## Resultado no histórico real (fator 0.8, aplicado às cegas)

| Temporada | RPS com choque | RPS sem choque | Nota |
|---|---|---|---|
| 2023 | 0.1397 | 0.1397 | idêntico (sem transição declarada aqui) |
| 2024 | 0.1308 | 0.1308 | idêntico |
| 2025 | 0.1430 | 0.1430 | idêntico |
| **2026** | **0.1651** | 0.1662 | **transição** |

**H8-F1: REFUTADA** — DM = -0.120, p=0.907 (longe de p<0.05).

**Leitura honesta, não "não funcionou":** a direção é a CERTA (RPS caiu
de 0.1662 para 0.1651 com o choque) — o mecanismo empurra na direção
prevista pela teoria. O problema é **poder estatístico**: 2026 só tem
**9 corridas** disputadas até agora. Uma melhora de 0.0011 no RPS médio
sobre 9 observações não tem como ser estatisticamente significativa —
precisaria de um efeito muito maior ou de mais corridas. Isso é
diferente de "a teoria está errada"; é "a amostra ainda é pequena demais
para provar a teoria com o rigor que o projeto exige antes de mudar a
produção".

As temporadas 2023-2025 confirmam a robustez do desenho: como não são
declaradas como transição, o choque não é aplicado nelas — RPS
idênticos byte a byte com/sem o mecanismo, provando que ele não introduz
efeito colateral fora do momento pretendido.

## Decisão

1. **H8-F1 não entra no serving** (`fase5_params.json`: `shrink_factor=0.0`,
   `usar_choque_transicao=false`) — mesma disciplina de todas as fases:
   nenhuma feature sem comprovação estatística entra em produção.
2. **Reavaliar com mais dado**: 2026 tem 13 corridas restantes. Rodar
   `scripts/run_fase5.py` de novo ao final da temporada (ou em qualquer
   ponto — é idempotente) para checar se o efeito ganha significância
   com mais observações.
3. **GO/NO-GO de aposta: inalterado, NO-GO** (gate lê H1-F1, que segue
   refutada — H8 não é uma hipótese de edge de mercado).

## Reprodução

```bash
.venv\Scripts\python.exe scripts\run_fase5.py
.venv\Scripts\python.exe -m pytest tests/ -q   # 116 verdes
```
