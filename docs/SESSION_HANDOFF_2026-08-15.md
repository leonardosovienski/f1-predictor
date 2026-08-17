# Session handoff — 2026-08-14/15

Registro completo de uma sessão que cobriu diligência de mercado, uma
correção arquitetural no gate de aposta real, e uma auditoria de gaps de
teste/segurança. Escrito para sobreviver ao fim da conversa que o gerou —
nada aqui deveria depender de contexto que só existe no chat.

## Contexto: os 3 projetos do ecossistema

- **`core-predictor`** (`predictor_core`): biblioteca científica canônica
  compartilhada — Elo, métricas (RPS), bootstrap, calibração, contratos
  temporais. Instalável via wheel, sem vendoring.
- **`tools-predictor`** (`predictor_ops`): runner operacional agnóstico de
  domínio — execução de jobs, heartbeat, locks, Redis opcional,
  observabilidade. Não sabe nada sobre F1 nem sobre mercados.
- **`f1-predictor`**: a aplicação de domínio, consumidora dos dois acima.
  Único repositório tocado nesta sessão — os outros dois não têm nenhuma
  lógica de mercado ou aposta e estavam com CI verde no início e no fim.

## O que estava travado (e continua travado, de propósito)

Isto não mudou nesta sessão e não deveria mudar sem decisão humana nova e
auditável:

- `data/authorized_closure.json`: `real_money_operation: PERMANENTLY_BLOCKED`,
  `tracks.H2H` e `tracks.H8`: `CLOSED_BY_HUMAN_DECISION`.
- `H1-F1` (Elo vs. grid de largada): **REFUTADA** — RPS do modelo 0,1399 vs.
  grid 0,1303 (DM p=0,0002). O modelo perde até para uma baseline gratuita
  e pública, que já é mais fraca que qualquer preço de mercado.
- **Zero** fontes de odds aceitas, zero quotes, zero corridas cobertas no
  Market DB. `market_h2h_feasibility.json`: `MARKET_H2H_NOT_FEASIBLE`.
- Mesmo com dados de mercado perfeitos, o modelo nunca foi testado contra
  preço (só contra grid) — obter odds torna o teste possível, não produz
  edge sozinho.

## Trabalho feito nesta sessão (4 PRs, todos mergeados em `main`)

### PR #11 — diligência SportsDataIO (docs only)
- `docs/DILIGENCIA_ODDS_2026-08-14.md`: tentativa de reler as páginas
  oficiais de odds da SportsDataIO — bloqueado pelo proxy de rede do
  ambiente (`EGRESS_BLOCKED`). Busca por texto só achou paráfrase de
  marketing de terceiros ("14+ esportes incluindo F1"), que descreve o
  catálogo geral de dados, não o produto de odds — não tratado como
  evidência nova.
- `docs/SPORTSDATAIO_PRESALE_QUESTIONS_DRAFT.md`: rascunho pronto (11
  perguntas fechadas de sim/não, mapeadas ao contrato de decisão de
  `docs/PAST_ATTEMPT_LEDGER.md`) — **não enviado**. Nenhuma sessão tem
  conector de e-mail; isso exige ação humana.
- Correção lateral: um edit inicial em `data/trials.json` quebrou o hash
  congelado em `authorized_closure.json.preserved_artifact_sha256`
  (`data/trials.json` é um artefato preservado desde o fechamento de
  2026-07-23). Revertido antes do merge — lição: nunca editar arquivos
  dessa tabela sem uma reconciliação de hash explícita.

### PR #12 — guia Betfair BASIC (docs only)
- `docs/BETFAIR_BASIC_SAMPLE_HOWTO.md`: passo a passo pra baixar uma
  amostra grátis do tier BASIC da Betfair Historical Data (portal
  `historicdata.betfair.com`, conta própria, "Other Sports" cobre
  motorsport desde 2016, formato tar/bz2/NDJSON). É a "próxima ação mínima
  de custo zero" identificada na diligência de julho. **Nada foi baixado
  por esta sessão.**
- Ressalva conhecida: BASIC é uma casa só — nunca passa sozinho o
  threshold de 2+ bookmakers de `market_h2h_feasibility.json`; serve só
  pra medir liquidez antes de gastar em algo pago.

### PR #13 — correção arquitetural: gate de aposta real por estratégia
**O achado**: `go_gate()` lia incondicionalmente o veredito de H1-F1
(`data/backtest_fase1.json`) para *qualquer* `record_bet(real=True)`,
independente do `market`/`selection`. Funcionava por acidente feliz (H1-F1
refutada → tudo NO-GO), mas não era seguro por design: se aquele arquivo um
dia lesse `COMPROVADA` (reexecução, bug, arquivo trocado), **qualquer**
estratégia passaria, incluindo uma nunca testada. `operate.py --h2h` já
exercia esse bug em produção — apostas H2H eram gateadas por uma hipótese
de vencedor pré-evento, não por qualquer trial de H2H contra mercado (que
nunca existiu).

**A correção**: `go_gate(strategy_id, ...)` agora lê
`data/strategy_gates.json` — um registro que mapeia cada `strategy_id` ao
seu próprio `verdict_path`/`verdict_key`. Fail-closed em cada etapa: sem
`strategy_id`, sem registro, estratégia não cadastrada, ou veredito
ausente → NO-GO. `record_bet(real=True)` agora exige `strategy_id`
explícito (checado antes do closure, pra ser testável isoladamente).
`operate.py --h2h` usa por padrão `f1/h2h-post-qualifying/v1`, que
**deliberadamente não está registrada** — o NO-GO agora é pelo motivo
certo. `f1/winner-pre-event/v1` → H1-F1 é a única entrada registrada
hoje (ainda NO-GO; nenhuma ciência mudou). `scripts/validate_2026.py`
atualizado para o mesmo `strategy_id`.

Também produziu `docs/DIAGNOSTICO_MERCADO_2026-08-14.md`: a análise
completa e corrigida do estado real do projeto (modelo, mercado,
governança), verificada linha a linha contra o código — foi essa análise
que revelou o bug do gate.

### PR #14 — auditoria de gaps: `manual_approval.py`
**O achado**: `src/manual_approval.py` estava em **34% de cobertura**, sem
arquivo de teste dedicado. `tests/test_betting.py` nunca alcança essa
lógica de verdade: todo `record_bet(real=True)` naquela suíte bate primeiro
em `require_real_money_allowed()` (o closure real do projeto está
`PERMANENTLY_BLOCKED`), então a validação de aprovação manual nunca roda
até o fim.

Escrevendo testes de verdade (em vez de assumir o comportamento), dois bugs
apareceram:
1. Um `now` sem timezone (naive) passado a `require_manual_approval`
   (flui de `record_bet`) levantava `TypeError` não capturado em vez do
   `PermissionError` que todo chamador espera (`operate.py`'s
   `except PermissionError`). Não era um bypass — a aposta nunca era
   gravada — mas era um crash em vez da rejeição limpa e capturável de
   que o resto do código depende. Corrigido com checagem explícita de
   `tzinfo`.
2. `approval_id` só precisava satisfazer `isinstance(str)` — uma string
   vazia passava, diferente de `approved_by`, que já exigia não-vazio.
   Mesma checagem aplicada agora.

`tests/test_manual_approval.py` criado: 21 testes. Cobertura de
`manual_approval.py`: 34% → **100%**.

## O que foi encontrado mas NÃO corrigido (decisão pendente sua)

### `closure.py` — `require_real_money_allowed()` falha ABERTO, não fechado

Reproduzido ao vivo nesta sessão:

```python
# authorized_closure.json com {"tracks": {...}} MAS SEM a chave
# "real_money_operation" (ausência simples, não um valor diferente)
require_real_money_allowed(root=...)
# -> nenhuma exceção. Dinheiro real ficaria liberado silenciosamente.
```

O código atual (`src/closure.py`):
```python
def require_real_money_allowed(*, root: Path | str = ROOT) -> None:
    ...
    if record.get("real_money_operation") == "PERMANENTLY_BLOCKED":
        raise PermissionError(...)
    # se a chave não existir, .get() retorna None, a comparação é False,
    # a função simplesmente retorna — SEM bloquear.
```

**Por que isto importa**: é o mesmo padrão de falha do bug do `go_gate`
corrigido no PR #13 — ausência de sinal é tratada como permissão, não como
bloqueio. Isso contradiz o que o próprio módulo declara ("Fail-closed human
closure record") e o que `require_open()` faz para H8/H2H (arquivo ausente
→ bloqueia explicitamente).

**Por que não corrigi sozinho**: muda a polaridade padrão da função mais
crítica do projeto (o único portão que impede dinheiro real de sair, downstream
de tudo mais). Hoje não é explorável na prática — o `authorized_closure.json`
real tem a chave definida — mas eu não sabia (e ainda não sei) se existe
alguma razão, mesmo não documentada, para esse comportamento atual, e essa
não é uma decisão que um agente deveria tomar sozinho.

**Pergunta feita ao usuário, ainda sem resposta**: como corrigir —
(a) bloquear por padrão (só um marcador explícito de "permitido", que hoje
não existe no schema, libera — chave ausente/null/desconhecida sempre
bloqueia; só pode ficar mais restritivo que hoje, nunca menos), (b) só
documentar sem mexer no código agora, ou (c) revisar o diff exato antes de
decidir. **Nenhuma opção foi escolhida ainda.**

Próximo passo, se/quando o usuário decidir: aplicar a opção (a) é a
recomendação, análoga ao padrão de `go_gate`/`require_open` já corrigido
nesta sessão, com teste de regressão cobrindo especificamente "chave
ausente" além do "chave = PERMANENTLY_BLOCKED" já testado em
`tests/test_closure.py`.

## Estado do código nesta branch (topo: mergeado em `main`)

Todos os 4 PRs foram mergeados sequencialmente na branch
`claude/entender-3-projetos-vjoi1g` → `main`. CI verde em todos (ruff,
pyright, pytest, coverage ≥80%, build) exceto uma falha **pré-existente e
não relacionada** em `tests/test_runtime_contracts.py::test_portable_scheduler_success_heartbeat_and_terminal_failure`
(timing do scheduler do `predictor_ops`, presente antes de qualquer mudança
desta sessão, não reproduzida no CI real do GitHub — só neste sandbox
local).

Suíte completa ao final: **265 testes passando** (era 237 no início da
sessão), cobertura total 87,05%.

## Próximas ações concretas disponíveis (nenhuma exige mais código até aqui)

1. **Decidir o fix do `closure.py`** (ver seção acima) — a única coisa
   puramente sua, sem dependência externa.
2. **Mandar o e-mail pra SportsDataIO** (`docs/SPORTSDATAIO_PRESALE_QUESTIONS_DRAFT.md`)
   — comercial, precisa ser você.
3. **Criar conta na Betfair e baixar a amostra BASIC**
   (`docs/BETFAIR_BASIC_SAMPLE_HOWTO.md`) — grátis, self-service, precisa
   ser você (login humano).
4. Se qualquer uma das duas fontes acima confirmar cobertura real de
   `race_h2h` de F1, o próximo passo é atualizar `data/market_h2h_feasibility.json`
   (mudar status da fonte pra `SOURCE_ACCEPTED`) — decisão humana explícita,
   documentada no mesmo padrão dos registros anteriores.
5. Mesmo com fonte aceita, `tracks.H2H` continua exigindo uma nova decisão
   humana explícita e auditável antes de qualquer `ingest()`/`coverage_gate()`
   rodar de verdade (`src/closure.require_open('H2H')`).
6. Nenhuma dessas ações, sozinha ou combinada, autoriza dinheiro real — isso
   exige ainda: (a) uma estratégia testada e comprovada contra preço de
   mercado (não só contra grid), registrada em `data/strategy_gates.json`,
   e (b) uma decisão humana separada e explícita revertendo
   `real_money_operation: PERMANENTLY_BLOCKED`.
