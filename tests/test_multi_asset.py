"""Tests for MultiAssetEngine. Run: pytest aurora/tests/test_multi_asset.py -v"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.engine_multi import MultiAssetEngine, MultiAssetResult
from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs, IBKR_costs


# ------------------------------------------------------------------------- #
# Fixtures                                                                  #
# ------------------------------------------------------------------------- #
@pytest.fixture
def two_asset_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=1000, freq="B")
    rng = np.random.default_rng(42)
    rets_a = rng.normal(0.0005, 0.012, 1000)
    rets_b = rng.normal(0.0004, 0.014, 1000)
    pa = 100 * np.cumprod(1.0 + rets_a)
    pb = 50 * np.cumprod(1.0 + rets_b)
    return {
        "SPY": pd.Series(pa, index=idx, name="SPY"),
        "QQQ": pd.Series(pb, index=idx, name="QQQ"),
    }


@pytest.fixture
def four_asset_prices():
    set_global_seed(7)
    idx = pd.date_range("2012-01-01", periods=800, freq="B")
    rng = np.random.default_rng(7)
    out = {}
    for k, mu, sigma, p0 in [
        ("AAA", 0.0006, 0.011, 100.0),
        ("BBB", 0.0005, 0.013, 80.0),
        ("CCC", 0.0004, 0.015, 60.0),
        ("DDD", 0.0007, 0.010, 120.0),
    ]:
        r = rng.normal(mu, sigma, 800)
        p = p0 * np.cumprod(1.0 + r)
        out[k] = pd.Series(p, index=idx, name=k)
    return out


# ------------------------------------------------------------------------- #
# Required tests from spec                                                  #
# ------------------------------------------------------------------------- #
def test_basic_2_asset(two_asset_prices):
    """SPY+QQQ both LONG +0.5 -> portfolio NAV correct, attribution sums to total."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {
        "SPY": np.full(T, 0.5),
        "QQQ": np.full(T, 0.5),
    }

    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res = engine.run(pd_dict, weights, ppy=252)

    assert isinstance(res, MultiAssetResult)
    assert res.nav.shape == (T,)
    assert res.rets.shape == (T,)
    assert res.weights.shape == (T, 2)
    assert res.symbols == ["QQQ", "SPY"]  # sorted

    # gross = 0.5 + 0.5 = 1.0 -> at cap, no rescale
    assert np.allclose(res.rescale_factor, 1.0)
    assert np.allclose(res.gross_leverage, 1.0)
    assert np.allclose(res.net_leverage, 1.0)

    # attribution sums to total portfolio return (sum of bar-level net rets)
    total_attribution = sum(res.per_asset_attribution.values())
    total_portfolio = float(res.rets.sum())
    assert np.isclose(total_attribution, total_portfolio, atol=1e-10)

    # cross-check vs single-asset run_backtest with same weights, ZERO costs
    spy_single = run_backtest(
        pd_dict["SPY"], lambda p: np.full(len(p), 0.5), costs=ZERO_costs
    )
    qqq_single = run_backtest(
        pd_dict["QQQ"], lambda p: np.full(len(p), 0.5), costs=ZERO_costs
    )
    expected_total = (spy_single.rets.sum() + qqq_single.rets.sum())
    assert np.isclose(total_portfolio, expected_total, atol=1e-9)

    # NAV must be > 0
    assert np.all(res.nav > 0)


def test_gross_leverage_cap(two_asset_prices):
    """Pass weights summing to 2.0 -> engine rescales gross to 1.0."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {
        "SPY": np.full(T, 1.0),
        "QQQ": np.full(T, 1.0),
    }

    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res = engine.run(pd_dict, weights, ppy=252)

    # raw gross = 2.0, must be rescaled to 1.0
    assert np.allclose(res.gross_leverage, 1.0, atol=1e-12)
    assert np.allclose(res.rescale_factor, 0.5, atol=1e-12)
    # rescaled weights = 0.5 each
    assert np.allclose(res.weights, 0.5, atol=1e-12)
    # raw_weights preserved as 1.0
    assert np.allclose(res.raw_weights, 1.0, atol=1e-12)


def test_correlation_matrix(two_asset_prices):
    """Returns NxN matrix with diagonals = 1.0."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {
        "SPY": np.full(T, 0.5),
        "QQQ": np.full(T, 0.5),
    }
    engine = MultiAssetEngine()
    res = engine.run(pd_dict, weights)

    cm = res.correlation_matrix
    assert isinstance(cm, pd.DataFrame)
    assert cm.shape == (2, 2)
    assert list(cm.index) == ["QQQ", "SPY"]
    assert list(cm.columns) == ["QQQ", "SPY"]
    # diagonal = 1.0
    assert np.isclose(cm.iloc[0, 0], 1.0)
    assert np.isclose(cm.iloc[1, 1], 1.0)
    # symmetry
    assert np.isclose(cm.iloc[0, 1], cm.iloc[1, 0])
    # off-diagonal in [-1, 1]
    assert -1.0 <= cm.iloc[0, 1] <= 1.0


def test_per_asset_costs(two_asset_prices):
    """Different CostModel per asset -> costs apply correctly."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    # Force turnover by alternating weights bar-to-bar
    rng = np.random.default_rng(0)
    w_spy = np.where(rng.random(T) > 0.5, 0.5, -0.5)
    w_qqq = np.where(rng.random(T) > 0.5, 0.5, -0.5)
    weights = {"SPY": w_spy, "QQQ": w_qqq}

    cheap = CostModel(commission_bps=0.0, spread_bps=0.0, slippage_bps=0.0)
    expensive = CostModel(commission_bps=10.0, spread_bps=20.0, slippage_bps=30.0)

    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res_zero = engine.run(pd_dict, weights, costs_dict={"SPY": cheap, "QQQ": cheap})
    res_mixed = engine.run(pd_dict, weights, costs_dict={"SPY": cheap, "QQQ": expensive})

    # mixed run must produce strictly lower QQQ contribution than zero-cost run
    # (positive turnover -> positive cost drag)
    qqq_zero = res_zero.per_asset_attribution["QQQ"]
    qqq_mixed = res_mixed.per_asset_attribution["QQQ"]
    assert qqq_mixed < qqq_zero, (
        f"expensive QQQ should drag attribution lower: "
        f"zero={qqq_zero:.6f}, mixed={qqq_mixed:.6f}"
    )

    # SPY contribution should be unchanged (same costs)
    spy_zero = res_zero.per_asset_attribution["SPY"]
    spy_mixed = res_mixed.per_asset_attribution["SPY"]
    assert np.isclose(spy_zero, spy_mixed, atol=1e-12)

    # missing key in costs_dict -> defaults to ZERO_costs
    res_partial = engine.run(pd_dict, weights, costs_dict={"QQQ": expensive})
    assert np.isclose(
        res_partial.per_asset_attribution["SPY"], spy_zero, atol=1e-12
    )


# ------------------------------------------------------------------------- #
# Extra tests for robustness                                                #
# ------------------------------------------------------------------------- #
def test_net_leverage_cap(two_asset_prices):
    """Net cap = 0.5; both LONG 1.0 -> net=2.0 -> rescaled to 0.5."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {"SPY": np.full(T, 1.0), "QQQ": np.full(T, 1.0)}

    # gross cap loose, net cap tight
    engine = MultiAssetEngine(gross_leverage_cap=10.0, net_leverage_cap=0.5)
    res = engine.run(pd_dict, weights)

    # net = 2.0 -> rescaled by 0.25 to net=0.5
    assert np.allclose(res.net_leverage, 0.5, atol=1e-12)
    assert np.allclose(res.rescale_factor, 0.25, atol=1e-12)


def test_index_alignment_intersection(two_asset_prices):
    """Series with different lengths -> intersection used."""
    pd_dict = dict(two_asset_prices)
    pd_dict["QQQ"] = pd_dict["QQQ"].iloc[100:900]  # shorter
    T_spy = len(pd_dict["SPY"])
    T_qqq = len(pd_dict["QQQ"])
    weights = {
        "SPY": np.full(T_spy, 0.5),
        "QQQ": np.full(T_qqq, 0.5),
    }
    engine = MultiAssetEngine()
    res = engine.run(pd_dict, weights)
    # common index = intersection
    expected_T = T_qqq  # 800 bars
    assert res.nav.shape == (expected_T,)
    assert res.weights.shape == (expected_T, 2)


def test_weights_out_of_bounds_raises(two_asset_prices):
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {"SPY": np.full(T, 1.5), "QQQ": np.full(T, 0.5)}  # 1.5 > 1
    engine = MultiAssetEngine()
    with pytest.raises(ValueError, match="weights for SPY must be in"):
        engine.run(pd_dict, weights)


def test_mismatched_keys_raises(two_asset_prices):
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {"SPY": np.full(T, 0.5)}  # missing QQQ
    engine = MultiAssetEngine()
    with pytest.raises(ValueError, match="price_dict keys"):
        engine.run(pd_dict, weights)


def test_attribution_4_asset(four_asset_prices):
    """Attribution sums equals total portfolio return for 4-asset port."""
    pd_dict = four_asset_prices
    T = len(pd_dict["AAA"])
    weights = {
        "AAA": np.full(T, 0.25),
        "BBB": np.full(T, 0.25),
        "CCC": np.full(T, 0.25),
        "DDD": np.full(T, 0.25),
    }
    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res = engine.run(pd_dict, weights)

    assert res.symbols == ["AAA", "BBB", "CCC", "DDD"]
    assert res.correlation_matrix.shape == (4, 4)
    # diagonal = 1
    assert np.allclose(np.diag(res.correlation_matrix.values), 1.0)
    # attribution sum = portfolio total
    total_attr = sum(res.per_asset_attribution.values())
    total_port = float(res.rets.sum())
    assert np.isclose(total_attr, total_port, atol=1e-10)


def test_anti_lookahead_convention(two_asset_prices):
    """signal[i-1] applies to return[i]; verify by zeroing last weight."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    # full position then drop to zero on last bar; only return[T-1] uses w[T-2]
    w_spy = np.full(T, 0.5)
    w_qqq = np.full(T, 0.5)
    w_spy[-1] = 0.0  # last weight zero
    w_qqq[-1] = 0.0
    weights = {"SPY": w_spy, "QQQ": w_qqq}

    engine = MultiAssetEngine()
    res = engine.run(pd_dict, weights, ppy=252)

    # rets[0] must be 0 (no prior weight)
    assert res.rets[0] == 0.0
    # nav[0] must be 1.0
    assert np.isclose(res.nav[0], 1.0)


def test_default_costs_zero(two_asset_prices):
    """costs_dict=None defaults to ZERO_costs each."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {"SPY": np.full(T, 0.5), "QQQ": np.full(T, 0.5)}
    engine = MultiAssetEngine()

    res_none = engine.run(pd_dict, weights, costs_dict=None)
    res_explicit = engine.run(
        pd_dict, weights,
        costs_dict={"SPY": ZERO_costs, "QQQ": ZERO_costs},
    )
    assert np.allclose(res_none.rets, res_explicit.rets, atol=1e-15)


def test_align_intersection_default(two_asset_prices):
    """Default align_calendar='intersection' preserves original behavior."""
    pd_dict = dict(two_asset_prices)
    pd_dict["QQQ"] = pd_dict["QQQ"].iloc[100:900]  # shorter
    T_spy = len(pd_dict["SPY"])
    T_qqq = len(pd_dict["QQQ"])
    weights = {
        "SPY": np.full(T_spy, 0.5),
        "QQQ": np.full(T_qqq, 0.5),
    }
    engine = MultiAssetEngine()  # default = intersection
    assert engine.align_calendar == "intersection"
    res = engine.run(pd_dict, weights)
    # common index = intersection (= QQQ length here)
    assert res.nav.shape == (T_qqq,)
    assert res.weights.shape == (T_qqq, 2)


def test_align_union_ffill_holidays():
    """union_ffill: synthetic frame with one asset missing dates -> ffill keeps full date range."""
    set_global_seed(123)
    full_idx = pd.date_range("2020-01-01", periods=300, freq="D")
    rng = np.random.default_rng(123)
    p_full = 100 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, 300))
    p_short = pd.Series(p_full[::3], index=full_idx[::3], name="EQ")  # every 3rd day
    p_long = pd.Series(p_full, index=full_idx, name="CRYPTO")

    pd_dict = {"EQ": p_short, "CRYPTO": p_long}
    w_short = np.full(len(p_short), 0.5)
    w_long = np.full(len(p_long), 0.5)
    weights = {"EQ": w_short, "CRYPTO": w_long}

    engine = MultiAssetEngine(align_calendar="union_ffill")
    res = engine.run(pd_dict, weights)

    # union of indices = full 300 bars, not 100
    assert res.nav.shape == (300,)
    assert res.weights.shape == (300, 2)
    # no NaN propagated
    assert not np.any(np.isnan(res.nav))
    assert not np.any(np.isnan(res.rets))


def test_align_invalid_calendar_raises(two_asset_prices):
    """Unknown align_calendar value should raise ValueError."""
    with pytest.raises(ValueError, match="align_calendar"):
        MultiAssetEngine(align_calendar="bogus")


def test_engine_multi_attribution_compound(two_asset_prices):
    """attribution_method='compound' returns the same TOTAL as the realized
    portfolio PnL (NAV[-1] - 1.0), exactly decomposing the path. The default
    'additive' method preserves original behavior (sum of per-bar contribs)."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {
        "SPY": np.full(T, 0.5),
        "QQQ": np.full(T, 0.5),
    }

    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)

    res_add = engine.run(pd_dict, weights, ppy=252, attribution_method="additive")
    res_cmp = engine.run(pd_dict, weights, ppy=252, attribution_method="compound")

    # NAV path is identical regardless of attribution method
    np.testing.assert_allclose(res_add.nav, res_cmp.nav)

    # Additive: total equals sum of per-bar net rets (matches existing test_basic_2_asset)
    add_total = sum(res_add.per_asset_attribution.values())
    np.testing.assert_allclose(add_total, float(res_add.rets.sum()), atol=1e-10)

    # Compound: total equals realized portfolio PnL (NAV_T - 1.0), accounting
    # for compounding through the rebalance path.
    cmp_total = sum(res_cmp.per_asset_attribution.values())
    nav_pnl = float(res_cmp.nav[-1]) - 1.0
    np.testing.assert_allclose(cmp_total, nav_pnl, atol=1e-10)

    # The two methods should differ (otherwise the parameter is useless)
    # — compound > additive in absolute terms when portfolio is profitable
    if nav_pnl > 0:
        assert cmp_total > add_total

    # Default value must be 'additive' (back-compat)
    res_default = engine.run(pd_dict, weights, ppy=252)
    for s in res_add.per_asset_attribution:
        assert res_default.per_asset_attribution[s] == res_add.per_asset_attribution[s]


def test_engine_multi_attribution_invalid_method(two_asset_prices):
    """Unknown attribution_method should raise ValueError."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    weights = {
        "SPY": np.full(T, 0.5),
        "QQQ": np.full(T, 0.5),
    }
    engine = MultiAssetEngine()
    with pytest.raises(ValueError, match="attribution_method"):
        engine.run(pd_dict, weights, attribution_method="bogus")


def test_multi_asset_no_first_bar_cost_leak(two_asset_prices):
    """Per-asset apply_costs charges turnover at bar 0 = |w[0]| * per_trade_bps,
    even though the strategy holds no carried position on bar 0. Previously
    engine_multi only zeroed portfolio_rets[0] AFTER summing per-asset costs,
    so the per-asset attribution leaked the bar-0 turnover. With non-zero
    starting weights and IBKR_costs, the per-asset attribution sum must equal
    the portfolio path total exactly (no leak)."""
    pd_dict = two_asset_prices
    T = len(pd_dict["SPY"])
    # Both assets at 0.5 on bar 0 -> per-asset apply_costs would charge
    # delta_w = 0.5 each at non-zero per_trade_bps. We must NOT see those
    # bar-0 charges leak into per-asset attribution.
    weights = {
        "SPY": np.full(T, 0.5),
        "QQQ": np.full(T, 0.5),
    }
    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res = engine.run(
        pd_dict, weights,
        costs_dict={"SPY": IBKR_costs, "QQQ": IBKR_costs},
        ppy=252,
    )

    # rets[0] must be exactly 0.0 (no carry, no cost)
    assert res.rets[0] == 0.0
    # Each per-asset rets[0] must also be 0 (the leak source)
    for s, arr in res.per_asset_rets.items():
        assert arr[0] == 0.0, f"{s} rets[0] = {arr[0]} (expected 0; bar-0 leak)"
    # Attribution sum still equals portfolio total (consistency check)
    total_attribution = sum(res.per_asset_attribution.values())
    total_portfolio = float(res.rets.sum())
    assert np.isclose(total_attribution, total_portfolio, atol=1e-10)


def test_multi_asset_non_positive_prices_raises(two_asset_prices):
    """A zero or negative price aligned across symbols must raise — division
    in `prices[1:] / prices[:-1] - 1` would otherwise produce inf/nan that
    silently corrupts NAV."""
    pd_dict = dict(two_asset_prices)
    # corrupt one price to zero on a middle bar
    spy_corrupted = pd_dict["SPY"].copy()
    spy_corrupted.iloc[100] = 0.0
    pd_dict["SPY"] = spy_corrupted
    T = len(pd_dict["SPY"])
    weights = {"SPY": np.full(T, 0.5), "QQQ": np.full(T, 0.5)}
    engine = MultiAssetEngine()
    with pytest.raises(ValueError, match="non-positive prices"):
        engine.run(pd_dict, weights)
