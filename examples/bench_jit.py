"""Benchmark: run_backtest vs run_backtest_jit on 10K bars synthetic prices.

Reports speedup ratio. Target >5x.

Run:
    uv run --with numba --with vectorbt --with scipy --with pyarrow \
        python quantforge/examples/bench_jit.py
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import IBKR_costs
from quantforge.core.engine import run_backtest
from quantforge.core.engine_jit import (
    NUMBA_AVAILABLE, run_backtest_jit, apply_costs_fast,
)
from quantforge.core.costs import apply_costs
from quantforge.core.engine_jit import rsi_fast
from quantforge.strategies.library import MACross
from quantforge.strategies.library.rsi_meanrev import _rsi as _rsi_py


def make_prices(T: int = 10_000) -> pd.Series:
    set_global_seed(1)
    idx = pd.date_range("2000-01-03", periods=T, freq="B")
    rets = np.random.default_rng(1).normal(0.0005, 0.012, T)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="BENCH")


def time_loop(fn, n_iter: int) -> float:
    t0 = time.perf_counter()
    for _ in range(n_iter):
        fn()
    return time.perf_counter() - t0


def main():
    print(f"numba available: {NUMBA_AVAILABLE}")
    prices = make_prices(10_000)
    s = MACross(fast=20, slow=100)

    # warm up JIT (compile cost excluded from measurement)
    _ = run_backtest_jit(prices.iloc[:200], s.signals, costs=IBKR_costs)

    # full backtest comparison
    n_iter = 20
    t_np = time_loop(lambda: run_backtest(prices, s.signals, costs=IBKR_costs), n_iter)
    t_jit = time_loop(lambda: run_backtest_jit(prices, s.signals, costs=IBKR_costs), n_iter)

    print(f"\nFull backtest ({n_iter} iters, T={len(prices)}):")
    print(f"  run_backtest      : {t_np:.4f}s  ({t_np / n_iter * 1000:.2f} ms/iter)")
    print(f"  run_backtest_jit  : {t_jit:.4f}s  ({t_jit / n_iter * 1000:.2f} ms/iter)")
    print(f"  speedup (full)    : {t_np / max(t_jit, 1e-9):.2f}x")

    # isolate cost-loop kernel (most numba-friendly piece)
    weights = s.signals(prices)
    returns = np.zeros(len(prices))
    pv = prices.values.astype(float)
    returns[1:] = pv[1:] / pv[:-1] - 1.0

    n_iter_k = 200
    t_np_k = time_loop(lambda: apply_costs(weights, returns, IBKR_costs), n_iter_k)
    t_jit_k = time_loop(lambda: apply_costs_fast(weights, returns, IBKR_costs), n_iter_k)

    print(f"\napply_costs kernel ({n_iter_k} iters, T={len(prices)}):")
    print(f"  numpy             : {t_np_k:.4f}s  ({t_np_k / n_iter_k * 1000:.3f} ms/iter)")
    print(f"  jit               : {t_jit_k:.4f}s  ({t_jit_k / n_iter_k * 1000:.3f} ms/iter)")
    speedup_k = t_np_k / max(t_jit_k, 1e-9)
    print(f"  speedup (kernel)  : {speedup_k:.2f}x")

    # RSI kernel: pure-python Wilder loop (rsi_meanrev._rsi) vs JIT
    pv = prices.values.astype(float)
    _ = rsi_fast(pv[:50], 14)  # warm up
    n_iter_r = 50
    t_py = time_loop(lambda: _rsi_py(pv, 14), n_iter_r)
    t_jr = time_loop(lambda: rsi_fast(pv, 14), n_iter_r)
    speedup_r = t_py / max(t_jr, 1e-9)
    print(f"\ncompute_rsi kernel ({n_iter_r} iters, T={len(prices)}, n=14):")
    print(f"  pure-python       : {t_py:.4f}s  ({t_py / n_iter_r * 1000:.3f} ms/iter)")
    print(f"  jit               : {t_jr:.4f}s  ({t_jr / n_iter_r * 1000:.3f} ms/iter)")
    print(f"  speedup (rsi)     : {speedup_r:.2f}x")

    target = 5.0
    best = max(speedup_k, speedup_r)
    print(f"\nTarget >{target:.1f}x best-kernel speedup: "
          f"{'PASS' if best > target else 'FAIL'} (best={best:.2f}x)")


if __name__ == "__main__":
    main()
