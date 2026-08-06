# Aurora implementation handoff — V2

## Repository baseline

Repository:

```text
trading-optimizer-lab-org/aurora
```

V1 lives in draft PR `#114`, branch:

```text
codex/sp500-long-short-daily-research
```

The V2 branch must be created from:

1. the verified current PR #114 head if V1 is still unmerged; or
2. current `main` if PR #114 has been merged and its V1 campaign files are present.

Never recreate V1 from memory and never modify its frozen candidate pack or results.

Recommended V2 branch:

```text
codex/sp500-long-short-daily-research-v2
```

## New isolated paths

```text
campaigns/sp500_long_short_daily_v2/
campaigns/sp500_long_short_daily_v2/input_package/
campaigns/sp500_long_short_daily_v2/research_input/
campaigns/sp500_long_short_daily_v2/prior_campaign/
infra/sp500_long_short_daily_v2/
config/sp500_long_short_daily_v2_train_v3.yaml
.github/workflows/sp500-long-short-daily-v2-campaign.yml
tests/test_sp500_long_short_daily_v2_campaign.py
```

Recommended workload:

```text
aurora.infra.sp500_long_short_daily_v2.workload:TRAIN_WORKLOAD
```

Reuse the universal framework:

```text
.github/workflows/_aurora-future-run-v3.yml
```

## V1 components to reuse, not fork semantically

- package and locked-boundary contracts;
- bounded Yahoo/Stooq acquisition machinery;
- exact audited SPY total-return ledger;
- NYSE session mapping;
- metric and annual/rolling report contracts;
- deterministic scheduler/pilot machinery;
- hierarchical merge, retry and checkpoint framework;
- artifact verifier;
- multiple-testing implementation after extending it to combined V1+V2 inputs.

## New V2 components

- split-normalized OHLCV feature layer;
- fixed-ETF panel adapter with inception and completeness gates;
- 24 family dispatchers;
- variance-ratio estimator with frozen finite-sample convention;
- causal rolling autocorrelation and HAC slope t-stat;
- robust median/MAD tail event;
- two-sided Page CUSUM state;
- monthly expanding shallow-tree fit with lawful label delay;
- cumulative V1+V2 multiplicity loader and verifier;
- V2 freeze and one-shot validation guard.

## Required equivalence testing

Every optimized implementation must match a simple row-by-row causal reference implementation on:

- positions;
- first eligible date;
- missing/persistence behavior;
- daily returns;
- metrics;
- hashes.

For the tree family, compare predictions, fitted tree text/export and probabilities across clean reruns.

## Pull request

Open a new draft PR. Do not append V2 changes to PR #114 unless repository policy makes a separate PR technically impossible; if so, explain the exact blocker and preserve V1/V2 commits and paths separately.
