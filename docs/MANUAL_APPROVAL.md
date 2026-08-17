# Aprovação manual

Mesmo após o gate estatístico retornar `GO`, `--real` exige um JSON local com
`schema_version: 1`, `status: "APPROVED"`, `approval_id`, `approved_by`,
`approved_at`, `expires_at` e `bet_fingerprint`. O fingerprint deve ser o da
ordem exata, incluindo seu `strategy_id`; aprovação expirada, futura ou para
estratégia, odds ou seleção diferentes falha.

O projeto somente registra o bilhete no ledger. Ele não envia ordem para uma
casa de apostas nem armazena credenciais de corretora.
