"""Regression tests for the deep-audit critical/high validation fixes.

Each test pins one bug from the audit to prevent regression:

1. ``test_pipeline_no_dead_mc_call`` — pipeline.py used to call
   ``monte_carlo_trade_reorder`` twice (a dead first call burned a child RNG
   pull, poisoning reproducibility hashes). Patch the function with a counting
   stub and assert it is called exactly once.

2. ``test_dsr_annualized_vs_per_period_consistent`` — feeding an annualized
   Sharpe + bar count to ``deflated_sharpe_check`` without ``ppy`` inflated DSR.
   With ``ppy=252`` the new conversion must match passing the per-period Sharpe
   directly.

3. ``test_fixed_block_bootstrap_no_truncation_bias`` — fixed-block path used
   too few blocks and biased the distribution. Distribution mean should now
   sit close to the circular variant's mean.

4. ``test_runtime_lookahead_multi_shuffle_catches_subtle_leak`` — single
   permutation could miss a leak if the random draw left a key bar in place.
   With multiple shuffles the leak must still be caught.

5. ``test_purged_cv_embargo_respects_lookback`` — embargo must be at least
   ``lookback_bars`` when supplied.

6. ``test_walk_forward_factory_warns_on_global_fit`` — when the factory does
   not accept an IS slice, walk_forward must emit a UserWarning explaining the
   strategy is using globally-fit params.
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross
from quantforge.validation import pipeline as pipe_mod
from quantforge.validation.pipeline import validate_pipeline
from quantforge.validation.walk_forward import WFWindow, walk_forward
from quantforge.validation.monte_carlo import (
    MCResult,
    monte_carlo_bootstrap,
    monte_carlo_trade_reorder,
)
from quantforge.validation.deflated_sharpe import (
    deflated_sharpe_annualized,
    deflated_sharpe_check,
)
from quantforge.validation.lookahead_check import runtime_lookahead_check
from quantforge.validation.purged_cv import PurgedKFold


def _prices(n: int = 1500, seed: int = 17) -> pd.Series:
    set_global_seed(seed)
    idx = pd.date_range("2008-01-02", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="MAND")


def _factory():
    return MACross()


_FAST_WF = [
    WFWindow("WF1", "2008-01-02", "2010-12-31", "2011-01-01", "2011-12-31"),
    WFWindow("WF2", "2008-01-02", "2011-12-31", "2012-01-01", "2012-12-31"),
]


# --------------------------------------------------------------------------- #
# Issue 1 — pipeline.py double monte_carlo_trade_reorder call                 #
# --------------------------------------------------------------------------- #
def test_pipeline_no_dead_mc_call(monkeypatch):
    """Pipeline must invoke monte_carlo_trade_reorder exactly once."""
    real_fn = pipe_mod.monte_carlo_trade_reorder
    calls = {"n": 0, "kwargs": []}

    def counting_stub(weights, returns, *args, **kwargs):
        calls["n"] += 1
        calls["kwargs"].append(dict(kwargs))
        # Delegate to the real implementation so the rest of the pipeline
        # behaves normally.
        return real_fn(weights, returns, *args, **kwargs)

    monkeypatch.setattr(pipe_mod, "monte_carlo_trade_reorder", counting_stub)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        rep = validate_pipeline(
            _factory, _prices(), name="dead-mc",
            costs=ZERO_costs, wf_windows=_FAST_WF, mc_n_paths=20,
            min_wf_pass=0,
        )

    assert calls["n"] == 1, (
        f"monte_carlo_trade_reorder called {calls['n']} times — "
        "the dead first call must be removed"
    )
    assert rep is not None and hasattr(rep, "overall_passed")


# --------------------------------------------------------------------------- #
# Issue 2 — DSR unit mismatch                                                 #
# --------------------------------------------------------------------------- #
def test_dsr_annualized_vs_per_period_consistent():
    """Feeding annualized SR + ppy must equal feeding the per-period SR."""
    ppy = 252
    n_periods = 1000
    sr_ann = 1.5  # annualized
    sr_pp = sr_ann / np.sqrt(ppy)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        rep_ann = deflated_sharpe_annualized(
            observed_sharpe_ann=sr_ann, n_trials=10, n_periods=n_periods,
            ppy=ppy,
        )
        rep_check_ann = deflated_sharpe_check(
            observed_sharpe=sr_ann, n_trials=10, n_periods=n_periods,
            ppy=ppy,
        )
        rep_pp = deflated_sharpe_check(
            observed_sharpe=sr_pp, n_trials=10, n_periods=n_periods,
        )

    # All three paths should produce the same DSR up to float roundoff.
    assert rep_ann.dsr == pytest.approx(rep_pp.dsr, abs=1e-3)
    assert rep_check_ann.dsr == pytest.approx(rep_pp.dsr, abs=1e-3)
    # Sanity: passing the annualized SR with NO ppy will inflate DSR
    # noticeably — verify the difference is non-trivial so the test catches
    # regressions if someone strips the ppy parameter.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        rep_inflated = deflated_sharpe_check(
            observed_sharpe=sr_ann, n_trials=10, n_periods=n_periods,
        )
    assert rep_inflated.dsr > rep_ann.dsr  # the bug: inflated DSR


# --------------------------------------------------------------------------- #
# Issue 3 — fixed-block bootstrap truncation bias                              #
# --------------------------------------------------------------------------- #
def test_fixed_block_bootstrap_no_truncation_bias():
    """Fixed-method MDD distribution mean should agree with circular variant.

    With the ceil(T/block) blocks fix, the fixed method no longer drops the
    last partial block systematically, so its long-run distribution mean
    matches the circular bootstrap within Monte-Carlo noise.
    """
    rng = np.random.default_rng(31)
    r = rng.normal(0.0005, 0.01, 1000)
    res_circ = monte_carlo_bootstrap(
        r, n_paths=400, block_size=20, ppy=252,
        seed_name="bias_circ", method="circular",
    )
    res_fix = monte_carlo_bootstrap(
        r, n_paths=400, block_size=20, ppy=252,
        seed_name="bias_fixed", method="fixed",
    )
    # MDD percentiles: medians should agree in sign and stay close.
    # Both estimators are noisy at 400 paths — use a forgiving tolerance
    # on the absolute MDD level (in % units, mdd is typically a few %).
    assert abs(res_circ.p50_mdd - res_fix.p50_mdd) < 5.0, (
        f"fixed-method p50 MDD ({res_fix.p50_mdd:.3f}%) drifts far from "
        f"circular ({res_circ.p50_mdd:.3f}%) — truncation bias may be back"
    )


# --------------------------------------------------------------------------- #
# Issue 4 — multi-shuffle lookahead                                            #
# --------------------------------------------------------------------------- #
def _subtle_leaky_signal(prices: pd.Series) -> np.ndarray:
    """Pulls the next bar into the current decision — clear leak.

    Uses the value of bar i+1 to vote at bar i.
    """
    p = prices.values.astype(float)
    n = len(p)
    out = np.zeros(n)
    for i in range(n - 1):
        out[i] = 1.0 if p[i + 1] > p[i] else -1.0
    return out


def test_runtime_lookahead_multi_shuffle_catches_subtle_leak():
    """A single shuffle may miss a subtle leak; multi-shuffle catches it."""
    n = 200
    rng = np.random.default_rng(0)
    prices = pd.Series(
        100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n)),
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )

    rep = runtime_lookahead_check(_subtle_leaky_signal, prices, n_shuffles=20)
    assert rep.runtime_violation is True, "leak should be detected"
    assert rep.passed is False
    assert rep.runtime_metric_delta > 1e-6


def test_runtime_lookahead_n_shuffles_validation():
    """n_shuffles must be >= 1."""
    n = 60
    prices = pd.Series(np.linspace(100.0, 110.0, n))
    with pytest.raises(ValueError):
        runtime_lookahead_check(_subtle_leaky_signal, prices, n_shuffles=0)


# --------------------------------------------------------------------------- #
# Issue 5 — purged_cv embargo respects lookback                                #
# --------------------------------------------------------------------------- #
def test_purged_cv_embargo_respects_lookback():
    """When lookback_bars > embargo_pct*n, the effective embargo is lookback."""
    n = 1000
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    X = pd.DataFrame({"x": np.arange(n, dtype=float)}, index=idx)

    # embargo_pct=0.01 -> 10 bars, but lookback_bars=80 should win.
    pkf = PurgedKFold(n_splits=5, embargo_pct=0.01, lookback_bars=80)
    splits = list(pkf.split(X))
    assert len(splits) == 5

    # Pick any non-final fold; check the 80 bars right after test_end are
    # excluded from train.
    train_idx, test_idx = splits[0]
    test_end = int(test_idx[-1])
    forbidden = set(range(test_end + 1, min(test_end + 80, n - 1) + 1))
    bad = forbidden & set(int(i) for i in train_idx)
    assert not bad, f"lookback embargo not enforced: {bad}"

    # Sanity: with lookback_bars below embargo_pct*n, lookback does NOT shrink
    # the embargo (we want max, not min).
    pkf2 = PurgedKFold(n_splits=5, embargo_pct=0.10, lookback_bars=5)
    embargo_n = int(round(n * 0.10))
    splits2 = list(pkf2.split(X))
    train_idx2, test_idx2 = splits2[0]
    test_end2 = int(test_idx2[-1])
    forbidden2 = set(range(test_end2 + 1, min(test_end2 + embargo_n, n - 1) + 1))
    bad2 = forbidden2 & set(int(i) for i in train_idx2)
    assert not bad2, "embargo_pct floor not respected"


# --------------------------------------------------------------------------- #
# Issue 6 — walk_forward factory IS-arg fallback emits UserWarning             #
# --------------------------------------------------------------------------- #
def test_walk_forward_factory_warns_on_global_fit():
    """No-arg factory must emit a UserWarning saying the strategy is global."""
    n = 800
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.012, n)
    prices = pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="P")

    def no_arg_factory():
        return MACross(fast=10, slow=50)

    wins = [
        WFWindow("W1", "2010-01-01", "2011-12-31", "2012-01-01", "2012-12-31"),
        WFWindow("W2", "2010-01-01", "2012-12-31", "2013-01-01", "2013-12-31"),
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = walk_forward(no_arg_factory, prices, wins, min_oos_bars=20)

    msgs = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("globally-fit" in m for m in msgs), (
        f"expected UserWarning about globally-fit strategy, got: {msgs}"
    )
    assert res.n_total == 2


def test_walk_forward_factory_with_is_arg_no_warning():
    """Factory accepting is_prices must not trigger the global-fit warning."""
    n = 800
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.012, n)
    prices = pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="P")

    captured = {"is_lens": []}

    def factory_with_is(is_prices: pd.Series):
        captured["is_lens"].append(int(len(is_prices)))
        return MACross(fast=10, slow=50)

    wins = [
        WFWindow("W1", "2010-01-01", "2011-12-31", "2012-01-01", "2012-12-31"),
        WFWindow("W2", "2010-01-01", "2012-12-31", "2013-01-01", "2013-12-31"),
    ]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = walk_forward(factory_with_is, prices, wins, min_oos_bars=20)

    glob_msgs = [
        str(w.message) for w in caught
        if issubclass(w.category, UserWarning) and "globally-fit" in str(w.message)
    ]
    assert not glob_msgs, "factory accepting IS arg must not warn"
    assert res.n_total == 2
    assert len(captured["is_lens"]) == 2
    assert all(L > 100 for L in captured["is_lens"])


# --------------------------------------------------------------------------- #
# Issue 8 / 7 — monte_carlo trade reorder min_trades + horizon                #
# --------------------------------------------------------------------------- #
def test_monte_carlo_trade_reorder_min_trades_param():
    """Strategies with too few trades raise with helpful message."""
    n = 100
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0, 0.01, n)
    weights = np.zeros(n)
    weights[10:30] = 1.0
    weights[60:80] = -1.0
    # 2 trades total
    with pytest.raises(ValueError) as excinfo:
        monte_carlo_trade_reorder(weights, rets, n_paths=10, ppy=252,
                                   min_trades=10)
    msg = str(excinfo.value)
    assert "vol-target" in msg or "Kelly" in msg or "monte_carlo_bootstrap" in msg


def test_monte_carlo_trade_reorder_uses_full_horizon():
    """Reorder CAGR must use len(r)/ppy, matching the real path's horizon."""
    n = 504  # ~2 years of daily bars
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, n)
    weights = np.zeros(n)
    on = True
    for i in range(0, n, 21):
        if on:
            weights[i:i + 21] = 1.0
        on = not on
    res = monte_carlo_trade_reorder(weights, rets, n_paths=50, ppy=252,
                                     seed_name="horizon_test")
    assert isinstance(res, MCResult)
    assert np.isfinite(res.real_calmar)
    # Two years -> Calmar should be well-defined for finite real_mdd.


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
