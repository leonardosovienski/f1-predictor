# Operação da Zona 1 de mercado

## Escopo e invariantes

A Zona 1 recebe lotes licenciados de mercados H2H de Fórmula 1 para arquivo e
avaliação de qualidade. Ela opera exclusivamente com
`scientific_state=COLLECTION_ONLY`: importar um lote ou obter um scorecard não
autoriza backtest, aposta, alteração de hipótese, nem reabertura da Zona 2.

O operador não deve alterar `data/authorized_closure.json`, chamar o caminho
legado de `market_h2h` ou interpretar `MARKET_H2H_FEASIBLE_FOR_PROTOCOL_DESIGN`
como GO científico. Toda promoção além da Zona 1 requer decisão humana
registrada e um protocolo previamente congelado.

## Formato do lote

Cada diretório contém um manifesto JSON e um ou mais arquivos JSON. Os arquivos
de dados contêm uma lista de objetos `MarketRecord`, validados estritamente por
`src/market_collection/contracts.py`.

```json
{
  "schema_version": "market-raw-batch/1",
  "batch_id": "provider-2026-08-09-001",
  "provider": "licensed-provider",
  "received_at": "2026-08-09T12:00:00Z",
  "obtained_by": "operator-id",
  "licence_reference": "contract-or-export-reference",
  "licence_allows_research_storage": true,
  "licence_allows_derived_results": true,
  "source_schema_version": "provider-export/1",
  "source_files": [{
    "path": "markets.json",
    "size_bytes": 12345,
    "sha256": "64-lower-or-upper-hex-characters"
  }],
  "export_parameters": {},
  "notes": "Operator notes"
}
```

Calcule tamanho e SHA-256 sobre os bytes exatos recebidos. Os caminhos precisam
ser relativos ao manifesto e não podem escapar do diretório. O import falha
fechado se licença, schema, tamanho, hash, identidade, timestamps ou qualquer
registro forem inválidos. Não edite o lote depois de calcular os hashes.

## Importação controlada

1. Preserve o lote original em uma área de entrada somente leitura.
2. Confirme a referência da licença com a pessoa responsável.
3. Instale a wheel aprovada em um ambiente Python compatível.
4. Execute:

   ```text
   f1-market-import --manifest <lote>/manifest.json --archive <arquivo>/market_archive.db
   ```

5. Registre stdout, stderr, código de saída, versão da wheel e hash do manifesto.

Sucesso retorna `run_status="SUCCEEDED"`,
`scientific_state="COLLECTION_ONLY"` e `result.state="NORMALIZED"`. Reexecutar
o mesmo `batch_id` e manifesto é idempotente. O mesmo ID com conteúdo diferente
falha. Qualquer erro causa rollback integral.

Cotações in-play ou publicadas depois do início agendado são preservadas para
auditoria, mas recebem `eligible_for_decision=false` e
`ineligibility_reason="IN_PLAY_OR_POST_EVENT"`.

## Scorecard e gates congelados

```text
f1-market-quality --archive <arquivo>/market_archive.db --scheduled-races <n>
```

| Opção | Duelos | Corridas | Temporal | Bookmakers | Uso permitido |
| --- | ---: | ---: | ---: | ---: | --- |
| `pilot_diagnostic_not_stage1` | 100 | 60% | 95% | 2 | diagnóstico apenas |
| `intermediate_descriptive_only` | 250 | 70% | 97% | 2 | descrição apenas |
| `stage1_authorization_candidate` | 500 | 80% | 98% | 3 | candidato a decisão humana |

Sem `--selected-option`, o resultado é `MARKET_H2H_NOT_FEASIBLE` ou
`MARKET_H2H_REQUIRES_HUMAN_DECISION`. Para avaliar uma opção explicitamente:

```text
f1-market-quality --archive <arquivo>/market_archive.db --scheduled-races <n> --selected-option stage1_authorization_candidate
```

Mesmo `MARKET_H2H_FEASIBLE_FOR_PROTOCOL_DESIGN` não autoriza análise ou
reabertura. Revise ainda `both_sides_coverage`, `settlement_coverage`,
`volume_coverage` e `ambiguous_identities`; identidade ambígua fica bloqueada.

## Checklist do primeiro lote real

- [ ] Aprovação humana e referência explícita da licença registradas.
- [ ] Licença permite armazenamento para pesquisa e resultados derivados.
- [ ] Original preservado sem transformação e com acesso restrito.
- [ ] Manifesto completo; IDs e horários UTC conferidos.
- [ ] Tamanho e SHA-256 recalculados independentemente.
- [ ] Wheel, commit, ambiente, operador e horário registrados.
- [ ] Import controlado terminou `NORMALIZED`.
- [ ] Reexecução idempotente confirmada sem duplicação.
- [ ] Scorecard usa o número correto de corridas programadas.
- [ ] Cobertura, ambos os lados, settlements, volume e identidades revisados.
- [ ] Zona 2 e `authorized_closure.json` não foram alterados.
- [ ] Lote, manifesto, logs e scorecard preservados para auditoria.
- [ ] Qualquer avanço foi encaminhado para decisão humana; nenhum GO automático.
