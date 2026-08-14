# Como baixar uma amostra BASIC da Betfair Historical Data — passo a passo

Status: **guia, não execução**. Ninguém desta sessão criou conta, logou ou
baixou nada. Isto é a "próxima ação mínima (custo zero)" já identificada em
`docs/DILIGENCIA_ODDS_2026-07-28.md` §7, item 1 — só que como passo a passo.

Por que este é o próximo passo mais barato: ao contrário da SportsDataIO
(produto comercial gated, precisa de negociação de vendas — ver
`docs/SPORTSDATAIO_PRESALE_QUESTIONS_DRAFT.md`), o tier **BASIC** da Betfair
é **gratuito** e de acesso self-service — basta uma conta própria (login
humano, sem scraping, sem contornar autenticação).

## O que o BASIC entrega (e o que não entrega)

- Motorsport está no pacote **"Other Sports"**, junto com esportes como
  ciclismo, dardos, e-sports etc.
- Cobertura: mercados liquidados na Exchange desde a introdução da Stream
  API (2016); "Other Sports" é tudo que não é futebol, corrida de cavalo,
  galgo, cricket, tênis ou golfe.
- Formato: arquivos `.tar` contendo NDJSON comprimido em `.bz2`, um evento
  por arquivo.
- **BASIC é limitado**: sem volume, só último preço negociado por minuto
  (não o livro de preços completo). Para volume e granularidade fina
  (1s/50ms) seria preciso ADVANCED ou PRO — pagos.
- **Uma casa só.** Mesmo perfeito, BASIC sozinho nunca passa nenhum
  threshold do projeto (todos exigem 2+ bookmakers — ver
  `data/market_h2h_feasibility.json` → `threshold_options`). Serve só para
  **medir liquidez** e decidir se vale a pena continuar essa trilha, não
  para autorizar nada.

## Passo a passo

1. **Conta**: se você não tem conta Betfair, registre uma em
   `register.betfair.com`. (Achado da diligência de 21/07: o acesso a partir
   do Brasil é redirecionado para `betfair.bet.br`, e alguns domínios
   `.com` de suporte podem não resolver ou retornar 404 daqui — pode ser
   necessário usar o domínio BR ou uma rede/VPN onde o `.com` resolva.
   Confirme você mesmo, esta sessão não tem como verificar geo-roteamento.)
2. **Portal**: acesse `historicdata.betfair.com` e faça login com essa
   conta.
3. Na página inicial, selecione o conjunto de dados: esporte **"Other
   Sports"** (ou o rótulo equivalente vigente), filtrando por período
   (ex.: um mês de temporada de F1) e, se o portal permitir, por tipo de
   mercado.
4. Baixe uma amostra pequena (ex.: um mês de uma temporada de F1 recente).
5. **Não ingira nada ainda.** Antes de qualquer uso:
   - Confirme quantos mercados de F1 aparecem no arquivo e se algum é do
     tipo H2H de corrida (não apenas vencedor/outright).
   - Verifique o volume negociado — BASIC não traz o campo de volume
     diretamente, mas a presença de preços variando ao longo do tempo é
     um proxy de que houve negociação.
   - Anote a contagem: quantos eventos de F1, quantos mercados por evento,
     quantos são H2H.

## Depois de baixar

Me passe o arquivo (ou um resumo/schema dele: nomes de campos, um evento de
exemplo, a contagem de mercados de F1/H2H encontrados). A partir de dado
real eu escrevo o parser de verdade em `src/data/`, seguindo o mesmo padrão
de `src/data/odds_provider.py` (stub fail-closed sem credencial, sem
inventar campo que não existe no arquivo real).

Isso ainda não entra em `src/data/market_h2h.py` nem em
`data/market_h2h.db` — essa trilha continua exigindo fonte `SOURCE_ACCEPTED`
e a reabertura explícita de `tracks.H2H`. O valor imediato de um parser real
é alimentar a Zona 1 (`COLLECTION_ONLY`, `docs/MARKET_COLLECTION.md`) para
avaliação de qualidade, que não promete nada além de arquivo e scorecard.

## Ressalvas já registradas (não repetir sem reavaliar)

- Comissão da entidade brasileira: 6,5% sobre o lucro líquido por mercado
  (fonte secundária, não confirmada em T&C oficial na diligência anterior —
  confirme ao criar a conta).
- Liquidez de H2H de F1 na Exchange é nicho e não documentada publicamente;
  só a amostra real responde isso.
