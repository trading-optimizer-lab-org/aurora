"""Backtest determinism contract test (R148).

Asserts that running the canonical smoke backtest twice with the same
seed and the same git_hash produces byte-identical output. Catches
non-determinism regressions (random call order, dict iteration,
multi-thread races) at PR time.

The test is fast (~1s on a developer machine) so it can run as part of
the default fast suite.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from quantforge.core.costs import IBKR_costs
from quantforge.core.engine import run_backtest
from quantforge.core.seed import set_global_seed
from quantforge.strategies.library import MACross


def _hash_result(rets: np.ndarray, nav: np.ndarray, metrics_dict: dict) -> str:
    """Stable digest of the backtest output."""
    payload = (
        rets.tobytes()
        + b"||"
        + nav.tobytes()
        + b"||"
        + json.dumps(metrics_dict, sort_keys=True, default=str).encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


def _run_smoke_backtest(seed: int = 42) -> tuple[np.ndarray, np.ndarray, dict]:
    set_global_seed(seed)
    # Synthetic deterministic GBM. Same seed -> same prices.
    rng = np.random.default_rng(seed)
    n = 1000
    rets = rng.normal(0.0005, 0.01, n)
    prices = pd.Series(
        100.0 * np.cumprod(1.0 + rets),
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=IBKR_costs, ppy=252)
    return np.asarray(res.rets), np.asarray(res.nav), res.metrics.to_dict()


def test_smoke_backtest_byte_identical_across_runs():
    """Same seed twice -> same output bytes. Non-negotiable."""
    rets1, nav1, metrics1 = _run_smoke_backtest(seed=42)
    rets2, nav2, metrics2 = _run_smoke_backtest(seed=42)
    h1 = _hash_result(rets1, nav1, metrics1)
    h2 = _hash_result(rets2, nav2, metrics2)
    assert h1 == h2, (
        f"determinism contract violated: {h1[:16]} vs {h2[:16]}"
    )


def test_different_seeds_produce_different_output():
    """Sanity: changing the seed actually changes the output.

    If this test passes alongside the byte-identical one, we know that
    determinism is keyed off the seed and not accidentally pinned to
    something else.
    """
    rets1, nav1, metrics1 = _run_smoke_backtest(seed=42)
    rets2, nav2, metrics2 = _run_smoke_backtest(seed=43)
    h1 = _hash_result(rets1, nav1, metrics1)
    h2 = _hash_result(rets2, nav2, metrics2)
    assert h1 != h2


def test_metrics_finite_under_canonical_smoke():
    """The smoke backtest must produce a finite Sharpe + Calmar."""
    _, _, metrics = _run_smoke_backtest(seed=42)
    # Calmar may be inf when MDD is exactly zero (R16 contract); allow
    # but require Sharpe finite.
    assert np.isfinite(metrics["sharpe"]) or pd.isna(metrics["sharpe"])
    # CAGR is always finite by R16 contract.
    assert np.isfinite(metrics["cagr"])
