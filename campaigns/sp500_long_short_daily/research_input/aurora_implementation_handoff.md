# Aurora implementation handoff

## Direct implementation target

Create a thin campaign adapter at `campaigns/sp500_long_short_daily/` that consumes the files in this ZIP and delegates generic computation to the repository's existing Aurora runner. Do not fork or rewrite the core engine unless an interface is genuinely missing and covered by tests.

## Required repository tree

```text
campaigns/sp500_long_short_daily/
  campaign_spec.yaml
  candidates/candidate_strategy_pack.jsonl
  candidates/candidate_pack_manifest.json
  features/feature_catalog.csv
  sources/data_source_inventory.csv
  sources/research_library.csv
  config/acceptance_gates.md
  src/acquire.py
  src/normalize.py
  src/features.py
  src/strategies.py
  src/returns.py
  src/walk_forward.py
  src/select.py
  src/validate_once.py
  src/audit.py
  tests/
.github/workflows/sp500-long-short-daily-campaign.yml
```

Paths may be adapted to repository conventions after inspection, but the logical separation and artifact names must remain.

## Adapter interface

The adapter should expose deterministic commands equivalent to:

```bash
python -m campaigns.sp500_long_short_daily.cli preflight --spec campaigns/sp500_long_short_daily/campaign_spec.yaml
python -m campaigns.sp500_long_short_daily.cli acquire --spec ... --max-date 2020-12-31
python -m campaigns.sp500_long_short_daily.cli run-shard --phase smoke --family price_trend_sma
python -m campaigns.sp500_long_short_daily.cli run-shard --phase full-train --family <family_id>
python -m campaigns.sp500_long_short_daily.cli merge-train --input artifacts/full-train
python -m campaigns.sp500_long_short_daily.cli freeze-selection
python -m campaigns.sp500_long_short_daily.cli validate-once --ack OPEN_VALIDATION_2011_2020_ONCE
python -m campaigns.sp500_long_short_daily.cli verify-artifacts
```

Use the repository's existing CLI instead when equivalent; record the mapping in `implementation_mapping.md`.

## Signal execution pseudocode

```python
for decision_date in trading_sessions:
    assert decision_date <= date(2020, 12, 31)
    x = feature_store.asof(decision_date, cutoff='after_close')
    target_position = strategy.decide(x, previous_position)
    assert target_position in (-1, +1)
    execution_date = next_spy_session(decision_date)
    entry_open = spy_open[execution_date]
    exit_date = next_spy_session(execution_date)
    exit_open = spy_open[exit_date]
    long_total_return = total_return_open_to_open(entry_open, exit_open, distributions)
    strategy_return = target_position * long_total_return
```

A feature store must preserve both observation time and availability/release time. A dataframe index alone is insufficient proof of causality.

## Candidate implementation

- Dispatch on `family`; parse parameters from the JSON object.
- Recompute canonical hash before execution.
- Use a common signal state machine for tie and initial-position rules.
- Static rules may vectorize only after a row-wise causal reference implementation produces identical results.
- Fitted rules receive only outer-train history and persist fold-specific parameters.
- Markov models: two states, deterministic restarts, filtered probabilities only; tests must fail if smoothed probabilities are requested.
- Logistic models: deterministic seed, predeclared feature set/grid, nested chronological tuning and train-only normalization.
- Ensemble components are resolved by family and variant label; no validation weighting.

## Return and benchmark implementation

Implement one audited open-to-open total-return ledger and reuse it for candidates and benchmarks. Implement all five mandatory benchmarks: buy-and-hold total return, always-long `+1`, always-short `-1`, symmetric SMA-200, and symmetric causal 252-session momentum. All use the same close decision/next-open execution and audited ledger as candidates. Buy-and-hold and always-long must reconcile exactly. Do not use adjusted close as an adjusted open without reconstructing factors.

## Pilot-driven scheduling and sharding

Do **not** preselect 28 or 360 jobs. The pilot must benchmark at least three equivalent layouts (for example candidate-block, family-block and cost-balanced multi-family blocks), and at least two process counts compatible with the runner. Estimate wall time, startup/merge overhead, peak memory, FeatureStore hit rate and retry granularity. Persist the chosen layout in `scheduler_plan.json`; the choice must be deterministic from measured pilot results, must preserve identical candidate hashes/results, must respect the repository limit, and must never exceed 360 concurrent standard jobs or 4 usable vCPU per runner. Full train then uses the selected cost-balanced matrix. Every shard outputs:

```text
candidate_metadata.jsonl
train_daily_returns.parquet
train_fold_metrics.csv
candidate_metrics.csv
eligibility_and_rejections.csv
causality_audit.json
runtime_manifest.json
```

The merge job verifies that exactly 168 unique candidate IDs and all five benchmark IDs are present or explicitly rejected, and that no candidate is lost silently.

## Tests required before smoke

- schema and UTF-8 parsing for every package file;
- JSONL count/hash/deduplication;
- deterministic initial/tie state;
- exact `+1/-1` and zero-cost assertions;
- hand-calculated open-to-open return and dividend cases for long and short;
- split-adjustment case;
- NYSE holiday/next-open case;
- release-date as-of joins for ALFRED and CFTC;
- intentionally leaked close/open and revised-vintage fixtures must be rejected;
- Markov filtered-versus-smoothed leakage test;
- nested walk-forward isolation test;
- locked-date firewall test;
- rerun determinism test.

## Required artifacts

- `sp500-ls-preflight-<run_id>`
- `sp500-ls-smoke-<run_id>`
- `sp500-ls-pilot-<run_id>`
- `sp500-ls-scheduler-plan-<run_id>`
- `sp500-ls-full-train-<run_id>-<shard_id>`
- `sp500-ls-train-merged-<run_id>`
- `sp500-ls-train-freeze-<run_id>`
- `sp500-ls-validation-once-<run_id>`
- `sp500-ls-final-verified-<run_id>`

The final artifact includes `RESULT_STATUS.md`, all candidate/benchmark metrics, train and validation daily returns, source/data hashes, environment lock, code commit, rejection log, multiplicity tests, validation-freeze proof and a machine-readable `final_manifest.json`.

## Do not implement

- a 2021+ phase;
- validation-driven candidate generation, thresholds or data repair;
- cash states, leverage scaling, volatility scaling or position magnitudes other than one;
- non-zero cost assumptions in headline calculations;
- paid or unverifiable data as silent fallbacks;
- smoothed regimes, current-constituent historical breadth or latest-vintage macro joins;
- manual deletion of poor candidates from logs.
