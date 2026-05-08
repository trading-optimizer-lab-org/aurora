"""Tests for PairTrade strategy. Run: pytest quantforge/tests/test_pair_trade.py -v"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.strategies.library import PairTrade
from quantforge.strategies.base import StrategySpec


@pytest.fixture
def cointegrated_pair():
    """Two assets sharing a common factor + idiosyncratic noise.
    Spread mean-reverts -> z-score crosses entry/exit thresholds.
    """
    rng = np.random.default_rng(42)
    n = 500
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    factor = np.cumsum(rng.normal(0.0, 0.01, n))
    noise_a = rng.normal(0.0, 0.005, n)
    noise_b = rng.normal(0.0, 0.005, n)
    pa = 100.0 + factor + noise_a
    pb = 100.0 + factor + noise_b
    return {
        "AAA": pd.Series(pa, index=idx, name="AAA"),
        "BBB": pd.Series(pb, index=idx, name="BBB"),
    }


# ---- 1. basic synthetic cointegrated pair generates trades ---------------- #
def test_basic_pair(cointegrated_pair):
    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)
    w = pt.weights(cointegrated_pair)
    assert "AAA" in w and "BBB" in w
    n = len(cointegrated_pair["AAA"])
    assert w["AAA"].shape == (n,)
    assert w["BBB"].shape == (n,)
    # at least some non-zero weights generated
    assert np.any(w["AAA"] != 0.0), "no trades fired -> spread never crossed entry_z"
    # values bounded in [-0.5, 0.5]
    assert np.all(np.abs(w["AAA"]) <= 0.5 + 1e-12)
    assert np.all(np.abs(w["BBB"]) <= 0.5 + 1e-12)
    assert not np.any(np.isnan(w["AAA"]))
    assert not np.any(np.isnan(w["BBB"]))


# ---- 2. hedge ratio applied -> different B weights vs ratio=1.0 ----------- #
def test_hedge_ratio_applied(cointegrated_pair):
    pt1 = PairTrade(sym_a="AAA", sym_b="BBB",
                    lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)
    pt2 = PairTrade(sym_a="AAA", sym_b="BBB",
                    lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=2.0)
    w1 = pt1.weights(cointegrated_pair)
    w2 = pt2.weights(cointegrated_pair)
    # Different hedge ratio -> spread series differs -> z differs -> entry timing differs
    # At least one of the weight arrays must differ from the ratio=1.0 baseline.
    diff_a = np.any(w1["AAA"] != w2["AAA"])
    diff_b = np.any(w1["BBB"] != w2["BBB"])
    assert diff_a or diff_b, (
        "changing hedge_ratio from 1.0 to 2.0 produced identical weights"
    )


# ---- 3. anti-lookahead: shuffle B prices after k -> w[a, :k] unchanged ---- #
def test_no_lookahead(cointegrated_pair):
    rng = np.random.default_rng(0)
    pa = cointegrated_pair["AAA"]
    pb = cointegrated_pair["BBB"]
    n = len(pa)
    k = 200  # cutoff: we shuffle bars [k:]

    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)
    w_ref = pt.weights({"AAA": pa, "BBB": pb})

    # shuffle B's tail values after k (preserve index, scramble values)
    pb_vals = pb.values.copy()
    tail = pb_vals[k:].copy()
    rng.shuffle(tail)
    pb_vals[k:] = tail
    pb_shuf = pd.Series(pb_vals, index=pb.index, name="BBB")
    w_shuf = pt.weights({"AAA": pa, "BBB": pb_shuf})

    # Weights for bars [0, k) must be identical: rolling window of length 30
    # uses spread[i-29 : i+1]. For bar i < k - 0 we touch spread up to index i,
    # which only depends on pb[:i+1]. Check w[:k].
    assert np.array_equal(w_ref["AAA"][:k], w_shuf["AAA"][:k]), \
        "lookahead detected: AAA weights changed before shuffle cutoff"
    assert np.array_equal(w_ref["BBB"][:k], w_shuf["BBB"][:k]), \
        "lookahead detected: BBB weights changed before shuffle cutoff"


# ---- 4. anti-correlation: weights[a] and weights[b] always opposite signs - #
def test_anti_correlation(cointegrated_pair):
    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)
    w = pt.weights(cointegrated_pair)
    wa = w["AAA"]
    wb = w["BBB"]
    # whenever a leg is non-zero, the other leg must be the negation
    assert np.allclose(wa, -wb, atol=1e-15), \
        "legs are not exact opposites"
    # and any non-zero bar must have opposite signs (non-zero either both or neither)
    nz = wa != 0.0
    assert np.array_equal(nz, wb != 0.0)
    assert np.all(np.sign(wa[nz]) == -np.sign(wb[nz]))


# ---- 5. index alignment: different indexes -> aligned to intersection ----- #
def test_index_alignment():
    rng = np.random.default_rng(7)
    idx_a = pd.date_range("2010-01-01", periods=400, freq="B")
    idx_b = pd.date_range("2010-03-01", periods=400, freq="B")  # offset start
    factor_a = np.cumsum(rng.normal(0.0, 0.01, 400))
    factor_b = np.cumsum(rng.normal(0.0, 0.01, 400))
    pa = pd.Series(100.0 + factor_a, index=idx_a, name="AAA")
    pb = pd.Series(100.0 + factor_b, index=idx_b, name="BBB")

    common = idx_a.intersection(idx_b)
    assert len(common) > 50  # sanity: some overlap

    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3, hedge_ratio=1.0)
    w = pt.weights({"AAA": pa, "BBB": pb})
    # both leg arrays must have length == len(common)
    assert w["AAA"].shape == (len(common),)
    assert w["BBB"].shape == (len(common),)


# ---- spec ranges --------------------------------------------------------- #
def test_spec_ranges():
    spec = PairTrade.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.name == "PairTrade"
    assert spec.param_ranges["lookback"] == (20, 252)
    assert spec.param_ranges["entry_z"] == (1.0, 3.5)
    assert spec.param_ranges["exit_z"] == (0.0, 1.5)
    assert spec.param_ranges["hedge_ratio"] == (0.5, 2.0)
    assert spec.params["lookback"] == 60
    assert spec.params["entry_z"] == 2.0
    assert spec.params["exit_z"] == 0.5
    assert spec.params["hedge_ratio"] == 1.0


# ---- ctor validation ----------------------------------------------------- #
def test_ctor_validation():
    with pytest.raises(ValueError, match="must differ"):
        PairTrade(sym_a="X", sym_b="X")
    with pytest.raises(ValueError, match="lookback"):
        PairTrade(sym_a="A", sym_b="B", lookback=1)
    with pytest.raises(ValueError, match="entry_z"):
        PairTrade(sym_a="A", sym_b="B", entry_z=0.0)
    with pytest.raises(ValueError, match="exit_z"):
        PairTrade(sym_a="A", sym_b="B", exit_z=-0.1)
    # exit_z >= entry_z is no longer fatal; ctor projects exit_z into the
    # feasible region (exit_z = 0.99 * entry_z) so that the GA does not waste
    # ~28% of samples on an infeasible param region. Verify the projection
    # is applied AND the strict inequality exit_z < entry_z still holds.
    pt = PairTrade(sym_a="A", sym_b="B", entry_z=1.0, exit_z=1.0)
    assert pt.exit_z < pt.entry_z
    assert pt.exit_z == pytest.approx(0.99)
    pt2 = PairTrade(sym_a="A", sym_b="B", entry_z=2.0, exit_z=3.0)
    assert pt2.exit_z < pt2.entry_z
    assert pt2.exit_z == pytest.approx(1.98)


def test_missing_symbol_raises(cointegrated_pair):
    pt = PairTrade(sym_a="AAA", sym_b="ZZZ", lookback=30)
    with pytest.raises(KeyError, match="ZZZ"):
        pt.weights(cointegrated_pair)


def test_insufficient_overlap_raises():
    idx_a = pd.date_range("2010-01-01", periods=20, freq="B")
    idx_b = pd.date_range("2010-01-01", periods=20, freq="B")
    pa = pd.Series(np.linspace(100, 105, 20), index=idx_a)
    pb = pd.Series(np.linspace(100, 103, 20), index=idx_b)
    pt = PairTrade(sym_a="AAA", sym_b="BBB", lookback=60)
    with pytest.raises(ValueError, match="insufficient overlapping bars"):
        pt.weights({"AAA": pa, "BBB": pb})


# ---- 6. recompute_hedge_ratio_every: enabling rolling refit changes weights -- #
def test_pair_trade_hedge_ratio_recompute(cointegrated_pair):
    """recompute_hedge_ratio_every > 0 enables rolling-OLS hedge ratio.

    The recomputed ratio should differ from the static fixed ratio in general
    so weights diverge from the no-recompute baseline.
    """
    pt_fixed = PairTrade(sym_a="AAA", sym_b="BBB",
                         lookback=30, entry_z=1.5, exit_z=0.3,
                         hedge_ratio=1.0,
                         recompute_hedge_ratio_every=0)
    pt_dyn = PairTrade(sym_a="AAA", sym_b="BBB",
                       lookback=30, entry_z=1.5, exit_z=0.3,
                       hedge_ratio=1.0,
                       recompute_hedge_ratio_every=20)
    w_fixed = pt_fixed.weights(cointegrated_pair)
    w_dyn = pt_dyn.weights(cointegrated_pair)

    # Same shape
    assert w_fixed["AAA"].shape == w_dyn["AAA"].shape
    # Recompute must change at least one weight (synthetic noise -> ratio drifts)
    assert not np.array_equal(w_fixed["AAA"], w_dyn["AAA"]) or \
           not np.array_equal(w_fixed["BBB"], w_dyn["BBB"])
    # Anti-correlation invariant must still hold under recompute
    assert np.allclose(w_dyn["AAA"], -w_dyn["BBB"], atol=1e-15)


def test_pair_trade_hedge_ratio_recompute_no_lookahead(cointegrated_pair):
    """Mutating tail-only price data must not change pre-cutoff weights,
    even with rolling hedge-ratio refit enabled.
    """
    rng = np.random.default_rng(0)
    pa = cointegrated_pair["AAA"]
    pb = cointegrated_pair["BBB"]
    k = 200

    pt = PairTrade(sym_a="AAA", sym_b="BBB",
                   lookback=30, entry_z=1.5, exit_z=0.3,
                   hedge_ratio=1.0, recompute_hedge_ratio_every=20)
    w_ref = pt.weights({"AAA": pa, "BBB": pb})

    pb_vals = pb.values.copy()
    tail = pb_vals[k:].copy()
    rng.shuffle(tail)
    pb_vals[k:] = tail
    pb_shuf = pd.Series(pb_vals, index=pb.index, name="BBB")
    w_shuf = pt.weights({"AAA": pa, "BBB": pb_shuf})

    assert np.array_equal(w_ref["AAA"][:k], w_shuf["AAA"][:k])
    assert np.array_equal(w_ref["BBB"][:k], w_shuf["BBB"][:k])


def test_pair_trade_recompute_negative_raises():
    with pytest.raises(ValueError, match="recompute_hedge_ratio_every"):
        PairTrade(sym_a="A", sym_b="B", recompute_hedge_ratio_every=-1)


def test_pair_trade_with_params_carries_recompute():
    pt = PairTrade(sym_a="A", sym_b="B", recompute_hedge_ratio_every=15)
    pt2 = pt.with_params(lookback=80)
    assert pt2.recompute_hedge_ratio_every == 15
