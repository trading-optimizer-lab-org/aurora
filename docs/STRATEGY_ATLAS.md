# Strategy atlas

The strategy atlas is the first gatekeeper in QuantForge's research
pipeline. Every strategy idea is registered here with an explicit
status, an asset class, a data-requirements list, an
engine-capability list, and an explicit benchmark expectation. Ideas
that are not in the atlas, or whose status forbids promotion, never
reach the validation pipeline.

## Why the atlas refuses many tempting ideas

QuantForge has hard constraints on what data it owns and what engine
features it supports today. The atlas makes those constraints visible:

- **`BLOCKED`** entries are ideas the platform cannot honestly run.
  Examples: anything that needs an options chain, convertible bond
  terms, structured-credit tranche data, or full tax-lot accounting.
  These are blocked because the *data* is missing or because the
  *engine* lacks the pricing model. We could simulate them, but we
  would not be honest about what we are simulating, so they stay
  blocked until the missing piece arrives.
- **`EXTERNAL_DATA_ONLY`** entries could run on the engine but rely
  entirely on data that lives outside QuantForge. They are kept
  visible so consumers do not waste effort re-implementing them
  in-platform.
- **`BENCHMARK_ONLY`** entries (e.g. the "151 PDF" baselines) exist
  only as comparison references. They will never be promoted to
  production. Keeping them in the atlas makes their numbers
  reproducible without ever putting them on the live track.
- **`REJECTED`** entries are strategies we already tried and decided
  against. Listing them prevents an enthusiastic future contributor
  from rediscovering the same dead end.

## Status lifecycle

| Status                | Promotable? | Typical transition                                  |
|-----------------------|-------------|------------------------------------------------------|
| `CANDIDATE`           | no          | Becomes `SUPPORTED` after validation + R92/R39 gates |
| `SUPPORTED`           | yes         | Stays `SUPPORTED` while live; can be `REJECTED` later |
| `BLOCKED`             | no          | Stays blocked until the missing piece is documented  |
| `REJECTED`            | no          | Terminal                                             |
| `BENCHMARK_ONLY`      | no          | Terminal -- never promoted to production             |
| `EXTERNAL_DATA_ONLY`  | no          | Becomes `CANDIDATE` only if the data is on-platform  |

Only `SUPPORTED` is promotable. The
`StrategyAtlas.is_promotable(name)` helper is the canonical check.

## Changing a status

Status changes are policy decisions, not code refactors. Required
inputs depend on the direction:

- **`CANDIDATE` -> `SUPPORTED`**
  - All declared `validation_gates` must have passed on the official
    OOS partition.
  - `query_before_promote` must return either an empty warning list
    or a documented override.
  - The benchmark comparison must show the strategy meaningfully
    beats its declared `benchmark_expectation`.
- **`SUPPORTED` -> `REJECTED`**
  - Documented degradation (lifecycle SLA breach, regime drift, cost
    blow-up, or operator decision).
- **anything -> `BLOCKED`**
  - Allowed at any time. The reason MUST go in `notes`.
- **`BLOCKED` -> anything else**
  - Only after the blocking constraint has been resolved AND the
    resolution is documented in `notes`.

The atlas does not lock these transitions in code -- they are
enforced by review. The dataclass is frozen so a registered entry
cannot drift silently; replacing an entry requires re-registering it,
which surfaces in code review.

## Adding a new entry

1. Pick a status. Default to `CANDIDATE` for new ideas, `BLOCKED` if
   the platform clearly cannot run it.
2. Fill every field. The constructor enforces:
   - `data_requirements` non-empty (the data registry must be able
     to verify availability).
   - `benchmark_expectation` non-empty (every entry must declare
     what it expects to beat, or the literal string `"none"`).
   - `notes` non-empty when status is `BLOCKED` (so the refusal is
     auditable).
3. Append the entry to `research/_atlas_seed.py::SEED_ENTRIES` in
   the section matching its status.
4. Run the test suite. The deterministic seed-load test will flag
   the new entry; update the test if the new entry is intentional.

## Benchmarks

Each entry declares one of the comparators in
`research/strategy_benchmarks.py::BenchmarkExpectation`:

- `CASH` -- zero-return baseline; useful for pair / market-neutral
  strategies.
- `BUY_AND_HOLD` -- the underlying asset itself.
- `EQUAL_WEIGHT` -- equal-weight portfolio of the asset universe.
- `SIMPLE_MOMENTUM` -- generic 20-period momentum baseline.
- `SIMPLE_MEAN_REVERSION` -- generic 5-period mean-reversion baseline.
- `RANDOM_COMPARABLE_TURNOVER` -- random-sign series with the same
  magnitude as the underlying; the "is this skill or activity" check.
- `CURRENT_PRODUCTION` -- the current production strategy for this
  asset class.

The comparison helper
`evaluate_against_benchmark(strategy_returns, benchmark, asset_returns)`
returns a `BenchmarkResult` with `beats_benchmark`, `sharpe_diff`,
and `alpha_annualised`. By default `beats_benchmark` is True iff
`sharpe_diff > 0`. The threshold can be tightened by callers.

## R92 and R39 gates

Before promoting a `CANDIDATE` to `SUPPORTED`, callers must run
`query_before_promote(name, signal, params, equity, ...)` from
`research/strategy_atlas.py`. The function consults:

- **R92 -- DNA fingerprint** (`research/dna_fingerprint.py`) to flag
  candidates that are too similar to existing supported strategies.
- **R39 -- Graveyard** (`research/graveyard.py`) to flag candidates
  that match a previously archived strategy.

Both modules are best-effort imports: if either is not present in
the deployment, the corresponding check is skipped and a degradation
warning is added to the returned list rather than raising.

A non-empty warning list is *not* an automatic veto -- it is a
hand-off to review. The warnings must be addressed (or explicitly
overridden in writing) before the status can flip.
