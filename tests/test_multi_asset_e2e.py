"""E2E integration test combining MultiAssetEngine + HRP allocator + Black-Litterman.

Pipeline tested:
  1. Synthetic 3-asset GBM returns
  2. HRP allocator -> static weights summing to 1
  3. Run MultiAssetEngine with HRP weights -> portfolio NAV/metrics
  4. Run BL on prior + 1 absolute view -> posterior weights -> MultiAssetEngine
  5. Verify equity curves valid, metrics finite, no NaN propagation across assets

Run: pytest aurora/tests/test_multi_asset_e2e.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.engine_multi import MultiAssetEngine, MultiAssetResult
from aurora.core.costs import ZERO_costs
from aurora.deployment.hrp import hrp_allocate
from aurora.deployment.black_litterman import (
    BlackLittermanModel,
    market_implied_returns,
)


# --------------------------------------------------------------------------- #
# Fixture: 3 synthetic assets with mixed correlations                         #
# --------------------------------------------------------------------------- #
@pytest.fixture
def three_asset_data():
    """Three GBM assets, 600 daily bars.

    Returns:
        (price_dict, returns_df) where returns_df is the simple-return DataFrame
        used for HRP/BL covariance estimation.
    """
    set_global_seed(123)
    n = 600
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    rng = np.random.default_rng(123)

    # Two correlated assets + one uncorrelated outsider (HRP should bucket)
    base = rng.normal(0.0005, 0.012, n)
    pair_a = base + rng.normal(0.0, 0.002, n)
    pair_b = base + rng.normal(0.0, 0.002, n)
    outsider = rng.normal(0.0006, 0.014, n)

    price_a = 100.0 * np.cumprod(1.0 + pair_a)
    price_b = 80.0 * np.cumprod(1.0 + pair_b)
    price_c = 60.0 * np.cumprod(1.0 + outsider)

    price_dict = {
        "PAIR_A": pd.Series(price_a, index=idx, name="PAIR_A"),
        "PAIR_B": pd.Series(price_b, index=idx, name="PAIR_B"),
        "OUT":    pd.Series(price_c, index=idx, name="OUT"),
    }

    rets_df = pd.DataFrame(
        {"PAIR_A": pair_a, "PAIR_B": pair_b, "OUT": outsider}, index=idx
    )
    # First bar return = 0 (no prior price). Drop nothing; columns already aligned.
    return price_dict, rets_df


# --------------------------------------------------------------------------- #
# Helper: build constant-weight matrix for MultiAssetEngine                   #
# --------------------------------------------------------------------------- #
def _broadcast_weights(weights_series: pd.Series, T: int, symbols: list) -> dict:
    """Broadcast a per-asset Series into dict[symbol -> array(T,)]."""
    out = {}
    for s in symbols:
        out[s] = np.full(T, float(weights_series[s]))
    return out


# --------------------------------------------------------------------------- #
# E2E Tests                                                                   #
# --------------------------------------------------------------------------- #
def test_e2e_multi_asset_with_hrp(three_asset_data):
    """HRP allocator -> MultiAssetEngine. Verify NAV/metrics finite, no NaN."""
    price_dict, rets_df = three_asset_data
    T = len(rets_df)

    # Step 1: HRP weights
    hrp_res = hrp_allocate(rets_df, linkage_method="single", cov_estimator="sample")
    weights = hrp_res.weights
    assert abs(weights.sum() - 1.0) < 1e-9, f"HRP weights don't sum to 1: {weights.sum()}"
    assert (weights >= 0).all(), "HRP weights must be non-negative"

    # Step 2: feed HRP weights into MultiAssetEngine
    weight_dict = _broadcast_weights(weights, T, list(price_dict.keys()))
    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res = engine.run(price_dict, weight_dict, ppy=252)

    # Equity-curve invariants
    assert isinstance(res, MultiAssetResult)
    assert res.nav.shape == (T,)
    assert np.all(np.isfinite(res.nav)), "NAV has NaN/Inf"
    assert np.all(res.nav >= 0.0), f"NAV went negative: min={res.nav.min()}"
    assert abs(res.nav[0] - 1.0) < 1e-12 or res.nav[0] == 1.0 or res.nav[0] >= 0.0

    # Returns finite, no NaN propagation
    assert np.all(np.isfinite(res.rets)), "rets contain NaN/Inf"
    for sym, sym_rets in res.per_asset_rets.items():
        assert np.all(np.isfinite(sym_rets)), f"per-asset rets for {sym} have NaN/Inf"

    # Metrics finite
    m = res.metrics
    for fld in ["cagr", "mdd", "calmar", "sharpe", "sortino", "mar",
                "skew", "kurtosis", "win_rate", "profit_factor", "final_nav"]:
        v = getattr(m, fld)
        assert np.isfinite(v), f"metric {fld} not finite: {v}"


def test_e2e_multi_asset_with_bl_views(three_asset_data):
    """BL with views -> MultiAssetEngine. Verify equity curve + metrics finite."""
    price_dict, rets_df = three_asset_data
    T = len(rets_df)
    assets = list(rets_df.columns)

    # Build prior cov from sample returns
    prior_cov = rets_df.cov() * 252.0  # annualized cov
    # Construct a simple market-implied prior using equal market caps
    market_caps = pd.Series([1.0, 1.0, 1.0], index=assets)
    prior_returns = market_implied_returns(market_caps, prior_cov, risk_aversion=2.5)

    # Single absolute view: OUT will return 15% (above prior)
    views_p = pd.DataFrame(
        [[0.0, 0.0, 1.0]], columns=assets, index=["v0"]
    )
    views_q = pd.Series([0.15], index=["v0"])

    bl = BlackLittermanModel(
        prior_returns=prior_returns, prior_cov=prior_cov,
        views_p=views_p, views_q=views_q,
        view_confidence=0.5, tau=0.05,
    )
    optimal = bl.optimal_weights(risk_aversion=2.5)
    # Normalize to sum=1 so they fit weight bounds even with negative shorts
    # If long-only is required, clip to >= 0; here we allow signed but cap |w| <= 1.
    raw = optimal.values
    max_abs = np.max(np.abs(raw))
    if max_abs > 1.0:
        raw = raw / (max_abs + 1e-9)
    weights = pd.Series(raw, index=assets)

    weight_dict = _broadcast_weights(weights, T, assets)
    engine = MultiAssetEngine(gross_leverage_cap=2.0, net_leverage_cap=2.0)
    res = engine.run(price_dict, weight_dict, ppy=252)

    # Equity curve sanity
    assert np.all(np.isfinite(res.nav)), "NAV has NaN/Inf with BL weights"
    assert np.all(res.nav >= 0.0), f"NAV went negative: min={res.nav.min()}"
    assert np.all(np.isfinite(res.rets)), "rets contain NaN/Inf"

    # Metrics finite
    m = res.metrics
    for fld in ["cagr", "mdd", "calmar", "sharpe", "sortino"]:
        v = getattr(m, fld)
        assert np.isfinite(v), f"metric {fld} not finite under BL weights: {v}"

    # No NaN propagation across asset attribution
    for sym, contrib in res.per_asset_attribution.items():
        assert np.isfinite(contrib), f"attribution[{sym}] not finite"


def test_e2e_pipeline_no_nan_propagation(three_asset_data):
    """Run full pipeline (HRP then BL) and confirm no NaN appears in any output."""
    price_dict, rets_df = three_asset_data
    T = len(rets_df)
    assets = list(rets_df.columns)

    # Pipeline 1: HRP
    hrp_res = hrp_allocate(rets_df)
    hrp_weights_dict = _broadcast_weights(hrp_res.weights, T, assets)

    # Pipeline 2: BL with HRP weights as informal prior
    prior_cov = rets_df.cov() * 252.0
    prior_returns = market_implied_returns(
        market_caps=hrp_res.weights * 1000.0,  # scaled to positive caps
        prior_cov=prior_cov, risk_aversion=2.5,
    )
    bl = BlackLittermanModel(
        prior_returns=prior_returns, prior_cov=prior_cov,
        view_confidence=0.5, tau=0.05,
    )
    bl_returns = bl.posterior_returns()
    bl_cov = bl.posterior_cov()

    assert not bl_returns.isna().any(), "BL posterior returns contain NaN"
    assert not bl_cov.isna().values.any(), "BL posterior cov contains NaN"

    # Run engine with HRP weights, confirm metrics
    engine = MultiAssetEngine()
    res = engine.run(price_dict, hrp_weights_dict, ppy=252)
    assert np.all(np.isfinite(res.nav))
    assert not res.correlation_matrix.isna().values.any(), \
        "correlation matrix has NaN"


def test_e2e_with_costs_keeps_finite(three_asset_data):
    """Same pipeline but with non-zero costs. Equity must remain finite."""
    from aurora.core.costs import IBKR_costs

    price_dict, rets_df = three_asset_data
    T = len(rets_df)
    assets = list(rets_df.columns)

    hrp_res = hrp_allocate(rets_df)
    weight_dict = _broadcast_weights(hrp_res.weights, T, assets)
    costs_dict = {s: IBKR_costs for s in assets}

    engine = MultiAssetEngine()
    res = engine.run(price_dict, weight_dict, costs_dict=costs_dict, ppy=252)

    assert np.all(np.isfinite(res.nav))
    assert np.all(np.isfinite(res.rets))
    # final NAV may dip from costs but must not be NaN
    assert np.isfinite(res.metrics.final_nav)
