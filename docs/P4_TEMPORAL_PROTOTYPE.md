# P4-A temporal contract prototype

This is an experimental, test-only adapter. It is not a public F1 or Core API,
does not modify the snapshot schema, and is not connected to collection,
scheduling, serving, settlement, H8, or any canonical pipeline.

The synthetic contract tests call the canonical F1 snapshot functions with
offline fakes, then map the resulting PRE_EVENT/MATURED pair to a small private
record. The adapter adds explicit `cutoff_at` and `result_available_at` guards,
reuses Core `PredictionPoint` and replay, preserves the native F1
`winner_brier` scale, and compares concrete values and hashes to a checked-in
golden. All fixtures are synthetic.

Gap classification:

| Concern | Classification |
|---|---|
| aware prediction/maturity clocks and replay | `CORE_CONTRACT_SUFFICIENT` |
| cutoff, event start, result publication and artifact links | `CONSUMER_ADAPTER_REQUIRED` |
| generic canonical JSON/hash helper | `POSSIBLE_FUTURE_CORE_CANDIDATE` |
| grid, driver identity and winner Brier | `DOMAIN_SPECIFIC` |
| Core allowing `matures_at == predicted_at` vs event maturity | `SEMANTIC_CONFLICT` unless the consumer guard remains |

P4-B must not start until this pilot and its draft PR receive explicit human
approval.
