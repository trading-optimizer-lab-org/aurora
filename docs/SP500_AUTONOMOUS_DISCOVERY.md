# SP500 Autonomous Discovery

## Purpose

Find a daily SPY rule that is always invested, uses only `-1` or `+1`, has
zero costs, and survives the frozen train gates. The campaign does not build
a portfolio and does not select a rule from validation.

## Execution order

1. `preflight` checks the frozen specification, candidate contract, workflow,
   and date boundaries.
2. `research` and `data_build` publish source and boundary evidence before
   any search batch.
3. `pilot` exercises the real workload on a small pre-registered batch.
4. `search_batch` generates a deterministic batch, registers every candidate,
   evaluates chronological train returns, writes metrics and multiplicity
   evidence, and either dispatches the next batch or freezes finalists.
5. `merge_batch`, `statistical_gate`, `freeze`, and `verify` independently
   check a completed train artifact and its boundary/reconciliation evidence.
6. `validation_once` is dispatched only from a successful train freeze and
   requires `OPEN_VALIDATION_2011_2020_ONCE_AUTONOMOUS`.

The controller never opens validation when a batch has no eligible finalist.
The locked period starts at `2021-01-01` and is never requested by the data
preparation or validation code.

## Provenance

Candidate IDs and canonical hashes are generated before evaluation. Effective
rules are hashed without identity, notes, job placement, or research-only
metadata. Changing a rule changes its hash and creates a new candidate ID.

The result artifact includes the batch registry, train OOF returns, annual
metrics, candidate leaderboard, rejection ledger, bootstrap/multiple-testing
evidence, train freeze record, feature-store manifest, cost-balanced job
manifest, canonical dedupe map, pre-registration manifest, trial ledger, and
an autonomous batch summary. The trial ledger assigns every candidate a
monotonic global index before performance is calculated, including the 312
previously registered trials. The FeatureStore is keyed by symbol, snapshot
hash, code revision, and date range; only formulas proven equivalent to the
original signal engine use its cached values, while unsupported formulas keep
the original path. All heavy work runs on GitHub Actions; local verification
is limited to syntax, schema, and small synthetic tests.

## Scientific boundary

Train ends on `2010-12-31`. Validation covers `2011-01-01` through
`2020-12-31` exactly once and cannot influence candidate selection. No result
from `2021-01-01` onward is loaded by this campaign.
