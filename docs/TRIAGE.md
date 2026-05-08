# P2.A Triage Backend

The triage backend (`quantforge.triage`) is a fast, vectorized screening
layer for thousands of strategy variants. It is **not** a substitute
for the official engine.

## What triage is for

When a research session generates 10k+ candidate parameter combinations
(GA sweeps, random search, bulk LLM proposals), running each through
the full QuantForge engine -- with snapshots, OOSGuard, slippage, and
the eight-gate pipeline -- is too expensive. Triage gives every
variant a coarse score under a simplified cost model and flags the ones
worth re-running on the official engine.

Triage answers exactly one question:

> **Is this variant interesting enough to spend a real backtest on?**

Promising variants are flagged. Anything that survives is then re-run
on `quantforge.core.engine.run_backtest` (or whatever the official
runner the caller passes). Triage **never** produces a verdict that can
be promoted on its own.

## Hard guarantees

1. **Tier guard.** `TriageEngine` refuses to operate on data crossing
   the OOS_LOCKED or FORWARD boundaries. The configured
   `triage_tier_only` must be one of `IS_TRAIN`, `IS_VALID`, or
   `OOS_DEV`. The boundaries are read directly from the active
   `ProtocolPolicy`, so changing the policy automatically tightens
   triage.
2. **No promotion.** `TriageResult.promising` means *eligible to re-run
   on the official engine*. It is never a promotion to OOS_LOCKED, the
   review queue, or paper trading. The promotion bridge
   (`TriageEngine.promote_to_official`) requires a single-use UUID
   token and consumes it on success so a triage hit cannot be
   re-promoted.
3. **Deterministic identity.** Each `StrategyVariant.variant_id` is a
   SHA-256 of the canonical (strategy_class, params, universe,
   rebalance) tuple. Two variants whose canonical fields agree have
   the same id; the dedup logic and promotion bridge round-trip
   through this id.

## Components

- **`StrategyVariant`** -- frozen dataclass with `variant_id`,
  `strategy_class`, `params`, `universe`, `rebalance`.
- **`variant_grid` / `variant_random_sample`** -- factories for
  cartesian-product sweeps and seeded random samples.
- **`TriageConfig`** -- knobs: `parallel`, `max_workers`,
  `cost_bps_simple`, `slippage_bps_simple`, `min_sharpe_threshold`,
  `max_dd_threshold`, `min_trades`, `use_vectorbt`,
  `triage_tier_only`.
- **`TriageEngine`** -- the pipeline. `triage_batch(prices, variants)`
  returns a `TriageBatch`; `promote_to_official(result, runner)` hands
  off promising results to the official engine.
- **`TriageResult` / `TriageBatch`** -- frozen records. The batch is
  parquet-serializable.

## Backends

The default backend is the internal numpy implementation in
`quantforge.triage.vectorized`. It computes signals per variant per
asset in a Python loop (strategy ctors cannot be vectorized safely)
but runs the pnl + metric layer entirely in numpy with broadcasting.

When `TriageConfig.use_vectorbt=True` and `vectorbt` is importable,
the pipeline routes through `quantforge.triage.vectorbt_backend`
instead. If vectorbt is not installed, the engine emits a single
`UserWarning` and falls back to the internal backend; vectorbt is
intentionally not a hard dependency of QuantForge.

## CLI

```
forge triage run \
    --variants variants.yaml \
    --output batch.parquet \
    [--config-path config/triage.yaml] \
    [--prices prices.parquet] \
    [--use-vectorbt] \
    [--tier IS_TRAIN]

forge triage list-promising --batch batch.parquet --top 20

forge triage promote --batch batch.parquet --variant-id <id>

# Within the research factory namespace:
forge research triage specs.yaml [--threshold sharpe=0.5,max_dd=-0.30]
```

## Promotion bridge

A typical workflow looks like:

1. `variant_grid` or `variant_random_sample` enumerates candidates.
2. `TriageEngine.triage_batch(prices, variants)` scores them all.
3. `TriageBatch.promotable_ids()` lists the ones that passed
   thresholds.
4. For each promotable id, the caller hands the corresponding
   `TriageResult` to `TriageEngine.promote_to_official(result, runner)`,
   where `runner` is the official `run_backtest` (with full
   QuantForge ceremony: real costs, slippage model, snapshots,
   OOSGuard).
5. The official run is the only verdict; triage is a filter, not an
   answer.

## Cost model

Triage uses a **flat-bps cost model** on top of equal-weight asset
returns:

```
gross[t] = w[t-1] * r[t]                              (anti-lookahead shift)
turnover[t] = abs(w[t] - w[t-1])
cost[t] = (cost_bps_simple + slippage_bps_simple) * 1e-4 * turnover[t]
net[t] = gross[t] - cost[t]
```

This is **not** the official cost model. Triage's cost charges are
deliberately simple so the screen runs at thousands of variants per
second. The `correlation` between triage Sharpe and engine Sharpe is
high (because both are dominated by the same underlying signal), but
the absolute numbers will not match -- that is what re-running on the
official engine is for.
