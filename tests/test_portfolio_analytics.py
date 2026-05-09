# ruff: noqa: N806
"""Tests for portfolio.analytics and portfolio.attribution (Phase 4 gap)."""
from __future__ import annotations

import numpy as np
import pytest
from aurora.portfolio import (
    contribution_to_return,
    contribution_to_risk,
    decompose_return,
    rolling_correlation,
    rolling_max_drawdown,
    rolling_sharpe,
    rolling_volatility,
)


# --------------------------------------------------------------------------- #
# rolling_volatility                                                          #
# --------------------------------------------------------------------------- #
def test_rolling_volatility_warmup_is_nan():
    r = np.array([0.01, -0.02, 0.015, 0.0, -0.005])
    out = rolling_volatility(r, window=3)
    assert out.shape == r.shape
    # First window-1 entries are NaN (warmup).
    assert np.isnan(out[0])
    assert np.isnan(out[1])
    # First valid index.
    assert np.isfinite(out[2])


def test_rolling_volatility_first_valid_value_matches_numpy():
    r = np.array([0.01, -0.02, 0.015, 0.0, -0.005])
    out = rolling_volatility(r, window=3)
    expected = float(np.std(r[:3], ddof=1))
    assert out[2] == pytest.approx(expected, abs=1e-12)


def test_rolling_volatility_invalid_window():
    r = np.array([0.01, 0.02, 0.03])
    with pytest.raises(ValueError):
        rolling_volatility(r, window=0)
    with pytest.raises(ValueError):
        rolling_volatility(r, window=10)


# --------------------------------------------------------------------------- #
# rolling_sharpe                                                              #
# --------------------------------------------------------------------------- #
def test_rolling_sharpe_finite_for_nonzero_returns():
    rng = np.random.default_rng(7)
    r = rng.normal(0.0005, 0.01, size=300)
    out = rolling_sharpe(r, window=20, ppy=252)
    assert out.shape == r.shape
    # Warmup entries are NaN.
    assert np.all(np.isnan(out[:19]))
    # All valid entries are finite.
    valid = out[19:]
    assert np.all(np.isfinite(valid))


def test_rolling_sharpe_zero_variance_window_is_nan():
    # Constant returns -> std == 0 -> sharpe NaN for those windows.
    r = np.zeros(50)
    out = rolling_sharpe(r, window=10)
    assert np.all(np.isnan(out))


def test_rolling_sharpe_invalid_ppy():
    r = np.array([0.01, 0.02, 0.03, 0.04])
    with pytest.raises(ValueError):
        rolling_sharpe(r, window=2, ppy=0)


# --------------------------------------------------------------------------- #
# rolling_max_drawdown                                                        #
# --------------------------------------------------------------------------- #
def test_rolling_max_drawdown_zero_for_monotonic_increase():
    # Strictly positive returns -> equity always at peak -> drawdown is 0.
    r = np.full(20, 0.01)
    out = rolling_max_drawdown(r, window=5)
    assert np.all(np.isnan(out[:4]))
    assert np.all(out[4:] == 0.0)


def test_rolling_max_drawdown_negative_for_decline():
    # Big positive then big negative -> non-zero drawdown in window.
    r = np.array([0.05, 0.05, 0.05, -0.10, -0.05])
    out = rolling_max_drawdown(r, window=4)
    assert np.isnan(out[0])
    assert np.isnan(out[1])
    assert np.isnan(out[2])
    # The last two windows include the -0.10 drop, so drawdown < 0.
    assert out[3] < 0.0
    assert out[4] < 0.0


# --------------------------------------------------------------------------- #
# rolling_correlation                                                         #
# --------------------------------------------------------------------------- #
def test_rolling_correlation_identical_series_is_one():
    rng = np.random.default_rng(1)
    a = rng.normal(0.0, 0.01, size=100)
    out = rolling_correlation(a, a, window=20)
    assert np.all(np.isnan(out[:19]))
    valid = out[19:]
    assert np.allclose(valid, 1.0, atol=1e-9)


def test_rolling_correlation_independent_series_near_zero():
    rng = np.random.default_rng(2)
    a = rng.normal(0.0, 0.01, size=2000)
    b = rng.normal(0.0, 0.01, size=2000)
    out = rolling_correlation(a, b, window=200)
    valid = out[~np.isnan(out)]
    # Mean correlation across windows should be close to 0 for independent
    # series with this much data.
    assert abs(float(np.mean(valid))) < 0.1


def test_rolling_correlation_length_mismatch():
    a = np.array([0.0, 0.1, 0.2])
    b = np.array([0.0, 0.1])
    with pytest.raises(ValueError):
        rolling_correlation(a, b, window=2)


# --------------------------------------------------------------------------- #
# contribution_to_return                                                      #
# --------------------------------------------------------------------------- #
def test_contribution_to_return_sum_equals_portfolio_return():
    w = np.array([0.4, 0.3, 0.2, 0.1])
    r = np.array([0.02, -0.01, 0.005, 0.03])
    contrib = contribution_to_return(w, r)
    assert contrib.shape == w.shape
    expected_port = float(np.dot(w, r))
    assert float(np.sum(contrib)) == pytest.approx(expected_port, abs=1e-12)


def test_contribution_to_return_length_mismatch():
    w = np.array([0.5, 0.5])
    r = np.array([0.01, 0.02, 0.03])
    with pytest.raises(ValueError):
        contribution_to_return(w, r)


# --------------------------------------------------------------------------- #
# contribution_to_risk                                                        #
# --------------------------------------------------------------------------- #
def test_contribution_to_risk_sum_equals_portfolio_variance():
    rng = np.random.default_rng(3)
    R = rng.normal(0.0, 0.01, size=(500, 4))
    cov = np.cov(R, rowvar=False, ddof=1)
    w = np.array([0.4, 0.3, 0.2, 0.1])
    contrib = contribution_to_risk(w, cov)
    expected_var = float(w @ cov @ w)
    assert float(np.sum(contrib)) == pytest.approx(expected_var, abs=1e-12)


def test_contribution_to_risk_long_only_non_negative():
    rng = np.random.default_rng(4)
    R = rng.normal(0.0, 0.01, size=(500, 5))
    cov = np.cov(R, rowvar=False, ddof=1)
    w = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    contrib = contribution_to_risk(w, cov)
    # Long-only + PSD covariance => every entry is non-negative.
    # Allow a tiny negative slack from floating-point round-off.
    assert np.all(contrib >= -1e-12)


def test_contribution_to_risk_shape_mismatch():
    w = np.array([0.5, 0.5])
    cov = np.eye(3)
    with pytest.raises(ValueError):
        contribution_to_risk(w, cov)


# --------------------------------------------------------------------------- #
# decompose_return                                                            #
# --------------------------------------------------------------------------- #
def test_decompose_return_basic_keys_and_lengths():
    w = np.array([0.25, 0.25, 0.25, 0.25])
    r = np.array([0.05, -0.02, 0.01, 0.04])
    out = decompose_return(w, r)
    # Keys.
    assert "portfolio_return" in out
    assert "top_contributors" in out
    assert "bottom_contributors" in out
    # Top/bottom are length 3.
    assert len(out["top_contributors"]) == 3
    assert len(out["bottom_contributors"]) == 3
    # Each entry is (name, value) and name uses asset_<i>.
    for name, _ in out["top_contributors"]:
        assert name.startswith("asset_")
    for name, _ in out["bottom_contributors"]:
        assert name.startswith("asset_")


def test_decompose_return_portfolio_return_matches_dot_product():
    w = np.array([0.4, 0.3, 0.2, 0.1])
    r = np.array([0.02, -0.01, 0.005, 0.03])
    out = decompose_return(w, r)
    expected = float(np.dot(w, r))
    assert out["portfolio_return"] == pytest.approx(expected, abs=1e-12)


def test_decompose_return_top_is_descending_bottom_is_ascending():
    w = np.array([0.25, 0.25, 0.25, 0.25])
    r = np.array([0.05, -0.02, 0.01, 0.04])
    out = decompose_return(w, r)
    top_vals = [v for _, v in out["top_contributors"]]
    bot_vals = [v for _, v in out["bottom_contributors"]]
    assert top_vals == sorted(top_vals, reverse=True)
    assert bot_vals == sorted(bot_vals)
