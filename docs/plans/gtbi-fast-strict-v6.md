# GTBI Fast Strict V6

## Objective

Complete the 72,000-strategy long-hold campaign in GitHub Actions with exact
economic equivalence, zero final timeouts, no synthetic rows, and immutable
provenance.

## Global Constraints

- Preserve the strategy pack, economic entry/exit logic, long/cash execution,
  universe, score, and data.
- `train_end=2010-12-31`.
- `validation_start=2011-01-01`.
- `validation_end=2020-12-31`.
- `locked_start=2021-01-01`; no data on or after that date may enter train or
  validation.
- Drawdown remains informational and cannot affect the no-drawdown score.
- Heavy execution runs only in GitHub Actions.
- Final success requires exactly 72,000 terminal strategy identities, zero
  missing/extra/overlap/timeout/synthetic/runtime/unsupported/deferred rows.

## Task 1: Exact economic planning

Add a dedicated module and tests that:

- hashes only the effective `IndicatorConfig` for economic equivalence;
- keeps the existing canonical provenance hash unchanged;
- groups the 72,000 identities by economic hash;
- deterministically chooses one representative per group;
- balances unique groups over exactly 360 workers with LPT scheduling;
- emits 360 canonical strategy shards, an alias map, two 180-worker matrices,
  twenty merge-block manifests, and a campaign manifest;
- binds the campaign manifest to code SHA, strategy-pack digest, data identity,
  dates, locked boundary, universe rules, and execution mode.

## Task 2: Exact alias expansion and strict merge

Add tests first, then implementation that:

- expands canonical leaderboard and final-reject rows to every original alias;
- preserves alias-specific research metadata while copying only economic
  metrics from the representative;
- expands yearly rows and diagnostics deterministically;
- records the canonical representative for every alias;
- rejects conflicting duplicate results before any deduplication;
- fails closed on campaign-fingerprint mismatch;
- produces 72,000 terminal identities without synthetic timeout rows.

## Task 3: Persistent worker path

Add tests first, then a worker command that:

- loads one canonical shard and the immutable data pack once;
- invokes V5 in `combined` phase once for all unique strategies in that shard;
- disables the currently unproven signal proxies and approximate early stops;
- uses exact feature/cache keys;
- emits a compact worker artifact containing canonical outcomes and only the
  trade detail needed by the final reports;
- validates campaign and data digests before evaluation.

## Task 4: Hierarchical merge

Add tests first, then block/final reducers that:

- merge eighteen worker artifacts into each of twenty block artifacts;
- scan files once and concatenate deterministically;
- reject duplicate canonical IDs with non-identical content;
- final-merge only the twenty blocks;
- publish `_SUCCESS` only after every strict invariant passes.

## Task 5: Single GitHub workflow

Create a registered workflow that:

- builds the immutable data pack and global plan once;
- runs two matrices of 180 workers concurrently;
- uses `ubuntu-latest`, one combined evaluator process per worker, and pip
  caching;
- has two internal missing-worker retry rounds;
- performs twenty block merges and one strict final merge;
- never dispatches child workflows or performs manual recoveries;
- uploads intermediate artifacts briefly and the final artifact under
  `global-technical-buy-indicator-long-hold-fast-strict-v6-results`.

## Task 6: Verification and execution

- Run the focused Python tests, full GTBI test file, `py_compile`, and YAML
  validation.
- Commit and push to `codex/gtbi-github-only-external-pack-72000`.
- Run a GitHub differential smoke against the legacy full evaluator with all
  unsafe early rejects disabled.
- Only after exact equality is proven, launch one full workflow and monitor it
  through a strict final artifact.

