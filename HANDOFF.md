# HANDOFF.md — f1-predictor

> **Sincronia Git (revalidada em 2026-07-20):** o HEAD local `030a5b7`
> está um commit à frente de `origin/main` (`2bf2dad`). Nenhum push foi
> feito nesta rodada.

> ## FECHAMENTO FINAL — INTEGRIDADE DE REPLAY E MATURAÇÃO (2026-07-20)
>
> Auditoria direta de código, banco, artefatos e casos hostis. Estado real:
> banco íntegro (`integrity_check=ok`), 114 corridas, 2.058 resultados e
> 3.750 pitstops; em 2026 há 22 eventos no calendário, 10 disputados com
> 220 resultados, mas **0 pares PRE_EVENT→MATURED `VALID_FOR_H8`**.
> `H8_REQUIRED_RACES = 15` permanece literal em `src/snapshots.py`; faltam
> 15 evidências forward válidas, não cinco corridas disputadas.
>
> Bugs reais corrigidos nesta rodada:
>
> 1. `_atomic_create` escrevia diretamente no nome final; ENOSPC/erro
>    parcial podia deixar JSON truncado e consumir definitivamente o id
>    imutável. Agora grava+`fsync` em temporário, publica por hard link
>    atômico sem overwrite concorrente e sempre limpa o temporário.
> 2. `mature_snapshot` aceitava timestamp anterior à largada, e
>    `h8_eligibility` não revalidava tempo/identidade após leitura. Ambos
>    agora falham fechados (`INVALID_FOR_H8`).
> 3. `build_db` fazia apenas `INSERT OR REPLACE`: replay de resultado
>    oficial corrigido com menos linhas preservava piloto obsoleto. Uma
>    resposta não vazia agora substitui transacionalmente o conjunto da
>    corrida; resposta vazia não apaga resultado maduro.
> 4. JSON de ratings/parâmetros aceitava NaN/Inf, contaminando simulação e
>    serialização. Validação finita e de tipo foi adicionada.
>
> Cobertura hostil inclui banco/temporada vazios, DNF/DNS/DSQ/Lapped,
> ausência e substituto (rejeição explícita fora do grid canônico), posições
> inválidas/duplicadas, pit lane empatado em zero, novo piloto, timestamps
> inválidos, snapshot duplicado/truncado, maturação prematura, resultado
> corrigido, replay, falha parcial, concorrência/determinismo e NaN/Inf.
> Fechamento adicional: `build_db` agora valida atomicamente cada lote de
> resultado/pitstops antes da substituição. Corrida/round divergente,
> identidade ou posição duplicada, grid inválido, DNF malformado e
> NaN/Inf abortam sem apagar o dado anterior; resposta vazia também não é
> destrutiva. Suíte completa: **152 verdes**; CI local: **3/3**. Nenhum parâmetro,
> threshold, K-factor, trial ou veredito científico mudou. Veredito local:
> **PASS LOCAL COM GATE CIENTÍFICO FECHADO**.

> ## 📋 RECONCILIAÇÃO DE PENDÊNCIAS DO ECOSSISTEMA (2026-07-20)
>
> Revisão de `../PENDENCIAS_ABERTAS.md` procurando itens de f1-predictor
> genuinamente acionáveis dentro do escopo desta auditoria (sem tocar
> `SEC-1`/itens de outros consumidores nem promover lifecycle
> compartilhado). Três imprecisões factuais corrigidas no documento:
> 1. **SCI-6 estava desatualizada e confundia exatamente o que a missão
>    pede pra não confundir**: dizia "9 corridas maturadas confirmadas"
>    — na verdade são 10 corridas DISPUTADAS (retropredição) e **0**
>    corridas MATURADAS forward (`VALID_FOR_H8`; `snapshots/` nem existe).
> 2. **INC-1 estava factualmente errada sobre o F1**: afirmava que só o
>    cs-predictor tem vínculo criptográfico entre snapshots PRE_EVENT/
>    MATURED — mas `src/snapshots.py` hasheia (SHA-256) e vincula
>    `pre_event_payload_hash` desde sempre (`mature_snapshot`/
>    `h8_eligibility` rejeitam hash inconsistente). Corrigida só a parte
>    f1 (LoL não verificado, fora de escopo).
> 3. **Branch órfã não catalogada** achada: `claude/belgium-quali-gp-test-72bff2`
>    — verificada como subconjunto estrito de `main` (mesmo padrão da já
>    catalogada `reintegracao-f1-ondas-2-3`), documentada, nenhuma ação
>    destrutiva tomada (apagar branch é decisão do usuário).
>
> Nenhum bug de código novo encontrado nesta revisão; os gaps restantes
> (SCI-1/SCI-4 deferidas, OP-4 parte não-f1, SCI-6 aguardando amostra)
> são governança científica normal, não pendências corrigíveis à força.

> ## 🐛 BUG CIENTÍFICO REAL — CONVENÇÃO DE STATUS "Lapped" (2026-07-20)
>
> Investigando um print de resultado real (GP da Bélgica, R10) contra o
> banco local, achei que a Jolpica troca de convenção de status ENTRE
> temporadas para o MESMO conceito (piloto classificado, voltas atrás do
> líder): `"+N Lap(s)"` só em 2022 (87 linhas), `"Lapped"` a partir de
> 2023 (363 linhas, 2023-2026 — quase toda a janela de avaliação cega dos
> backtests). `is_dnf()` só reconhecia o formato antigo — **363
> resultados reais estavam marcados DNF quando na verdade terminaram a
> corrida**, contaminando `finish_order` em TODO backtest (Fases 1, 2, 4,
> 5) e, mais diretamente, a feature de Reliability (H6-F1c), que é
> literalmente DNF rolling.
>
> Corrigido: `is_dnf()` reconhece `"Lapped"` como classificado, igual a
> `"+N Lap(s)"`. `"Did not start"` (DNS) e `"Disqualified"` (DSQ)
> permanecem DNF — não são o mesmo caso (DNS não correu; DSQ foi excluído
> da classificação por decisão de comissários, não é formatação
> alternativa de "terminou voltas atrás") — semântica atual confirmada,
> não alterada sem evidência de bug.
>
> **Rebuild offline do banco (cache local, sem rede) + reexecução
> COMPLETA do pipeline científico na ordem oficial** (`run_backtest.py` →
> `run_fase2.py` → `run_fase4.py` → `run_fase5.py` →
> `validate_2026.py`), sem tocar em nenhum threshold/critério/hipótese —
> só a correção do bug de ingestão. **Todos os 9 vereditos permaneceram
> EXATAMENTE os mesmos** (nenhuma hipótese foi salva nem derrubada pela
> correção); os números mudaram de forma consistente com mais dados
> corretamente classificados:
>
> | Trial | Antes (com bug) | Depois (corrigido) |
> |---|---|---|
> | H1-F1 | REFUTADA — RPS 0.1410 vs grid 0.1303 (DM 4.430, p=0.0000, 79 corridas) | REFUTADA — RPS 0.1399 vs grid 0.1303 (DM 3.853, p=0.0002, 80 corridas) |
> | H2-F1 | COMPROVADA — 62.6% (253/404), Wilson95 [0.578, 0.672] | COMPROVADA — 65.0% (392/603), Wilson95 [0.611, 0.687] |
> | H3-F1b | COMPROVADA — w=0.5, RPS blend 0.1281 vs elo 0.1416 (57 corridas) | COMPROVADA — w=0.5, RPS blend 0.1274 vs elo 0.1407 (58 corridas) |
> | H4-F1b | COMPROVADA — Brier 0.0932→0.0783 | COMPROVADA — Brier 0.0930→0.0794 |
> | H0-F1-formal | COMPROVADA — RPS grid 0.1304 vs elo 0.1410, IC95 [-0.0153,-0.006] | COMPROVADA — RPS grid 0.1304 vs elo 0.1399, IC95 [-0.0145,-0.0047] |
> | H5-F1c | REFUTADA — w_ctx=1.5, RPS 0.1299 vs 0.1282 (p=0.2497) | REFUTADA — w_ctx=1.5, RPS 0.1309 vs 0.1275 (p=0.0375) |
> | H6-F1c | REFUTADA — w_rel=1.0, RPS 0.1289 vs 0.1299 (p=0.1948) | REFUTADA — w_rel=**0.0** (Reliability corrigida perdeu todo peso no dev), RPS 0.1309 vs 0.1309 (p=nan) |
> | H7-F1c | REFUTADA — w_pit=0.0, RPS 0.1289 vs 0.1289 (p=nan) | REFUTADA — w_pit=0.0, RPS 0.1309 vs 0.1309 (p=nan) |
> | H8-F1 | REFUTADA — RPS 2026 0.1662→0.1651 (DM p=0.907) | REFUTADA — RPS 2026 0.1631→0.1576 (DM p=0.5035) |
>
> H6-F1c é o resultado mais informativo: o peso ótimo de Reliability no
> período de desenvolvimento caiu de 1.0 para **0.0** depois da correção
> — ou seja, parte do "sinal" que a Fase 4 via em Reliability podia ser
> artefato do próprio bug de DNF (o feature de confiabilidade calculado
> sobre rótulos errados). O veredito já era REFUTADA antes e continua
> REFUTADA depois — a correção não precisou salvar nem derrubar nada,
> mas reforça que não havia sinal real ali.
>
> `data/ratings.json` (Elo vivido do serving) foi recalculado do zero a
> partir do histórico corrigido — Verstappen segue no topo do serving
> (favorito 18,4% no smoke do CI, era 14,5% antes). `data/f1.db` e
> `data/ratings.json` são runtime/gitignored (não entram no commit);
> `backtest_fase1/2/4/5.json`, `trials.json` e o atestado do harness SÃO
> versionados e entram. Suíte: **136 verdes** (+1 teste de `is_dnf`); CI
> 3/3.

> ## 🔧 RESOLUÇÃO DE PENDÊNCIAS (2026-07-20)
>
> Continuação da rodada de evolução final:
> 1. **`build_db` corrigido**: `date >= hoje` pulava a corrida do PRÓPRIO
>    dia mesmo já terminada (só ingeria no dia seguinte); agora `>` —
>    corrida de hoje é buscada e, se ainda não correu, a resposta vazia
>    não vira cache (guard existente). Teste novo cobre os dois lados.
> 2. **GP da Bélgica (R10, 2026-07-19) ingerido** — gatilho natural
>    documentado. `validate_2026.py` rerodado: Antonelli venceu (5ª
>    vitória), acerto de vencedor do blend 2/10, RPS médio 2026
>    elo=0.1654 / grid=0.1334 / blend=0.1425 — o grid puro segue batendo
>    o modelo; gate de operação segue NO-GO. Nenhum snapshot forward de
>    R10 existia (a coleta ainda não começou), então H8 segue 0/15 —
>    a R10 é retropredição como R1–R9, nunca evidência forward.
> 3. **Fixture time-bomb corrigido**: os testes de snapshot usavam R10
>    hardcoded como "corrida futura" e quebraram (7 falhas) no dia
>    seguinte ao GP; agora o fixture escolhe dinamicamente a primeira
>    rodada de 2026 sem resultado no banco.
> 4. **OP-4 (parte f1) verificado**: rebuild OFFLINE do `f1.db` a partir
>    do cache `data/raw/` reproduz o banco vivo com dump lógico SHA-256
>    idêntico — o caminho de backup/restore do f1-predictor é o próprio
>    cache + `build_db` (determinístico). Registrado em
>    `../PENDENCIAS_ABERTAS.md`.
>
> OP-3 (glossário) já estava resolvida em 2026-07-19
> (`../GLOSSARIO_STATUS.md`). Demais pendências do ecossistema são
> `CORRECTLY_DEFERRED`/`REJECTED` por decisão registrada ou exigem ação
> humana (SEC-1) — não reabertas. Suíte: **135 verdes**; CI 3/3.

> ## 🔍 EVOLUÇÃO FINAL — AUDITORIA HOSTIL (2026-07-19)
>
> Rodada de auditoria/testes hostis sobre ingestão, ratings, lifecycle de
> snapshots e gates. **4 bugs reais corrigidos, nenhum científico**:
> 1. `update_ratings` aceitava aliases que resolvem para a MESMA
>    identidade ("Verstappen" + "Max Verstappen") — o dict de posições
>    colapsava silenciosamente (last-wins) e a corrida era processada com
>    n inflado; agora rejeita com erro claro (nada é aplicado).
> 2. `update_ratings` aceitava posição final 0/negativa; agora exige 1..n.
> 3. `predict_race_with_grid` tinha o mesmo colapso silencioso de alias no
>    grid; agora rejeita. Também ganhou `params_file` opcional — e
>    `create_pre_event_snapshot(root=...)` passa a usar OS MESMOS
>    `fase2_params.json` que congela/hasheia no payload (antes o modelo lia
>    do ROOT do processo enquanto a proveniência hasheava o do `root`
>    passado — divergência latente quando root != ROOT).
> 4. `mature_snapshot` agora rejeita resultado com posição final duplicada
>    (empate/corrupção de banco não pode maturar); e 3 strings de erro de
>    `snapshots.py` estavam com mojibake (UTF-8 lido como Latin-1) —
>    corrigidas.
>
> Verificação de estado científico: `H8_REQUIRED_RACES=15` confirmado no
> código; `snapshot-status` real = **0 corridas VALID_FOR_H8** (nenhum
> snapshot forward criado ainda — não confundir com as 9 corridas
> disputadas de 2026, que são retropredição). Gate H8 segue fechado;
> gate de operação segue NO-GO (H1-F1 refutada). Trials: 9 pré-registradas,
> vereditos inalterados. Suíte: **134 verdes** (8 novos testes hostis:
> alias duplicado, posição inválida, empate na maturação, snapshot
> truncado, temporada vazia, coerência de params congelados, determinismo
> independente de ordem). CI 3/3.

> ## ADENDO ECOSSISTEMA (2026-07-18)
>
> Vendor de `predictor_core` byte-idêntico ao canônico, sincronizado em
> `c99a545`. Suíte: 100% verde. Bug real corrigido numa rodada anterior:
> modelo de grid rejeitava múltiplos largadores do pit-lane na posição 0
> (`9ce89a6`). Auditoria hostil adicional 2026-07-18 (DNF e posições
> duplicadas em `update_ratings`): nenhum bug novo — DNF já tratado
> corretamente por design ("quem não está no dict não pontua nem perde"),
> duplicata de posição já rejeitada. Gate H8 segue corretamente fechado:
> `H8_REQUIRED_RACES=15`, só 9 corridas maturadas confirmadas em
> 2026-07-17 (não força conclusão antes da amostra mínima). Sem incidente
> de segurança próprio. Documento canônico do ecossistema:
> `../ECOSYSTEM_HANDOFF.md`.
>
> ## 🔒 SELADO — auditoria final (2026-07-12)
>
> Reconciliação factual posterior confirmou `main` e a branch atual em
> `19e3ec4` (sem commits exclusivos e árvore limpa). A referência anterior
> a `9415c7b` era uma fotografia desatualizada. R1–R9 têm retropredições
> reproduzíveis, mas **0 corridas temporalmente válidas para H8**: não há
> snapshots pré-evento históricos. A coleta forward começa na próxima
> corrida pelo `python -m src.snapshots`; nunca converter R1–R9 em evidência
> forward. O gate de 15 corridas completas e o gate real `NO-GO` permanecem
> congelados. Nenhum H8 deve ser executado sem autorização explícita.
> Próximo gatilho natural: mais corridas de 2026 disputadas — rodar
> `scripts/validate_2026.py` (acompanhamento) e, quando fizer sentido
> pelo calendário, `scripts/run_fase5.py` de novo (H8-F1 pode ganhar
> significância com mais amostra). Até lá, o projeto fica parado por
> design — nenhuma fase nova sem gatilho de dado ou pedido explícito.

> ## 🧪 FASE 5 — CHOQUE ESTRUTURAL DE TRANSIÇÃO DE REGULAMENTO (2026-07-12)
>
> **A pedido do usuário, com protocolo científico próprio dele**: testar
> se "esquecer" parte do Elo acumulado bem na virada de uma temporada
> com regulamento novo (2022, 2026 — mudanças técnicas reais da F1)
> ajuda o modelo a reagir mais rápido. O protocolo original pedia
> calibrar na transição real 2021→2022 e aplicar cegamente em 2026 —
> **mas nosso histórico começa em 2022** (é o burn-in; não há Elo
> acumulado de 2021 pra chocar, a virada de 2022 já é um no-op).
> Adaptei sem avisar depois, avisei ANTES: calibrei o fator só em
> cenário SINTÉTICO (reembaralhamento do campo inteiro numa fronteira
> conhecida) e apliquei o resultado às cegas ao histórico real — 2026
> nunca influenciou a escolha do fator.
>
> **H8-F1 REFUTADA, mas com leitura honesta**: fator calibrado (0.8) via
> harness sintético (sensibilidade+especificidade corretas); aplicado ao
> real, RPS de 2026 melhora na DIREÇÃO certa (0.1662→0.1651) mas SEM
> significância (DM p=0.907) — só 9 corridas disputadas em 2026 não dão
> poder estatístico pra confirmar nem um efeito bem menor que esse.
> 2023-2025 ficam byte a byte idênticos com/sem o mecanismo (só dispara
> nos anos de transição declarados) — confirma que não há efeito
> colateral fora do momento pretendido. Não entra no serving
> (`fase5_params.json`: shrink_factor=0.0). Reavaliar quando 2026 tiver
> mais corridas — `scripts/run_fase5.py` é idempotente.
>
> **Também nesta sessão**: criei um protocolo de validação viva
> (`docs/PROMPT_VALIDACAO_2026.md` + `scripts/validate_2026.py`) que
> retrodiz toda corrida de 2026 já disputada (sem lookahead) e prevê a
> próxima automaticamente — não é pesquisa nova, é acompanhamento
> operacional. Rodando, confirma ao vivo o achado da Fase 1: o grid
> sozinho continua batendo o modelo em 2026 (RPS 0.1339 vs 0.1664 vs
> 0.1433 do blend; acerto de vencedor 2/9 — Antonelli venceu 5).
>
> **Nota operacional**: um `git worktree remove --force` anterior apagou
> os arquivos de trabalho do worktree usado nas Fases 1-4 antes de travar
> na pasta raiz (limitação do Windows — não dá pra apagar o diretório em
> que o próprio processo está rodando). Nada foi perdido de verdade: a
> `main` já tinha tudo mesclado (fast-forward limpo antes da remoção);
> reconstruí `f1.db`/`ratings.json`/`fase2_params.json` da rede e eles
> reproduziram **byte a byte** os `backtest_fase1/2.json` já commitados.
>
> Suíte: **116 verdes** (10 novos); CI 3/3. Relatório:
> `docs/RELATORIO_FASE5.md`.

> ## 🔬 FASE 4 — EMPRÉSTIMOS CROSS-ECOSSISTEMA (2026-07-12)
>
> **A pedido explícito: estudei brasileirao/cs/lol/nba/previsao-cripto/
> wc-predictor-v2 e importei o que era genuinamente reaproveitável.**
> Auditoria factual ANTES de codificar: de 7 itens pedidos, só 1 era
> cópia direta (PrequentialEvaluator+bootstrap do brasileirão) e 1 já
> estava feito (Plackett-Luce). Os outros 5 exigiram desenho novo — nada
> pronto em lugar nenhum do ecossistema.
>
> **Vendor do core sincronizado manualmente** (v1.1.0→v1.3.0), ISOLADO a
> este worktree via replicação da lógica do `sync_core.py` — rodar
> `--write` de verdade tocaria os OUTROS consumidores e o checkout
> principal do f1-predictor, fora do escopo desta sessão. Trouxe
> `kernel/rating.py` (RatingBook), `testing/prequential.py` e
> `measurement/calibration.py`.
>
> **H0-F1-formal COMPROVADA**: portei `GridBaselineEvaluator` e
> `EloPlackettLuceEvaluator` (herdam de `PrequentialEvaluator` do core) +
> bootstrap pareado (padrão exato do brasileirao-predictor) — reconfirma
> a Fase 1 por caminho INDEPENDENTE: RPS grid 0.1304 vs Elo 0.1410,
> bootstrap IC95 [-0.0153,-0.0061] inteiro negativo.
>
> **H5/H6/H7-F1c REFUTADAS** (contexto de circuito via `RatingBook` do
> core por tipo power/downforce/balanced; Reliability via DNF rolling;
> Pit Efficiency via duração rolling — a Jolpica TEM pit stops reais,
> descoberta desta fase, `/pitstops.json`, corrigi dois formatos de
> duração inconsistentes na ingestão). Mecanismo validado em harness
> sintético (sensibilidade+especificidade corretas nos 3), mas sem sinal
> suficiente no dado real — nenhuma entra no serving.
>
> **Lição metodológica que se repetiu 2x (H6 e H7)**: se a força nova
> varia pelo MESMO canal que já determina a ordem de chegada
> historicamente, o Elo aprende sozinho via as próprias atualizações
> pareadas — só há valor incremental genuíno quando a informação é
> PERSISTENTE mas o Elo ainda não convergiu na janela real (poucas
> corridas), ou quando é informação "do dia" que o Elo (memória de
> médias históricas) não pode ver de jeito nenhum. Corrigi os geradores
> sintéticos duas vezes até isolar isso (skill FLAT + efeito
> binário/persistente independente do canal que o Elo já vê).
>
> **Choque de volatilidade pós-patch** (CS/LoL): `VolatilityShock` (K
> temporariamente multiplicado) plugado no `BacktestElo`. Validado SÓ em
> sintético (RPS pós-salto cai de 0.1831→0.1801 com o choque disparado).
> NÃO aplicado a dados reais — sem calendário de upgrades aerodinâmicos
> por equipe, inventar datas violaria a regra de ouro do projeto.
>
> **Purge/embargo** (previsao-cripto): parâmetros opcionais no backtest
> da Fase 4 — checagem de robustez no dado real mostra pesos IDÊNTICOS
> com/sem gap na fronteira dev/eval.
>
> **Intensidade não-homogênea de DNF/SC** (wc-predictor-v2): **fora de
> escopo, honestamente** — exige dado por VOLTA que a Jolpica não tem
> (só classificação final + paradas agregadas). Precisaria de FastF1 ou
> fonte equivalente; registrado como candidato de Fase 5+.
>
> Suíte: **106 verdes** (27 novos); CI 3/3. Relatório:
> `docs/RELATORIO_FASE4.md`.

> ## 🏆 FASE 2+3 — GRID COMO FEATURE, CALIBRAÇÃO, OPERAÇÃO GATED (2026-07-12)
>
> **H3-F1b COMPROVADA: blend Elo+grid (w=0.5, escolhido no dev/2023) bate
> o Elo puro na avaliação CEGA 2024-2026 (RPS 0.1281 vs 0.1416, DM −9.34,
> p≈0) — quase empata com o próprio grid (0.1272). H4-F1b COMPROVADA:
> Platt reduz o Brier do pódio (0.093→0.078), COM RESSALVA: sobrecorrige
> os extremos (P90%+ previsto vira ~74% realizado — não confiar
> literalmente em P(pódio)>85%). H2H entre companheiros sobe para 70.3%
> com o blend (era 62.6% na Fase 1). Fase 3 (Kelly, bet_log, settle,
> OddsProvider) construída e testada, mas o GATE continua NO-GO: ele lê
> o veredito de H1-F1 (Elo vs grid puro), que segue REFUTADA — H3 mede
> outra coisa (grid ajuda o Elo A SE MESMO, não estabelece edge sobre o
> mercado). `record_bet(..., real=True)` levanta PermissionError.**
>
> Pendência da Fase 1 FECHADA: sondei `/v4/sports` da The Odds API com
> chave real do usuário (autorização explícita, só leitura) — 57
> esportes listados, **nenhum é F1/motorsport**. Não há fonte de odds
> reais de F1 nessa API; a Fase 1b está encerrada por falta de fonte.
>
> Lições da Fase 2:
> - **Harness de "grid como feature" precisa de um mecanismo de
>   informação NOVA por corrida** (`form_scale` no gerador sintético: um
>   choque de "forma do dia" compartilhado entre quali e largada) — sem
>   isso, um grid que é só "outra amostra ruidosa da mesma força estática"
>   NUNCA ajuda um Elo já convergido, e o harness confirma incorretamente
>   REFUTADA mesmo com cenário pretensamente "informativo". Achado
>   metodológico reaproveitável em qualquer domínio com feature "do dia"
>   (odds de abertura, forma recente, clima).
> - **w e Platt escolhidos SÓ no dev (2023)**, congelados para a avaliação
>   cega (2024-2026) — mesmo Elo contínuo 2022→2026, só o hiperparâmetro
>   fica confinado ao "treino". Testado: truncar a avaliação não muda w
>   nem Platt.
> - **Platt de 2 parâmetros tem um limite real**: corrige subconfiança no
>   meio da distribuição mas sobrecorrige nos extremos — não dá para
>   "consertar" os dois lados com só 2 graus de liberdade. Reportado
>   com honestidade em vez de escondido (o Brier agregado melhorou, mas
>   a tabela de calibração por faixa é que revela o efeito colateral).
> - **Gate de operação lê a hipótese CERTA**: H1-F1 (Elo vs grid), não
>   H3-F1b (Elo+grid vs Elo puro) — H3 comprovada não é edge de mercado,
>   é só "o grid ajuda o modelo internamente". Ver [[gate-de-operacao]]
>   se essa distinção precisar ser revisitada.
> - Suíte: **79 verdes** (25 novos); CI 3/3. Relatório:
>   `docs/RELATORIO_FASE2.md`.
>
> Próximo passo natural (Fase 4, N+1): DNF/confiabilidade por equipe como
> feature — a Fase 1 já apontava DNF como maior fonte de erro residual do
> Elo. Fase 3 (operação) segue construída e pronta, mas 🔒 NO-GO até H1
> (ou uma hipótese de edge de mercado equivalente) ser comprovada.

> ## 🏁 FASE 1 — BACKTEST ORDINAL (2026-07-12)
>
> **Backtest prequential rodado sobre 101 corridas reais (2022–2026 R9).
> H1-F1 REFUTADA: o Elo puro NÃO bate o grid de largada (RPS 0.1410 vs
> 0.1303, DM +4.43, p=0.00003). H2-F1 COMPROVADA: H2H entre companheiros
> 62.6% (253/404, Wilson95 [0.578, 0.672]). NO-GO para apostas.**
>
> Primeiro backtest ORDINAL do ecossistema — `metrics.rps`, `nullref` e
> Diebold-Mariano do core estrearam com cliente real. Fluxo de governança
> completo NA ORDEM: harness (controle positivo) → atestado → pré-registro
> (`data/trials.json`, versionado) → backtest → resultados nas trials.
>
> Decisões e lições da Fase 1:
> - **Semente do backtest = 1400 para todos** (a semente 2025 da Fase 0
>   seria lookahead dentro de 2022-2025); burn-in 2022, avaliação 79
>   corridas 2023–2026. K novato 40 (<22 corridas vistas), base 24.
> - **Nulo one-hot é armadilha**: o harness pegou — qualquer previsor flat
>   vence ordenações one-hot no RPS (especificidade falhou na 1ª versão).
>   O nulo correto é o **teste de PERMUTAÇÃO** (previsões do próprio
>   modelo, atribuição sorteada): preserva assertividade, destrói
>   informação. Ficou barato via matriz de custo RPS (equivalência com o
>   core testada).
> - **Baselines justos**: grid/standings viram forças pela escada
>   declarada da Fase 0 (1750→1350) e passam pelo MESMO Plackett-Luce.
> - O modelo carrega informação real (percentil 0 do nulo; esmaga o
>   uniforme) e é MELHOR que o grid no vencedor (Brier 0.831 vs 0.846) —
>   perde no meio do pelotão. Pior estrato: 2026 (choque de regulamento).
>   Pódio subconfiante nas faixas altas (Platt = candidata N+1, Fase 2).
> - **Jolpica**: 429 na primeira carga (retry/backoff implementado);
>   resposta vazia de corrida futura NÃO pode virar cache imutável (bug
>   corrigido + teste). Rate limit cortês 1s; cache `data/raw/` gitignored.
> - Serving agora usa o **Elo vivido** (`data/ratings.json`, só grid 2026;
>   filtro no model.py impede aposentados de entrar no grid do serving).
>   Novo topo: Verstappen 1696 > Norris 1680 (a semente 2025 dava Norris).
> - Suíte: **50 verdes** (25 novos); CI 3/3. Relatório:
>   `docs/RELATORIO_FASE1.md`.
>
> Próximo passo (Fase 2, cada variação = trial N+1 pré-registrada): grid
> de largada como FEATURE do modelo (Elo + grid, não Elo vs grid — alvo
> nº 1 do relatório), DNF/confiabilidade por equipe, Platt no headline.
> Fase 1b (odds): H2H é o único sinal comprovado — sondar `motorsport_f1`
> na The Odds API quando houver chave. Fase 3 segue 🔒 NO-GO.

> ## 🏎️ CRIAÇÃO (2026-07-11)
>
> **Projeto criado. Modelo Elo para pilotos implementado. Diferencial:
> previsão ordinal com RPS (métricas do core). Backtest e operação real
> pendentes.**
>
> Oitavo consumidor do predictor_core (v1.1.0, vendor via `sync_core
> --write`). Python 3.13 em `.venv`. PRIMEIRO domínio ordinal do ecossistema
> — o RPS e o nullref.py do core ganham cliente na Fase 1.
>
> Decisões da Fase 0:
> - **Plackett-Luce = extensão multiclasse do Elo**: forças 10^(elo/400),
>   ordenação simulada via truque de Gumbel (20k sims, seed 13,
>   determinístico); H2H em fórmula fechada CONSISTENTE com a marginal do
>   PL (mesma logística). Testes verificam Σwin=1, Σpódio=3, Σtop6=6.
> - **update_ratings pareado**: todo par da ordem de chegada, K/(n−1) por
>   par, K médio do par com novato=40 vs base=24 (progressão rápida),
>   soma zero. DNF/ausente fica de fora (não pontua nem perde).
> - **Dados REAIS via Jolpica** (api.jolpi.ca, sucessor mantido do Ergast,
>   sem chave — sondagem 2026-07-11): grid 2026 tem **22 pilotos/11 equipes**
>   (Cadillac entrou: Bottas+Pérez; o prompt assumia 20/10 — corrigido com
>   fonte). Standings 2026 correntes mostram a sacudida do regulamento novo
>   (Antonelli líder, Verstappen 7º) — mas a SEMENTE segue a regra do
>   prompt: campeonato FINAL de 2025 (Norris 1750 → linear → 1350;
>   Lindblad novato 1300; Bottas/Pérez retornantes 1400 declarado).
> - **Calendário 2026 real** (22 rodadas, incl. Madring novo). As
>   características de circuito (power/downforce/tire_wear) são estimativa
>   qualitativa DECLARADA — metadados para a Fase 1+; o modelo da Fase 0
>   não as consome (circuit/weather só são validados).
> - Governança desde o dia zero: PredictionPoint com value=ORDENAÇÃO
>   (formato do RPS), telemetria domínio `f1`, log append-only com override
>   por env; CI 3 barreiras; integridade do vendor + higiene de repo;
>   `.gitattributes` eol=lf.
> - Suíte: **25 verdes**.
>
> Próximo passo (Fase 1, prompt separado): histórico de corridas via
> Jolpica (`/f1/<season>/<round>/results.json`), backtest prequential
> ordinal — RPS do ranking previsto vs realizado, nullref (seletores
> aleatórios) como piso de significância, Diebold-Mariano vs baseline
> "grid de largada" — e o fluxo de governança da plataforma (harness →
> TrialRegistry → GO/NO-GO) antes de qualquer aposta.

## Atualização Stage 0 — Gate de viabilidade Market H2H (2026-07-21)

**Veredito: `MARKET_H2H_NOT_FEASIBLE`.** Há zero fontes aceitas e zero quotes;
logo não há backtest econômico. The Odds API permanece rejeitada por ausência
de F1 na sonda local. SportsDataIO, Sportradar/Betradar e Betfair exigem
decisão humana sobre licença, cobertura `race_h2h`, timestamps e settlement.

Foram adicionados os contratos isolados `src/data/market_h2h.py` e
`src/data/fastf1_contract.py`, a evidência `data/market_h2h_feasibility.json`,
a trial de governança `G0-F1-market-h2h-feasibility` e testes hostis. FastF1
não foi integrado nem coletado; rating/modelo não mudaram. O gate não escolhe
automaticamente uma opção de cobertura. Detalhe completo:
`docs/RELATORIO_MARKET_H2H_FEASIBILITY.md`.

Atualização 2026-07-22: criado `docs/PAST_ATTEMPT_LEDGER.md`, preservando H1,
H8, ratings, DNF, FastF1, telemetria, treino/classificação/ritmo, H2H, datasets,
fontes, cobertura e gates. O contrato H2H agora exige `season`, `race_id`,
timestamps distintos de opening/closing e `decision_at`, bloqueando closing
posterior. OddsPapi é somente `SOURCE_PARTIALLY_ACCEPTED` para diligência;
continua inelegível para ingestão ou Stage 1.

## O que é o projeto

Laboratório de previsão de corridas de F1 (vencedor, pódio, top6,
head-to-head) — Fase 0. Roda 100% local. Idioma do projeto: português.
NÃO é ferramenta de investimento; nenhum edge foi demonstrado.

Máquina do Leo: Windows, `C:\Claude-projetos\Claude\f1-predictor`,
venv `.venv` (Python 3.13.14), atrás de proxy corporativo Volvo.
