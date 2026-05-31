# Research Protocol

> Canonical workflow note: the mandatory, unified workflow now lives in
> `RESEARCH_OPERATING_PROTOCOL.md`. This file remains the detailed tier
> and lockbox reference. If the two ever conflict, the operating protocol
> wins unless a newer version explicitly replaces it.

This document defines the formal data-split policy for Aurora research.
The split is the foundation of the OOS sagrado doctrine. Every backtest,
every GA run, every paper / live deployment must respect it.

## Tiers

| Tier | Range | Purpose | Access policy |
|------|-------|---------|---------------|
| `IS_TRAIN` | 1995-01-01 to 2010-12-31 | Model fitting | Free read |
| `IS_VALID` | 2011-01-01 to 2012-12-31 | In-sample walk-forward holdout | Free read |
| `WF` | rolling within `IS_TRAIN` + `IS_VALID` | Walk-forward folds for GA fitness stability | Free read inside IS only |
| `OOS_DEV` | 2013-01-01 to 2020-12-31 | Post-GA validation, may be re-touched after a research-cycle reset | Read after pareto front selected |
| `OOS_LOCKED` | 2021-01-01 to 2024-12-31 | Frozen, single-look only | Lockbox ceremony required |
| `FORWARD` | 2025-01-01 onward | Paper / live trading | Read at runtime, never used for fitting |

The boundary `IS_END = 2012-12-31`, `OOS_START = 2013-01-01` in
`aurora/core/data_layer.py` is the authoritative source. The remaining
tiers are conventions enforced by reviewer + lockbox ceremony.

## Rules

### R1 - GA fitness reads only IS_TRAIN + WF folds
The genetic algorithm in `aurora/ga/runner.py` calls
`aurora.ga.fitness.multi_objective_fitness_is`. That function builds
its objectives from in-sample prices and walk-forward stability across
sub-windows of IS data. It must not read `OOS_DEV`, `OOS_LOCKED`, or
`FORWARD`.

### R2 - IS_VALID is consulted only for the final IS-side walk-forward
After the GA selects a pareto front, `validation/walk_forward.py` runs the
walk-forward gate. The last fold may extend into `IS_VALID` but must not
enter `OOS_DEV`.

### R3 - OOS_DEV is consulted only after pareto-front selection
The pipeline in `aurora/validation/pipeline.py` is the only call site
permitted to evaluate candidates on `OOS_DEV`. Re-running the GA with
different parameter ranges and consulting `OOS_DEV` again is allowed only
after a documented research-cycle reset (see ceremony below).

### R4 - OOS_LOCKED is single-look
`OOS_LOCKED` is consulted exactly once per strategy version. Re-touching it
requires the explicit lockbox ceremony in section "Lockbox ceremony"
below. The journal entry is mandatory.

### R5 - FORWARD is paper / live only
Data after `2025-01-01` is consumed live (yfinance polling adapter,
broker fills, drift monitor). It is never used to fit model parameters,
calibrate cost models, or tune drift thresholds.

### R6 - Costs are at least IBKR_costs
Any backtest that informs a research decision must use at least the
default `IBKR_costs` floor in `core/costs.py`: 5 bps spread + 0.5 bps
commission + 5 bps slippage per trade. Optimistic cost assumptions are a
form of OOS leakage.

### R7 - Every OOS read is recorded
The `OOSGuard` context manager writes every OOS read to
`data_cache_qf/.oos_lock.json` with a timestamp and the current git hash.
Reviewers verify the lock file before a strategy advances to paper.

## Snapshot freezing

The `OOS_LOCKED` tier and any other dataset that must remain bit-identical
across runs are persisted via `aurora.core.snapshots.SnapshotStore`. A
locked snapshot is the on-disk equivalent of the lockbox: any
non-ceremonial code path that tries to load it raises `IntegrityError`.

### Freezing a locked snapshot

```python
from aurora.core.snapshots import SnapshotStore

store = SnapshotStore("data_cache_qf/snapshots.sqlite")
snap = store.freeze(
    prices=oos_locked_series,
    symbol="SPY",
    provenance="OOS_LOCKED 2021-01-01..2024-12-31 (yfinance pull on YYYY-MM-DD)",
    locked=True,
)
# snap.sha256 is the canonical hash; store it in the registry alongside the
# strategy version so the lock-and-load contract is enforceable.
```

### Loading a locked snapshot — only inside the explicit unlock phase

A locked snapshot can only be loaded inside an `OOSGuard` whose `phase`
attribute matches an entry in
`aurora.core.snapshots._ALLOWED_UNLOCK_PHASES`, currently
`{"explicit_unlock"}`. Any other phase (or no guard at all) raises
`IntegrityError`. The startswith-trick was tightened in v1.3.1 so that
`"explicit_unlock_oops"` no longer slips through.

```python
from aurora.core.data_layer import OOSGuard

with OOSGuard("explicit_unlock"):
    series = store.load(snap.sha256)  # IntegrityError without the guard
```

The hash is verified on every load (`SHA-256` of the frozen parquet bytes).
A mismatch — including a deliberate rewrite of the file — raises
`IntegrityError`.

### Lock invariants

- Once `freeze(..., locked=True)` is committed, the row cannot be silently
  demoted back to unlocked. Re-freezing the same hash with
  `locked=False` raises `IntegrityError`.
- The on-disk parquet file path is content-addressed by the SHA-256, so a
  snapshot can be moved or backed up without losing the verifiability.
- Any read recorded by `OOSGuard` is appended to
  `data_cache_qf/.oos_lock.json` with timestamp + git hash, in addition to
  the snapshot's own provenance metadata.

## Lockbox ceremony for OOS_LOCKED

Re-touching `OOS_LOCKED` after the single permitted look requires:

1. Write a research note in `RESEARCH_LOG` explaining the reason.
2. Record the current git hash: `git rev-parse HEAD`.
3. Acquire a file lock by creating
   `data_cache_qf/.oos_locked_unlock_request.json` with the git hash, the
   reason, and the timestamp.
4. A second reviewer signs off by appending their identifier to the same
   file.
5. Run the read.
6. Append the resulting metric values to the same file.
7. Commit the file to git in the same commit as any code or parameter
   change motivated by the read.

The intent is to make every additional look at `OOS_LOCKED` slow,
auditable, and embarrassing. The cost of re-looking should always be
higher than the cost of accepting the current verdict.

## Research-cycle reset

When the working hypothesis changes substantively (e.g. the strategy
family is replaced or the universe is redefined), a research-cycle reset
is permitted. Steps:

1. Document the reset in `RESEARCH_LOG` with the reason.
2. Roll the OOSGuard lock file to an archive (`.oos_lock.YYYYMMDD.json`).
3. Reset access counters.
4. Treat all subsequent runs as a new cycle.

A reset does not unlock `OOS_LOCKED`. That tier remains single-look across
cycles.

## Diagram

```
1995 ----------------- 2010 -- 2012 -- 2013 ------------- 2020 -- 2021 ------- 2024 -- 2025 --->
|                            |       |                          |                  |
|     IS_TRAIN               | IS_V  |       OOS_DEV            |   OOS_LOCKED     | FORWARD
|     (free)                 | ALID  |  (post-pareto only)      |  (single look)   |  (live)
|                            |(free) |                          |                  |
+----------------------------+-------+--------------------------+------------------+--------->
                                     ^                          ^
                                     |                          |
                                IS / OOS boundary          Lockbox boundary
                              (data_layer.py: IS_END)
```

## Operational checklist

Before any backtest reaches paper trading, the reviewer verifies:

- [ ] `data_cache_qf/.oos_lock.json` shows zero violations during the GA run.
- [ ] The pipeline run report in `validation/pipeline.py` shows the OOS
      read happening exactly once, after pareto-front selection.
- [ ] `forge preflight` passes all 10 checks.
- [ ] Costs used in the run are at least `IBKR_costs`.
- [ ] If `OOS_LOCKED` was consulted, the lockbox ceremony file exists in
      git history.
- [ ] The strategy is registered in `registry/registry.py` with a config
      hash and the corresponding git commit.

Only then does the strategy enter paper trading for the mandatory 90 days
before any live capital.
