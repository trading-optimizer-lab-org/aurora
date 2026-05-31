"""Walk-forward across a multi-asset price dict.

The single-asset ``walk_forward`` is reused per symbol. We verify that each
WF fold produces finite metrics for every asset in the dict.

Run: pytest aurora/tests/test_wf_multi_asset.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.costs import ZERO_costs
from aurora.strategies.library import MACross
from aurora.validation.walk_forward import (
    generate_wf_windows,
    walk_forward,
)


@pytest.fixture
def two_asset_prices():
    """Synthetic 2-asset price dict, 1000 daily bars each."""
    set_global_seed(2024)
    idx = pd.date_range("2014-01-01", periods=1000, freq="B")
    rng = np.random.default_rng(2024)
    out = {}
    for sym, mu, sigma, p0 in [
        ("ALPHA", 0.0005, 0.012, 100.0),
        ("BETA",  0.0004, 0.014, 80.0),
    ]:
        rets = rng.normal(mu, sigma, 1000)
        prices = p0 * np.cumprod(1.0 + rets)
        out[sym] = pd.Series(prices, index=idx, name=sym)
    return out


def test_wf_runs_per_asset(two_asset_prices):
    """walk_forward runs successfully for each asset; each fold has metrics."""
    strat_factory = lambda: MACross(fast=20, slow=100)

    results = {}
    for sym, prices in two_asset_prices.items():
        res = walk_forward(
            strat_factory, prices, mode="rolling",
            n_windows=4, oos_pct=0.20, costs=ZERO_costs, ppy=252,
        )
        results[sym] = res
        assert res.n_total == 4, (
            f"{sym}: expected 4 windows, got {res.n_total}"
        )

    # Each asset must produce metrics for every fold
    for sym, res in results.items():
        for w in res.windows:
            # Ensure each window dict has the expected keys (skip "insufficient data" windows)
            if "reason" in w:
                pytest.fail(
                    f"{sym}: window {w['window']} skipped: {w['reason']}"
                )
            assert "calmar" in w, f"{sym}: missing calmar in window {w}"
            assert "cagr" in w, f"{sym}: missing cagr in window {w}"
            assert "mdd" in w, f"{sym}: missing mdd in window {w}"
            assert "sharpe" in w, f"{sym}: missing sharpe in window {w}"
            for k in ("calmar", "cagr", "mdd", "sharpe"):
                assert np.isfinite(w[k]), (
                    f"{sym}: non-finite {k} in window {w['window']}: {w[k]}"
                )


def test_wf_fold_metrics_valid_for_all_assets(two_asset_prices):
    """Every WF fold across both assets must yield non-NaN metrics."""
    strat_factory = lambda: MACross(fast=20, slow=100)

    per_asset_folds = {}
    for sym, prices in two_asset_prices.items():
        res = walk_forward(
            strat_factory, prices, mode="expanding",
            n_windows=3, oos_pct=0.30, costs=ZERO_costs, ppy=252,
        )
        per_asset_folds[sym] = res.windows

    # Same number of folds across assets
    fold_counts = {sym: len(w) for sym, w in per_asset_folds.items()}
    assert len(set(fold_counts.values())) == 1, (
        f"fold counts disagree across assets: {fold_counts}"
    )

    # Each fold pair (across assets, same index) has finite metrics
    n_folds = next(iter(fold_counts.values()))
    for fold_i in range(n_folds):
        for sym, folds in per_asset_folds.items():
            f = folds[fold_i]
            if "reason" in f:
                continue
            for k in ("calmar", "cagr", "mdd", "sharpe"):
                assert np.isfinite(f[k]), (
                    f"asset={sym}, fold={fold_i}: {k}={f[k]} is not finite"
                )


def test_wf_window_generation_per_asset(two_asset_prices):
    """generate_wf_windows produces non-overlapping OOS for each symbol."""
    for sym, prices in two_asset_prices.items():
        windows = generate_wf_windows(
            prices, n_windows=4, oos_pct=0.25, mode="rolling",
        )
        assert len(windows) == 4, f"{sym}: expected 4, got {len(windows)}"

        # Strict non-overlap: oos_start[k+1] > oos_end[k]
        for i in range(1, len(windows)):
            prev_end = pd.Timestamp(windows[i - 1].oos_end)
            curr_start = pd.Timestamp(windows[i].oos_start)
            assert curr_start > prev_end, (
                f"{sym}: window {i} OOS overlaps previous; "
                f"start={curr_start} <= prev_end={prev_end}"
            )
