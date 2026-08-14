# Diligência de provedor de odds — SportsDataIO — 2026-08-14

Continuação da diligência autorizada em 2026-08-01
(`data/authorized_closure.json` → `h2h_reopening_2026-08-01`), trial
pré-registrada `G1-F1-market-h2h-sportsdataio-diligence` em
`data/trials.json`. Escopo, por decisão humana já registrada: **somente
SportsDataIO, somente diligência**. Nenhuma conta foi criada, nenhum dado foi
comprado, nenhum site protegido foi automatizado, nenhuma odd foi inventada.

**Este documento é evidência, não decisão.** Ele não altera `tracks.H2H`
(continua `CLOSED_BY_HUMAN_DECISION` — `src/closure.require_open('H2H')`
segue bloqueando `ingest()`/`coverage_gate()` em `src/data/market_h2h.py`),
não muda o status da SportsDataIO em `data/market_h2h_feasibility.json`
(continua `SOURCE_REQUIRES_HUMAN_DECISION`), não avança nenhum item do
contrato de decisão de `docs/PAST_ATTEMPT_LEDGER.md` para "verificado", e não
toca `real_money_operation` (`PERMANENTLY_BLOCKED`).

## O que foi tentado

1. **Reler as páginas oficiais** já citadas em
   `docs/DILIGENCIA_ODDS_2026-07-28.md` (`live-odds-api`, `historical-odds`,
   `developers/api-documentation/f1`), para checar se algo mudou desde
   21/07/2026 (novo mercado, cobertura de F1 adicionada ao produto de odds,
   documentação do endpoint renderizando desta vez).

   **Resultado: bloqueado.** O proxy de rede deste ambiente de execução
   recusa acesso ao domínio `sportsdata.io`
   (`EGRESS_BLOCKED: Access to sportsdata.io is blocked by the network
   egress proxy`). Não foi possível confirmar nem refutar nada a partir daqui
   hoje — isto é uma limitação do ambiente, não um achado sobre o provedor.

2. **Busca textual (motor de busca) por cobertura de odds da SportsDataIO
   para F1.** Retornou apenas páginas de terceiros (mirror de README no
   GitHub de um projeto não afiliado, agregador `apis.io`) repetindo a frase
   de marketing genérica "14+ major sports including ... Formula 1". Essa
   frase descreve o **catálogo geral de dados esportivos** da empresa (que
   inclui a API de estatísticas de F1, já conhecida e não é odds), não o
   produto de odds especificamente — exatamente a ambiguidade que o
   relatório de 21/07 já havia identificado e resolvido ao consultar a
   página do produto de odds diretamente, onde F1 não aparece na lista de
   esportes cobertos.

   Um resumo de busca de terceiros não é evidência mais forte que a leitura
   direta da página oficial já feita em julho; por isso **não é tratado como
   evidência nova** e não altera o veredito.

## Veredito desta rodada

Sem mudança. `SportsDataIO` permanece `SOURCE_REQUIRES_HUMAN_DECISION`.
Nenhum dos itens do contrato de decisão de `docs/PAST_ATTEMPT_LEDGER.md`
(licença, cobertura de `race_h2h` — não qualifying/sprint —, timestamps de
abertura e fechamento, odds dos dois lados, margem, regra de liquidação
versionada, tratamento DNF/DNS/DSQ/corrida cancelada/correção, batch e hash
de proveniência) foi verificado.

## Próxima ação concreta (não executada nesta sessão)

A diligência pública já esgotou o que dá para confirmar sem contato
comercial — ver `docs/DILIGENCIA_ODDS_2026-07-28.md` §7. O próximo passo
exige uma pessoa: enviar as perguntas de pré-venda fechadas (sim/não) para o
time comercial da SportsDataIO. O rascunho pronto para revisão e envio está
em `docs/SPORTSDATAIO_PRESALE_QUESTIONS_DRAFT.md`. Nenhum e-mail foi enviado
por esta sessão; nenhuma credencial foi solicitada ou usada.
