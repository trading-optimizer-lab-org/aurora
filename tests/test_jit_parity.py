"""End-to-end parity test: engine.run_backtest vs engine_jit.run_backtest_jit.

Both code paths must produce identical equity curves, return arrays, and
metric scalars on the same inputs. Tolerance 1e-6 (looser than the 1e-9 used
by per-kernel tests in test_jit.py because we accumulate floating-point
operations across the full pipeline).

Diverging results indicate a regression in either path.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantforge.core.costs import IBKR_costs, ZERO_costs
from quantforge.core.engine import run_backtest
from quantforge.core.engine_jit import run_backtest_jit
from quantforge.core.seed import set_global_seed
from quantforge.strategies.library import MACross, RSIMeanRev


TOL = 1e-6


def _prices(n: int = 800, seed: int = 11) -> pd.Series:
    set_global_seed(seed)
    idx = pd.date_range("2015-01-05", periods=n, freq="B")
    rets = np.random.default_rng(seed).normal(0.0004, 0.011, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="JIT_PARITY")


@pytest.mark.parametrize(
    "strategy_cls,costs",
    [
        (MACross, ZERO_costs),
        (MACross, IBKR_costs),
        (RSIMeanRev, ZERO_costs),
        (RSIMeanRev, IBKR_costs),
    ],
)
def test_engine_jit_parity(strategy_cls, costs):
    """Same prices and strategy must give identical NAV, rets, and metrics."""
    prices = _prices()
    strat = strategy_cls()

    ref = run_backtest(prices, strat.signals, costs=costs)
    jit = run_backtest_jit(prices, strat.signals, costs=costs)

    # Shapes
    assert ref.nav.shape == jit.nav.shape
    assert ref.rets.shape == jit.rets.shape
    assert ref.weights.shape == jit.weights.shape

    # Equity curve
    nav_err = float(np.max(np.abs(ref.nav - jit.nav)))
    assert nav_err < TOL, f"NAV diverged max_err={nav_err}"

    # Per-bar returns
    rets_err = float(np.max(np.abs(ref.rets - jit.rets)))
    assert rets_err < TOL, f"rets diverged max_err={rets_err}"

    # Weights are produced by signal_fn -- identical input -> identical output
    w_err = float(np.max(np.abs(ref.weights - jit.weights)))
    assert w_err < TOL, f"weights diverged max_err={w_err}"

    # Metric scalars
    for attr in ("calmar", "sharpe", "cagr", "mdd"):
        ref_val = getattr(ref, attr)
        jit_val = getattr(jit, attr)
        # Allow NaN matching too
        if np.isnan(ref_val) and np.isnan(jit_val):
            continue
        assert abs(ref_val - jit_val) < TOL, (
            f"{attr} diverged: ref={ref_val} jit={jit_val}"
        )


def test_engine_jit_parity_clip_edge_case():
    """Weights marginally above 1.0 + 1e-10 must be clipped exactly the same way
    in both engines. Previously engine.py clipped after validation but
    engine_jit.py did not, producing divergent results when inputs were
    1.0 + 1e-10 (within tolerance, accepted by both, but only one clipped)."""
    prices = _prices()

    def near_bound_signal(prices, **_):
        n = len(prices)
        w = np.full(n, 0.5)
        w[0] = 1.0 + 1e-10  # within tolerance, must be clipped to exactly 1.0
        w[5] = -1.0 - 1e-10  # within tolerance, must be clipped to exactly -1.0
        return w

    ref = run_backtest(prices, near_bound_signal, costs=ZERO_costs)
    jit = run_backtest_jit(prices, near_bound_signal, costs=ZERO_costs)

    # Both must clip to exact bounds (no 1e-10 leakage in either path).
    assert ref.weights[0] == 1.0
    assert jit.weights[0] == 1.0
    assert ref.weights[5] == -1.0
    assert jit.weights[5] == -1.0

    # Numerical parity at machine precision after clip.
    assert np.max(np.abs(ref.rets - jit.rets)) < TOL
    assert np.max(np.abs(ref.nav - jit.nav)) < TOL
