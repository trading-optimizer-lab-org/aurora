# Task 1 Report: Exact economic campaign planning

## Scope

Implemented only the assigned GTBI planner and focused tests:

- `scripts/gtbi_fast_strict.py`
- `tests/test_gtbi_fast_strict.py`

The requested report is this file. Existing unrelated work under `.superpowers/` and `docs/plans/` was left unchanged.

## TDD evidence

1. Added the focused test suite before production implementation.
2. Ran `C:/Python314/python.exe -m pytest tests/test_gtbi_fast_strict.py -q`.
3. The initial result failed at collection because `scripts.gtbi_fast_strict` did not exist, which was the expected RED state.
4. Implemented the minimum planner functionality.
5. The first GREEN run found one test expectation that conflicted with the specified fixed matrix boundary (`0..179` / `180..359`); the test was corrected for its two-worker fixture.
6. Added coverage for the actual 360-worker matrix and 20 blocks of 18 workers.

## Implementation

- `economic_evaluation_hash(candidate)` hashes only `candidate.config.to_dict()` using deterministic SHA-256 JSON.
- `strategy_pack_digest(pack_path)` hashes sorted relative file paths and their bytes.
- `campaign_fingerprint(...)` binds the required code, pack, data, date, universe, execution and dependency inputs.
- `create_campaign_plan(...)` loads all candidates through `load_external_strategy_candidates`, validates identities and count, groups economic equivalents, selects representatives by global slot then strategy ID, and schedules groups with deterministic LPT.
- Planner writes the canonical 360-shard pack under default settings, alias map, worker manifest, matrix A/B, 18-worker blocks, and campaign manifest.
- Canonical rows retain their representative payload, retain original source identity, and receive worker-local shard and slot identities.
- The CLI exposes the required defaults and provenance inputs.

## Verification

Commands run:

```powershell
& 'C:/Python314/python.exe' -m pytest tests/test_gtbi_fast_strict.py -q
& 'C:/Python314/python.exe' -m ruff check scripts/gtbi_fast_strict.py tests/test_gtbi_fast_strict.py
& 'C:/Python314/python.exe' -m scripts.gtbi_fast_strict --help
```

Results:

- Focused tests: `21 passed in 1.84s`.
- Ruff: `All checks passed!`.
- CLI help: completed successfully.

No backtests or research campaigns were run.

## Concerns

None. The implementation uses the evaluator's existing private cost estimator, `_estimated_cost_score`, because it is the established GTBI cost model used to order work.

## Review fixes

The first review found identity and provenance gaps. The follow-up change:

- validates non-empty strategy IDs, shard range 0..359, slot range 0..199,
  and global range 0..71999;
- rejects unsupported strategies and stale output directories;
- requires 3,600 unique economic groups by default;
- uses strictly positive scheduling costs while preserving the raw score;
- emits GitHub-native matrix objects;
- records SHA-256 and byte size for all canonical shards and planning files.

Fresh verification after these fixes:

```text
30 passed in 5.78s
All checks passed!
```
