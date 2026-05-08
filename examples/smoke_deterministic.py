"""Deterministic smoke example.

Synthetic 500-bar GBM with a fixed seed, run MACross(20, 100) through the
backtest engine, print metrics. Output is byte-stable and used as a
regression snapshot in ``examples/expected_output/smoke_deterministic.txt``.

Requires an editable install:
    pip install -e .

Run:
    python quantforge/examples/smoke_deterministic.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantforge.core.seed import set_global_seed
from quantforge.core.engine import run_backtest
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross


def make_prices(n: int = 500, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    return pd.Series(p, index=idx, name="SMOKE")


def main() -> None:
    set_global_seed(42)
    prices = make_prices()
    strat = MACross(fast=20, slow=100, allow_short=True)
    result = run_backtest(prices, strat.signals, costs=ZERO_costs)
    m = result.metrics

    print(f"bars={len(prices)}")
    print(f"sharpe={m.sharpe:.4f}")
    print(f"cagr={m.cagr:.4f}")
    print(f"mdd={m.mdd:.4f}")
    print(f"calmar={m.calmar:.4f}")
    print(f"final_nav={m.final_nav:.4f}")


if __name__ == "__main__":
    main()
