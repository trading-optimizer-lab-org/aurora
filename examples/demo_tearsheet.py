"""Demo: generate a full tearsheet for MACross(20, 100) on SPY.

Run:
    uv run --with vectorbt --with matplotlib --with scipy --with pyarrow \\
        --with yfinance python quantforge/examples/demo_tearsheet.py
"""
from __future__ import annotations
import os
import sys
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))

from quantforge.core.seed import set_global_seed
from quantforge.core.data_layer import load_asset
from quantforge.core.costs import IBKR_costs
from quantforge.core.engine import run_backtest
import numpy as np

from quantforge.strategies.library import MACross
from quantforge.reporting.tearsheet import (
    generate_tearsheet,
    generate_full_tearsheet,
)


def _buyhold_signal(prices, **_kw):
    """Simple buy-and-hold signal: weight 1.0 every bar."""
    return np.ones(len(prices))


def main() -> str:
    set_global_seed(42)
    print("Loading SPY...")
    prices = load_asset("SPY", include_oos=True)
    print(f"  {len(prices)} bars from {prices.index[0].date()} "
          f"to {prices.index[-1].date()}")

    strat = MACross(fast=20, slow=100, allow_short=True)
    print("Running backtest: MACross(20, 100)")
    result = run_backtest(prices, strat.signals, costs=IBKR_costs)
    m = result.metrics
    print(f"  CAGR={m.cagr}%  MDD={m.mdd}%  Calmar={m.calmar}  Sharpe={m.sharpe}")

    # benchmark: buy-and-hold SPY
    try:
        bench = run_backtest(prices, _buyhold_signal, costs=IBKR_costs)
        print(f"  Bench CAGR={bench.metrics.cagr}%  Sharpe={bench.metrics.sharpe}")
    except Exception as exc:
        print(f"  (benchmark skipped: {exc})")
        bench = None

    # basic tearsheet (kept for backward compat demonstration)
    basic_path = os.path.join(tempfile.gettempdir(), "tearsheet.html")
    print(f"Generating basic tearsheet -> {basic_path}")
    generate_tearsheet(
        result,
        output_path=basic_path,
        title="SPY MACross(20,100) — IBKR costs (basic)",
        benchmark_result=bench,
    )

    # full tearsheet (v2 sections enabled)
    full_path = os.path.join(tempfile.gettempdir(), "tearsheet_full.html")
    print(f"Generating full tearsheet  -> {full_path}")
    path = generate_full_tearsheet(
        result,
        output_path=full_path,
        title="SPY MACross(20,100) — IBKR costs (full)",
        benchmark_result=bench,
        include_round_trips=True,
        include_distributions=True,
    )
    print(f"Full tearsheet written: {path}")
    print(f"Size: {os.path.getsize(path):,} bytes")
    return path


if __name__ == "__main__":
    main()
