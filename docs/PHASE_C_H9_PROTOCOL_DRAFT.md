# Minuta de protocolo — H9-F1-h2h-market-v1

> **DRAFT — NÃO APROVADO, NÃO CONGELADO, NÃO EXECUTÁVEL.** Este documento não
> reabre hipóteses. Ele precisa de revisão humana, versão, commit e SHA-256 antes
> de qualquer inspeção analítica dos dados reais. Emendas posteriores não podem
> valer retroativamente para dados já observados.

## Pergunta científica

Probabilidades produzidas pelo Elo H2H congelado para companheiros de equipe,
comparadas a preços H2H disponíveis antes da corrida e tratadas com regras
causais, custos e sizing predefinidos, geram retorno médio positivo fora da
amostra?

- H0: retorno líquido esperado por aposta menor ou igual a zero.
- H1: retorno líquido esperado por aposta maior que zero.

H9 é independente e não altera os vereditos nem reabre H1–H8.

## Artefatos a congelar

Antes do primeiro acesso analítico ao arquivo real, registrar:

- versão e hash desta especificação e commit exato do projeto;
- versão do Elo H2H, estado inicial, parâmetros e identidades;
- fonte, licença, bookmaker/exchange, preço e settlement;
- seleção, sizing, custos, exclusões e código estatístico;
- temporadas OOS, burn-in, seed e tratamento de ausências.

O freeze não pode usar estatísticas aprendidas dos preços ou retornos OOS.

## Modelo e decisão

Será usado o Elo H2H de companheiros congelado no registro de pré-análise, sem
reotimização, calibração, seleção de features ou ajuste com retornos OOS.

Para `p_model`, odds executáveis decimais `o` e comissão `c` sobre lucro:

```text
net_win = (o - 1) * (1 - c)
p_break_even = 1 / (1 + net_win)
edge = p_model - p_break_even
```

Aposta somente se `edge >= 0.03`, com ambos os lados válidos no snapshot. Se os
dois lados excederem o threshold, o mercado é bloqueado. Aceita-se no máximo uma
seleção por mercado. A análise primária usa stake fixa de 1 unidade. Kelly,
reinvestimento e otimização de stake são apenas exploratórios.

## Mercado e causalidade

Fonte e preço serão aprovados após diligência e antes do freeze. A preferência
é preço executável de fechamento de exchange licenciado, como Betfair, somente
se licença, histórico e temporalidade forem aprovados.

- `decision_at`: último snapshot integralmente disponível até 10 minutos antes
  do `scheduled_start_utc` congelado;
- `closing_at`: último snapshot antes do início real, apenas para diagnóstico de
  closing-line value, nunca para decisão;
- in-play, pós-evento, retrodatado ou sem ordem causal é inelegível;
- comissão ausente ou ambígua bloqueia o mercado;
- margem proporcional usa os dois lados; exchange usa preço executável e
  comissão explícita;
- liquidez mínima, moeda e câmbio serão fixados antes do freeze;
- void devolve stake e permanece na auditoria.

Trocar fonte, preço, janela, comissão ou settlement cria nova versão da hipótese.

## População, OOS e burn-in

A população são mercados `race_h2h` entre companheiros canônicos. A minuta
reserva 2023–2024 como OOS se o lote aprovado cobrir essas temporadas; caso
contrário, a escolha ocorrerá sem observar retornos e antes da análise.

O burn-in mínimo será de 20 corridas anteriores ao primeiro evento OOS, usado
somente para inicializar o Elo. Burn-in não produz apostas ou métricas. Não há
split aleatório: avaliação e reamostragem preservam corrida e ordem temporal.

## Métricas e teste primário

Com stake unitária, retorno é `net_win` na vitória, `-1` na derrota e `0` em
void. A métrica primária é a média desse retorno.

O teste confirmatório será permutação unicaudal com 100.000 permutações e seed
congelada, trocando sinais/seleções dentro de corrida de modo compatível com H0
e preservando dependência intracorrida. Reportar média, IC 95% por bootstrap em
blocos de corrida e `p=(extremos+1)/(permutações+1)`.

Diebold–Mariano será secundário quando houver série de perdas comparável e HAC
predefinido; não substitui o teste primário. Métricas secundárias:

- Sharpe anualizado de retornos agregados por corrida;
- drawdown máximo da curva de stake fixa;
- taxa de acerto com intervalo binomial;
- P/L acumulado e número de apostas;
- closing-line value, cobertura e bloqueios somente como diagnósticos.

## Poder e tamanho mínimo

Premissas sintéticas conservadoras: alfa unicaudal 5%, poder 80%, efeito mínimo
relevante de 0,05 unidade e desvio-padrão 1,0:

```text
n = ceil(((z_0.95 + z_0.80) * sigma / delta)^2) = 2.473
```

Com 5% para voids/exclusões, o mínimo provisório é **2.604 apostas elegíveis**,
além do gate operacional de 500 duelos. Antes do freeze, simulação sintética
versionada deve reproduzir e ajustar esse número por cluster de corrida. Ele
pode aumentar, mas não diminuir com base em resultados reais. Amostra menor
gera `INSUFFICIENT_POWER`, nunca GO.

## GO/NO-GO

GO exige simultaneamente:

- retorno médio líquido maior que zero;
- permutação unicaudal com `p < 0.05`;
- limite inferior do IC 95% da média maior que zero;
- Sharpe anualizado maior que 0,5;
- drawdown máximo não superior a 30%;
- ao menos 2.604 apostas e nenhum desvio crítico;
- revisão e assinatura humana do pacote de resultados.

Qualquer falha produz NO-GO. Nenhum critério compensa outro e não há promoção
automática para dinheiro real.

## Paper trading e interrupção

Após GO retrospectivo e autorização separada, paper trading mantém protocolo e
stake fixa. Interromper imediatamente se:

- drawdown acumulado superar 20%;
- Sharpe móvel das últimas 10 corridas ficar abaixo de zero em três checkpoints;
- licença, causalidade, identidade, settlement ou disponibilidade quebrarem;
- houver divergência de hash ou alteração não autorizada do modelo.

Interrupção exige investigação e decisão humana. Mudança material cria protocolo
novo. Exclusões e desvios serão publicados; cortes por piloto, equipe,
bookmaker, threshold, sizing ou temporada são apenas exploratórios.
