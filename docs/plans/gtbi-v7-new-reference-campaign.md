# GTBI V7 New Reference Campaign

## 1. Decision

This campaign is a new research product. It is not a continuation,
reproduction or correction of GTBI Fast Strict V6.

```text
campaign_id=gtbi_v7_new_reference_v1
product=GTBI V7 Performance Engine New Reference
source_campaign=gtbi_v7_frozen_local_reference_candidate_v1
execution_environment=GitHub Actions only
maximum_incremental_net_spend_usd=0
historical_exclusion_start=2021-01-01
locked_authorized=false
```

The repository owner explicitly accepts that the frozen data lake uses a
static post-period universe, is survivorship biased and cannot authenticate
historical point-in-time membership. Results must always carry those limits.

## 2. Immutable Scientific Boundary

```text
train_end=2010-12-31
validation_start=2011-01-01
validation_end=2020-12-31
historical_exclusion_start=2021-01-01
locked_data_accessed=false
long_only=true
cash_allowed=true
next_session_open=true
minimum_market_cap_usd=2000000000
```

No workflow, smoke, benchmark, test fixture or merge may read or derive a
scientific value from a row dated on or after `2021-01-01`. Locked execution
requires a later, explicit owner authorization and is outside this campaign.

## 3. Frozen Inputs

The sole price-data source is the already published private release:

```text
repository=trading-optimizer-lab-org/aurora-v7-assets
release_tag=gtbi-v7-frozen-data-lake-v1
release_id=362286563
archive_sha256=sha256:5a77dc20ffcc8769e0dabe38811d50664f6f3ab6d8ac262c17d39dc7b86070b5
archive_size_bytes=3252295680
source_file_count=10678
```

The campaign must download these immutable parts in GitHub Actions, verify
every part and reconstructed archive digest before extraction, then create a
historical execution pack containing only rows before the exclusion boundary.
No provider download or refresh is permitted during this campaign.

The strategy source is the 72,000-strategy long-hold fundamental timing pack.
Its complete file inventory and canonical digest are frozen before the first
benchmark. Effective duplicates may be evaluated once only when every alias is
expanded back into the final results without changing metrics or provenance.
The 360 verbose JSONL shards are stored as one deterministic ZIP plus a
canonical per-shard inventory. Preparation and final merge verify the ZIP and
every uncompressed shard before materializing it. This reduces the repository
payload by roughly 200 MB without changing any strategy byte.

## 4. Required Limitations

Every result, manifest and report must state:

- separate from V6;
- not V6-equivalent;
- survivorship biased;
- not a point-in-time universe;
- retrospectively adjusted reference data;
- historical causal claims prohibited;
- locked not opened;
- no data after `2020-12-31` used for train or validation.

The campaign may compare runtime with the preserved V6 engineering run, but
must not attribute result differences solely to engine changes because the
input identity is different.

## 5. Implementation Phases

### NR0: Authorization And Identity

- Publish the canonical owner-authorization receipt.
- Bind the proposal, frozen release, plan, budget and old V6 terminal closure.
- Keep the closed V6 task and gate records immutable.
- Create a separate V7 campaign status and evidence namespace.

### NR1: Reference Engine

- Restore the last pre-locked Fast Strict engine from commit
  `cb80c5065c127322a303d58aea0f6c05337a6c9e` as read-only scientific reference.
- Exclude every later locked-mode and clean-portfolio change.
- Freeze its code tree, dependency lock, pack digest and output schemas.
- Prove next-session-open, long/cash, annual split and exclusion-boundary rules.

### NR2: V7 Performance Engine

- Extract the GTBI evaluator into owned Aurora modules.
- Build one immutable feature store per data identity.
- Share feature and entry-signal work across equivalent strategies.
- Use process-based parallelism for independent CPU work.
- Limit numerical-library threads so total active CPU work never exceeds the
  runner's measured CPU allocation.
- Select one, two or four workers from separate cold end-to-end GitHub runners.
- Use NumPy arrays in trade simulation and avoid row-by-row DataFrame loops.
- Add safe early rejection only where final failure is mathematically certain.
- Balance work by measured cost and memory rather than strategy count alone.
- Write compact worker outputs, hierarchical merges and selective recovery.

### NR3: Equivalence

- Compare reference and V7 on synthetic fixtures and a frozen real-data sample.
- One, two and four-worker modes must produce identical canonical scientific
  rows, trades, dates, returns and annual metrics.
- Reference and optimized output differences fail closed.
- Runtime diagnostics cannot affect strategy results.

### NR4: GitHub Smoke And Benchmark

- Run only in GitHub Actions on `ubuntu-24.04`.
- Verify actual CPU and memory capacity before work starts.
- Benchmark the same immutable sample with one, two and four workers.
- Measure checkout, download, verification, extraction, feature build,
  signals, simulation, merge and artifact publication separately.
- Accept the fastest equivalent mode, even when that is not four workers.
- A 100-job smoke must finish with zero missing, timeout, unsupported,
  synthetic or runtime-error strategy identities.
- Benchmark and smoke receipts must match the exact campaign fingerprint and
  Git commit used by the full run.

### NR5: Full Historical Campaign

- Freeze one immutable campaign manifest before dispatch.
- Evaluate all 72,000 strategy identities through the selected mode.
- Use up to the verified account concurrency without exceeding account limits.
- Build the full matrix dynamically from the winning process mode so all 360
  logical workers run in one wave, with up to 360 GitHub jobs in parallel.
- Recover only exact missing work units; never rerun a successful full range.
- Merge through bounded blocks and publish one final immutable artifact.
- Require exactly 72,000 terminal identities and no overlap or invented rows.

### NR6: Selection And Final Report

- Apply the unchanged final filters and ranking frozen in the campaign
  manifest.
- Publish leaderboard, filtered leaderboard, yearly performance, rules,
  diagnostics, timeout/error tables, benchmark report and provenance.
- Report complete and rejected strategies separately.
- Compare measured V7 runtime with the reference benchmark and calculate the
  reduction percentage from equal workloads only.
- Preserve the final artifact in the approved private GitHub asset stores.
- Publish a deterministic, hashed private GitHub release after the final
  artifact passes every validation gate.

## 6. Acceptance Criteria

The historical V7 campaign is complete only when all conditions are true:

1. Authorization and campaign manifests are canonical and digest-valid.
2. Frozen data and strategy inputs match their declared digests.
3. Locked access is false in every job and artifact.
4. Reference and optimized scientific outputs are identical on the complete
   equivalence suite.
5. One, two and four-worker tests are deterministic.
6. The selected worker mode is the fastest measured equivalent mode.
7. The 100-job smoke is complete and internally consistent.
8. The full result contains exactly 72,000 terminal strategy identities.
9. Missing, timeout, unsupported, synthetic and runtime-error counts are zero.
10. Final filters and ranking match the frozen campaign manifest.
11. Runtime reduction is measured using equal workloads and reported without
    mixing queue time with engine time.
12. The final artifact is restored and independently verified from GitHub.
13. Incremental net spend remains zero.
14. No V6-equivalence, point-in-time or survivorship-free claim is made.

Completion of these historical stages does not authorize locked. Locked remains
closed until the owner gives a separate explicit instruction after reviewing
the unblinded historical report.
