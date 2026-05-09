# Writing a Custom Strategy

This is a short tutorial for adding a new strategy to Aurora. Read
`docs/ARCHITECTURE.md` first for the design principles, especially the
anti-lookahead rules.

## Strategy interface

A strategy is a subclass of `aurora.strategies.base.Strategy`. The
contract is:

- `signals(prices) -> np.ndarray` returns target positions, same length as
  `prices`.
- Allowed values: floats in `[-1, +1]`. Use `0` for flat, `+1` for fully
  long, `-1` for fully short, fractional values for partial exposure.
- Causality (anti-lookahead): `weights[i]` may use `prices[:i+1]` only.
  Never `prices[i+1:]`.
- The convention: `weights[i]` is the position at close of bar `i`, applied
  to the return of bar `i+1`.
- `NaN` is forbidden in the output.

## Step 1 - Create the file

Create `aurora/strategies/library/my_strategy.py`:

```python
"""MyStrategy - simple example.

Goes long when the close is above its rolling N-period mean, short below.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from aurora.strategies.base import Strategy, StrategySpec


class MyStrategy(Strategy):
    """Mean-reversion-vs-trend toy example."""

    def __init__(self, lookback: int = 20):
        self.lookback = int(lookback)

    def signals(self, prices: pd.Series) -> np.ndarray:
        # Anti-lookahead: rolling mean uses past + current bar only.
        # The .shift(1) below makes signal[t] depend strictly on data
        # through t-1, which is the safest construction.
        ma = prices.rolling(self.lookback, min_periods=self.lookback).mean()
        sig = np.where(prices > ma, 1.0, -1.0)
        sig = pd.Series(sig, index=prices.index).shift(1).fillna(0.0).to_numpy()
        return sig

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="MyStrategy",
            params={"lookback": 20},
            param_ranges={"lookback": (5, 200)},
        )

    def with_params(self, **kwargs) -> "MyStrategy":
        return MyStrategy(**{**{"lookback": self.lookback}, **kwargs})
```

Notes:

- `spec()` is what the genetic algorithm uses. Each parameter listed in
  `params` must have an entry in `param_ranges` for the GA to mutate it.
  Tuples `(low, high)` are continuous; lists are discrete categories.
- `with_params(**kwargs)` returns a new instance. Do not mutate `self` from
  the GA loop.
- The `.shift(1)` in `signals` is the simplest safe pattern for
  anti-lookahead. The runtime check
  (`validation/lookahead_check.runtime_lookahead_check`) shuffles bars after
  index `k` and asserts `signals[:k]` is unchanged.

## Step 2 - Register in the library

Edit `aurora/strategies/library/__init__.py`:

```python
from aurora.strategies.library.my_strategy import MyStrategy

__all__ = [
    "MACross",
    "RSIMeanRev",
    # ...existing names...
    "MyStrategy",
]
```

After this, `forge list-strategies` will show `MyStrategy` and the CLI
resolver will pick it up.

## Step 3 - Run a single backtest

```bash
forge run --strategy MyStrategy --asset SPY
```

Or programmatically:

```python
from aurora.core.seed import set_global_seed
from aurora.core.engine import run_backtest
from aurora.core.data_layer import load_asset
from aurora.core.costs import IBKR_costs
from aurora.strategies.library import MyStrategy

set_global_seed(42)
prices = load_asset("SPY")              # IS-only by default
strat = MyStrategy(lookback=30)
weights = strat.signals(prices)
result = run_backtest(prices, weights, costs=IBKR_costs)
print(result.calmar, result.sharpe, result.mdd)
```

`load_asset` defaults `include_oos=False`. Do not flip this during
optimization. The `OOSGuard` in `core/data_layer.py` will record the
violation to `data_cache_qf/.oos_lock.json`.

## Step 4 - Run the validation pipeline

```bash
forge validate --strategy MyStrategy --asset SPY --n-trials 5
```

This runs the full gate sequence: walk-forward, MC bootstrap, MC
trade-reorder, SPP, deflated Sharpe, lookahead AST + runtime, and the
optional gates if requested. See `docs/ARCHITECTURE.md` for the full gate
list and `docs/GLOSSARY.md` for definitions.

## Step 5 - GA search

```bash
forge search --strategy MyStrategy --asset SPY --population 100
```

The GA reads `MyStrategy.spec()` to define the search space. Fitness is
computed on IS only by `aurora.ga.fitness.multi_objective_fitness_is`.
OOS is touched only after the pareto front is selected.

## Anti-lookahead checklist

Before running any optimization, walk through the following on your
`signals` method:

1. Every rolling / expanding aggregation has `min_periods` set, no implicit
   forward-fill, no `bfill`.
2. Every series operation that could leak future information ends with
   `.shift(1)`.
3. No use of `prices.iloc[i+1:]` or any equivalent forward slice.
4. No use of full-history statistics (mean, std, quantile) computed once
   over the whole series and applied at every `i`. Use rolling versions.
5. The runtime lookahead check passes:

   ```python
   from aurora.validation.lookahead_check import runtime_lookahead_check
   ok, msg = runtime_lookahead_check(MyStrategy(lookback=30), prices)
   assert ok, msg
   ```

## Tests

Add a test at `aurora/tests/test_my_strategy.py`:

```python
import numpy as np
import pandas as pd
import pytest
from aurora.strategies.library import MyStrategy


def test_signals_shape_and_bounds():
    prices = pd.Series(np.linspace(100, 110, 200))
    weights = MyStrategy(lookback=20).signals(prices)
    assert len(weights) == len(prices)
    assert np.all(np.isfinite(weights))
    assert np.all((weights >= -1) & (weights <= 1))


def test_no_lookahead():
    from aurora.validation.lookahead_check import runtime_lookahead_check
    prices = pd.Series(np.cumsum(np.random.RandomState(0).normal(size=500)) + 100)
    ok, msg = runtime_lookahead_check(MyStrategy(lookback=20), prices)
    assert ok, msg
```

Run:

```bash
pytest aurora/tests/test_my_strategy.py -q
```

## Wrapper strategies

A wrapper strategy decorates another strategy with extra logic (vol
targeting, hard stops, regime filters). Examples in
`aurora/strategies/library/`: `VolTargetWrapper`, `StopWrapper`.

### Convention

Wrappers expose a class-level sentinel and a default-`None` `base` argument:

```python
class StopWrapper(Strategy):
    # Sentinel for GA-discovery code: signals that this strategy cannot be
    # constructed from spec().param_ranges alone and should be skipped.
    is_wrapper: bool = True

    def __init__(self, base: Strategy = None, stop_pct: float = 0.05,
                 take_pct: float = 0.20, lockout: int = 5):
        if base is None:
            raise TypeError(
                "StopWrapper requires a base Strategy. Pass `base=...` "
                "explicitly or use a wrapper_factory in run_ga."
            )
        self.base = base
        # ...
```

The two pieces are:

- `is_wrapper: bool = True` — a class-level sentinel attribute. Code that
  enumerates strategies (the GA, autosearch, registry sweeps) checks
  `getattr(cls, "is_wrapper", False)` and skips wrappers because they cannot
  be instantiated from `spec().param_ranges` alone (the `base` constructor
  argument has no entry in the param ranges).
- `base: Strategy = None` — the default lets `inspect`-based reflection still
  call `WrapperCls()` without crashing, but the constructor raises
  `TypeError` if `base` is missing so silent misuse fails loudly.

### Using a wrapper in `run_ga`

`run_ga` refuses to run with a wrapper directly:

```python
from aurora.ga.runner import run_ga

# This raises TypeError because StopWrapper.is_wrapper is True:
# run_ga(StopWrapper, prices_is, prices_oos, fitness_fn, config)
```

Build a `wrapper_factory` that closes over a concrete base strategy and
exposes the same `Strategy` interface, then pass that synthesized class to
`run_ga`:

```python
from aurora.strategies.library import MACross, StopWrapper

def wrapper_factory(base_cls=MACross):
    class _StopWrappedMA(StopWrapper):
        is_wrapper = False  # this concrete class IS runnable
        @classmethod
        def spec(cls):
            return StopWrapper.spec()  # share the param ranges
        def __init__(self, **kwargs):
            super().__init__(base=base_cls(), **kwargs)
    return _StopWrappedMA

run_ga(wrapper_factory(MACross), prices_is, None, fitness_fn, config)
```

The factory pattern keeps OOS isolation guarantees intact — the GA still
sees only `is_prices`, and `with_params` / `signals` cascade through to the
underlying base.

## Multi-asset strategies

For strategies that need multiple inputs (pair trades, cross-sectional
ranks), accept a `pd.DataFrame` instead of a `pd.Series` and return a 2D
weights matrix. See `aurora/strategies/library/pair_trade.py` for the
canonical example. Use `core/engine_multi.py` to run the backtest.

## Tier-bypass is a protocol violation (E.3 round-4 audit)

Strategies receive prices via `signals(prices)` (or `weights(price_dict)`
for multi-asset). The framework enforces tier ceremony rules through
`load_tier` / `load_up_to_tier` / `OOSGuard` before the prices ever
reach your strategy.

Reading data outside the Aurora API — e.g. opening a parquet file
directly with `pd.read_parquet`, hitting yfinance from inside a
strategy, or shipping a hardcoded CSV path — bypasses every tier
enforcement and is a protocol violation. A strategy that does this can
silently pull OOS_LOCKED or FORWARD bars into a fitness loop, breaking
the OOS-sagrado contract.

Convention:
- Strategies are pure functions of the prices passed in.
- Any data hop that the framework does not see (loaders, snapshots, or
  external SQL queries inside `signals`) is a contract break, even if
  the unit test passes.
- If you need additional features (volume, fundamentals, alt-data),
  pass them as explicit `signals(prices, *, features)` arguments and
  load them through Aurora data connectors so the tier rules
  apply.
