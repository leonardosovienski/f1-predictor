# F1 archival COLLECTION_ONLY handoff for tools

`scripts/run_archival_collection.py` is the only entrypoint for this track.
It archives calendar-aware official sporting facts from the existing Jolpica
provider; it does not access odds, create a Market DB, invoke H8/H2H, evaluate
a model, create a trial, or alter a gate.

## Storage and lifecycle

Runtime data is isolated under `data/collection_only/` (ignored by Git):

- `archive.jsonl`: append-only `CollectionArchive` transitions;
- `snapshots/<collection_run_id>/`: source snapshots for a race weekend.

Each envelope uses the predictor-core `COLLECTION_ONLY` contract with a new
`collection_run_id`, `canonical_event_id`, schedule/observation timestamps,
Jolpica source record, provenance hash, source snapshot hash, project commit,
core version, event/circuit/sessions, drivers, teams and official results.

Lifecycle is `DISCOVERED → VALIDATED → SNAPSHOT_RECORDED`; after the scheduled
start it records `EVENT_STARTED`; an available official result adds
`OFFICIAL_RESULT_FOUND → COMPLETE`. Missing result before/after an event is not
invented. Empty/currently irrelevant calendars return `NO_UPSTREAM_EVENTS` and
do not create storage. Provider retry remains the existing Jolpica backoff.

## Scheduler

`scripts/install_archival_collection_task.ps1` registers
`f1-archival-collection` for Friday and Sunday at 18:00 local time: two
weekend-oriented checks, not daily polling. It runs through the canonical
`tools/operational_runner.py`, with a lock, 300-second timeout, external
heartbeat/event log and an atomic consumer-status file under
`%LOCALAPPDATA%\\predictor-tools\\runtime`. The entrypoint itself performs the
calendar window decision; `NO_UPSTREAM_EVENTS` and `SOURCE_UNAVAILABLE` are
preserved as explicit heartbeat statuses rather than being collapsed into a
generic successful run.

## Closure protection

Before every collection the closure record and preserved hashes are verified.
H1 remains `HYPOTHESIS_REFUTED`; the original operation remains
`NO_GO_CONFIRMED`; H8/H2H remain `CLOSED_BY_HUMAN_DECISION`. No collection
artifact can be promoted to a trial/gate under the core contract. The one
permitted historical exception is a vendor manifest changed by canonical
`sync_core.py`; it is accepted only when byte-identical to the canonical core.
