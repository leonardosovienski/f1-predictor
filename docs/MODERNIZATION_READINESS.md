# Modernization readiness

## Coverage scopes

Coverage is measured with `coverage run --branch -m pytest`. The homologated
runtime is `config`, `clock`, `contracts`, `repositories`, `services`, `cli`,
`closure`, `snapshots`, `archival_collection`, and `data/*` providers/storage.
Research/migration/legacy is `backtest`, `context_factors`, `manual_approval`,
historical expansion, phase scripts, and compatibility CLIs. CI publishes
global and per-module reports; no file is omitted from global coverage.

Final branch-aware result: **86.30% global**, **82.14% homologated runtime**,
and **93.36% research/migration/legacy**. Lower individual runtime modules are
reported rather than hidden: snapshot orchestration 78%, Jolpica provider 77%,
database 79%, API-Sports 79%, OpenF1 75%, odds stub 73%, and compatibility
prediction CLI 70%. Their exercised fail-closed behavior plus the strongly
covered contracts/services/repositories keep the complete runtime above 80%.

## Skip audit

All 16 baseline skips were eliminated. Operational inputs are generated before
test collection by `tests/conftest.py`, using sanitized deterministic data in a
temporary/ignored runtime substrate. CI runs the full official `dev` extra.

| Baseline test | Reason | Missing artifact | Origin | Untested risk | Fixture possible | CI job | Final decision |
|---|---|---|---|---|---|---|---|
| `test_ratings_vividos_sao_do_grid_2026` | runtime output absent | `ratings.json` | backtest | invalid live ratings | yes | quality 3.13/3.14 | deterministic ratings; executed |
| `test_vendor_manifest_files_are_tracked` | vendor removed | vendor manifest | retired sync | accidental vendor return | obsolete | quality 3.13/3.14 | replaced by vendor-absence assertion |
| `test_valid_snapshot_is_deterministic...` | runtime substrate absent | DB/ratings/phase2 | ingestion/backtest | nondeterminism/write | yes | quality 3.13/3.14 | generated; executed |
| `test_rejects_naive_and_late_timestamp` | same | same | same | temporal boundary | yes | quality 3.13/3.14 | generated; executed |
| `test_accepts_multiple_pit_lane...` | same | same | same | valid pit-lane grid | yes | quality 3.13/3.14 | generated; executed |
| `test_still_rejects_duplicate...` | same | same | same | corrupt grid | yes | quality 3.13/3.14 | generated; executed |
| `test_rejects_existing_result...` | same | same | same | lookahead/overwrite | yes | quality 3.13/3.14 | generated; executed |
| `test_detects_hash_tampering...` | same | same | same | hash/maturity | yes | quality 3.13/3.14 | generated; executed |
| `test_mature_rejects_duplicate...` | same | same | same | invalid official result | yes | quality 3.13/3.14 | generated; executed |
| `test_rejects_premature_maturation...` | same | same | same | premature maturity | yes | quality 3.13/3.14 | generated; executed |
| `test_atomic_create_has_exactly...` | tools checkout absent | tools provenance | sibling checkout | concurrent publication | yes | quality 3.13/3.14 | installed wheel provenance; executed |
| `test_corrected_result_invalidates...` | tools checkout absent | tools provenance | sibling checkout | result correction | yes | quality 3.13/3.14 | installed wheel provenance; executed |
| `test_truncated_snapshot_file...` | same | same | same | partial artifact | yes | quality 3.13/3.14 | generated; executed |
| `test_snapshot_status_empty...` | substrate absent | DB/ratings/phase2 | ingestion/backtest | empty gate count | yes | quality 3.13/3.14 | generated; executed |
| `test_pre_event_uses_same_params...` | tools checkout absent | tools provenance | sibling checkout | provenance mismatch | yes | quality 3.13/3.14 | installed wheel provenance; executed |
| remaining operational snapshot case | substrate absent | DB/ratings/phase2 | ingestion/backtest | fail-closed branch | yes | quality 3.13/3.14 | generated; executed |

Current expected result: zero skips. A future deliberate conditional test must
be added to this table and to a CI job that supplies its declared prerequisite.

## Windows scheduler migration

Retired files:

- `scripts/install_archival_collection_task.ps1`;
- `scripts/install_forward_snapshot_task.ps1`.

The forward task was already disabled by the H8 closure and must not be
recreated. The archival equivalent is the `f1-archival-collection` entry point,
declared as `COLLECTION_ONLY` in `scheduler.example.yaml` and run by
`predictor-ops`.

Migration:

1. Install the domain and shared release wheels in a Python 3.13 environment.
2. Validate with `f1-predictor health --offline`.
3. Import `scheduler.example.yaml` into the platform scheduler configuration.
4. Run one archival job and verify its terminal heartbeat and
   `COLLECTION_ONLY` status.
5. Disable the old Windows task; retain its exported XML outside the checkout
   for one rollback window.
6. After one successful weekly cycle, delete the old task.

Rollback disables the portable job and reimports the operator-owned Task
Scheduler XML. It does not restore source scripts, enable H8/H2H, or change
scientific gates. Removal is final once one portable weekly cycle, heartbeat,
artifact hash, and health check have passed. Task Scheduler is never the
primary runtime again.

## Shared dependency contract

Runtime imports must resolve from installed distributions. Contract tests and
wheel smoke assert `predictor_core` 2.2.0 and `predictor_ops` 3.0.0 from
`site-packages`; searches reject vendor, `PYTHONPATH`, `sys.path` mutation,
sibling imports, and `tools.*`. Release wheels in `wheels/` are binary build
inputs only, not importable source trees.

The wheel hashes are pinned by `uv.lock`; CI installs those immutable release
artifacts and exercises the commands outside the checkout.
Scheduler contract tests exercise success, timeout cleanup, heartbeat, and
terminal failure directly in-process with `ResourceWarning` promoted to error.

## predictor_ops 3.0.0 migration validation (2026-08-09)

- dependency and lock constraint: `predictor-ops>=3,<4`;
- clean wheel install: version 3.0.0 loaded from `site-packages`;
- operational `run_status` remains separate from opaque `scientific_state`;
- scheduler lifecycle: success, timeout cleanup, heartbeat and terminal failure;
- suite: 217 passed with `ResourceWarning` promoted to error;
- branch coverage: 86% global (82.14% homologated runtime scope);
- container: UID 10001, read-only filesystem and offline health smoke passed;
- scientific closure hashes and golden contracts remained valid.

Readiness remains **READY**.
