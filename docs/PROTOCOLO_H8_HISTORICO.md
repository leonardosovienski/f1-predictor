# Protocolo congelado — validação histórica auxiliar da H8

Data de congelamento: 2026-07-20, antes da coleta dos resultados anteriores
a 2022 nesta rodada.

## Pergunta

O choque estrutural já definido pela H8 — `shrink_to_mean(0.8)` no primeiro
round de uma temporada com mudança técnica ampla — reduz o RPS ordinal nas
oito primeiras corridas, comparado ao mesmo Elo sem choque?

Esta é uma validação retrospectiva auxiliar. Não cria snapshots PRE_EVENT,
não entra no contador forward e não altera `H8_REQUIRED_RACES=15`.

## Protocolo fixo

- transições: 2014, 2017 e 2022;
- burn-in independente: duas temporadas imediatamente anteriores;
- avaliação: rounds 1–8 da temporada de transição;
- amostra planejada: 24 corridas, salvo ausência documentada de dados;
- fator: 0.8, já calibrado exclusivamente no sintético da Fase 5;
- Elo, tratamento de DNF e simulação: implementação existente;
- `n_sims=10000`, `sim_seed=13`;
- métrica primária: diferença pareada de RPS, choque menos Elo comum;
- teste: Diebold–Mariano bilateral, `alpha=0.05`;
- leitura favorável: diferença média negativa e DM `p<0.05`;
- heterogeneidade: reportar obrigatoriamente cada transição;
- nenhum candidato, fator, janela ou transição será alterado após observar
  os resultados.

## Justificativa externa das transições

- 2014: https://www.fia.com/news/2014-f1-power-unit-guide
- 2017: https://www.fia.com/sites/default/files/2017_technical_regulations_2017-03-09_1.pdf
  e https://www.fia.com/news/pirelli-announces-test-calendar-new-wider-formula-1-tyres-2017
- 2022: https://www.fia.com/regulation/category/110

## Fonte e proveniência

Resultados: API Jolpica/Ergast, pelo `F1Provider` existente, com caches locais
imutáveis. O artefato final registra hashes SHA-256 dos caches usados, commit,
parâmetros, cobertura e perdas por corrida.

## Classificação permitida

`SUPPORTED_HISTORICALLY`, `NOT_SUPPORTED_HISTORICALLY` ou
`INCONCLUSIVE_HISTORICALLY`. Nenhuma dessas classificações abre o gate H8.
