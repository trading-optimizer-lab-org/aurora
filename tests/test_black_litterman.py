"""Tests for Black-Litterman blended-views model."""
from __future__ import annotations
import warnings

import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.black_litterman import (
    BlackLittermanModel,
    BLResult,
    market_implied_returns,
    _project_psd,
    _MAX_CONFIDENCE,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def four_asset_setup():
    """Four-asset universe with a plausible covariance matrix."""
    assets = ["A", "B", "C", "D"]
    rng = np.random.default_rng(42)
    # Construct a PSD covariance via X^T X.
    X = rng.normal(scale=0.02, size=(200, 4))
    cov = pd.DataFrame(np.cov(X, rowvar=False), index=assets, columns=assets)
    # Plausible prior expected returns (annualized-ish).
    prior = pd.Series([0.06, 0.08, 0.04, 0.10], index=assets)
    return assets, prior, cov


@pytest.fixture
def market_caps():
    return pd.Series([300.0, 200.0, 150.0, 350.0], index=["A", "B", "C", "D"])


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
def test_no_views_returns_prior(four_asset_setup):
    """Empty views -> posterior returns equal prior returns."""
    assets, prior, cov = four_asset_setup
    bl = BlackLittermanModel(prior_returns=prior, prior_cov=cov)
    posterior = bl.posterior_returns()
    np.testing.assert_allclose(posterior.values, prior.values, atol=1e-12)
    # Posterior cov should still be returned and PSD.
    posterior_cov = bl.posterior_cov()
    assert posterior_cov.shape == (4, 4)


def test_no_views_with_explicit_empty(four_asset_setup):
    """Explicit empty DataFrame/Series for views also returns prior."""
    assets, prior, cov = four_asset_setup
    empty_p = pd.DataFrame(columns=assets)
    empty_q = pd.Series(dtype=float)
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=empty_p, views_q=empty_q,
    )
    np.testing.assert_allclose(
        bl.posterior_returns().values, prior.values, atol=1e-12
    )


def test_single_absolute_view_high_confidence(four_asset_setup):
    """Confidence near 1 -> view dominates the corresponding asset."""
    assets, prior, cov = four_asset_setup
    # Absolute view on asset A: A will return 0.20 (much higher than prior 0.06)
    P = pd.DataFrame([[1.0, 0.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q = pd.Series([0.20], index=["v0"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=0.999,  # near-deterministic view
    )
    posterior = bl.posterior_returns()
    # Asset A should move strongly toward the view (0.20).
    assert posterior["A"] > prior["A"] + 0.05, (
        f"Posterior A={posterior['A']:.4f} should be much larger than prior "
        f"{prior['A']:.4f} given high-confidence view of 0.20"
    )
    # And it should be close to the view itself.
    assert abs(posterior["A"] - 0.20) < abs(prior["A"] - 0.20), (
        "Posterior A should be closer to view (0.20) than prior was."
    )


def test_single_relative_view(four_asset_setup):
    """Relative view: A outperforms B by 0.05.
    Posterior should respect direction: A's return rises, B's falls (or A-B
    spread increases vs prior).
    """
    assets, prior, cov = four_asset_setup
    # Prior spread: A - B = 0.06 - 0.08 = -0.02 (B currently expected higher).
    # View says A outperforms B by 0.05 -> spread should move toward +0.05.
    P = pd.DataFrame([[1.0, -1.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q = pd.Series([0.05], index=["v0"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=0.8,
    )
    posterior = bl.posterior_returns()
    prior_spread = prior["A"] - prior["B"]
    post_spread = posterior["A"] - posterior["B"]
    # Spread must have moved in direction of the view (i.e. become larger than
    # prior, ideally toward 0.05).
    assert post_spread > prior_spread, (
        f"Posterior A-B spread {post_spread:.4f} did not move toward view "
        f"{0.05} from prior spread {prior_spread:.4f}"
    )


def test_multiple_views_handled(four_asset_setup):
    """Two simultaneous views on different assets."""
    assets, prior, cov = four_asset_setup
    P = pd.DataFrame(
        [[1.0, 0.0, 0.0, 0.0],
         [0.0, 0.0, 1.0, -1.0]],
        columns=assets,
        index=["abs_A", "rel_C_D"],
    )
    Q = pd.Series([0.15, 0.02], index=["abs_A", "rel_C_D"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=0.6,
    )
    posterior = bl.posterior_returns()
    # Asset A should move up toward 0.15.
    assert posterior["A"] > prior["A"]
    # Spread C - D should move up toward 0.02.
    prior_spread = prior["C"] - prior["D"]   # 0.04 - 0.10 = -0.06
    post_spread = posterior["C"] - posterior["D"]
    assert post_spread > prior_spread
    # All four assets returned with a finite value.
    assert posterior.notna().all()
    # Sigma_post is square and aligned.
    sigma_post = bl.posterior_cov()
    assert sigma_post.shape == (4, 4)
    assert list(sigma_post.index) == assets
    assert list(sigma_post.columns) == assets


def test_market_implied_returns_basic(four_asset_setup, market_caps):
    """CAPM-implied prior: pi = lambda * Sigma * w_market."""
    assets, _, cov = four_asset_setup
    pi = market_implied_returns(market_caps, cov, risk_aversion=2.5)
    assert isinstance(pi, pd.Series)
    assert list(pi.index) == assets
    assert pi.notna().all()

    # Manual recomputation to confirm formula.
    w = market_caps / market_caps.sum()
    expected = 2.5 * cov.values @ w.values
    np.testing.assert_allclose(pi.values, expected, atol=1e-12)


def test_market_implied_returns_rejects_bad_input(four_asset_setup):
    """Negative caps and non-positive risk_aversion are rejected."""
    assets, _, cov = four_asset_setup
    with pytest.raises(ValueError):
        market_implied_returns(
            pd.Series([-1.0, 1.0, 1.0, 1.0], index=assets), cov, risk_aversion=2.5,
        )
    with pytest.raises(ValueError):
        market_implied_returns(
            pd.Series([1.0, 1.0, 1.0, 1.0], index=assets), cov, risk_aversion=0.0,
        )


def test_posterior_cov_psd(four_asset_setup):
    """Posterior covariance is PSD: all eigenvalues >= 0 (within tolerance)."""
    assets, prior, cov = four_asset_setup
    P = pd.DataFrame(
        [[1.0, 0.0, 0.0, 0.0],
         [0.0, 1.0, -1.0, 0.0],
         [0.0, 0.0, 0.0, 1.0]],
        columns=assets,
        index=["v1", "v2", "v3"],
    )
    Q = pd.Series([0.12, 0.03, 0.07], index=["v1", "v2", "v3"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=0.5,
    )
    sigma_post = bl.posterior_cov().values
    # Must be symmetric.
    np.testing.assert_allclose(sigma_post, sigma_post.T, atol=1e-10)
    # Eigenvalues non-negative (PSD).
    eigvals = np.linalg.eigvalsh(sigma_post)
    assert np.all(eigvals > -1e-10), (
        f"Posterior cov is not PSD; min eig = {eigvals.min():.3e}"
    )


def test_weights_sum_to_one(four_asset_setup):
    """Optimal weights normalize to sum 1.0."""
    assets, prior, cov = four_asset_setup
    P = pd.DataFrame([[1.0, 0.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q = pd.Series([0.10], index=["v0"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=0.5,
    )
    w = bl.optimal_weights(risk_aversion=1.0)
    assert isinstance(w, pd.Series)
    assert list(w.index) == assets
    assert w.notna().all()
    assert abs(w.sum() - 1.0) < 1e-10, f"Weights sum to {w.sum()}, expected 1.0"


def test_per_view_confidence_series(four_asset_setup):
    """view_confidence as Series is honored per-view."""
    assets, prior, cov = four_asset_setup
    P = pd.DataFrame(
        [[1.0, 0.0, 0.0, 0.0],
         [0.0, 1.0, 0.0, 0.0]],
        columns=assets,
        index=["high_conf", "low_conf"],
    )
    Q = pd.Series([0.20, 0.20], index=["high_conf", "low_conf"])
    confidences = pd.Series([0.95, 0.05], index=["high_conf", "low_conf"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=confidences,
    )
    posterior = bl.posterior_returns()
    # Asset A (high confidence view of 0.20) should be MUCH closer to 0.20 than
    # asset B (low confidence view of 0.20).
    assert abs(posterior["A"] - 0.20) < abs(posterior["B"] - 0.20), (
        f"High-confidence view should pull A closer to view than B. "
        f"Got A={posterior['A']:.4f}, B={posterior['B']:.4f}"
    )


def test_invalid_inputs(four_asset_setup):
    """Constructor raises on bad input shapes / values."""
    assets, prior, cov = four_asset_setup
    # tau <= 0
    with pytest.raises(ValueError):
        BlackLittermanModel(prior_returns=prior, prior_cov=cov, tau=0.0)

    # mismatched p/q lengths
    P = pd.DataFrame([[1.0, 0.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q = pd.Series([0.1, 0.2], index=["v0", "v1"])
    with pytest.raises(ValueError):
        BlackLittermanModel(
            prior_returns=prior, prior_cov=cov, views_p=P, views_q=Q,
        )

    # confidence out of (0, 1]
    P_ok = pd.DataFrame([[1.0, 0.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q_ok = pd.Series([0.1], index=["v0"])
    with pytest.raises(ValueError):
        BlackLittermanModel(
            prior_returns=prior, prior_cov=cov,
            views_p=P_ok, views_q=Q_ok,
            view_confidence=1.5,
        )
    with pytest.raises(ValueError):
        BlackLittermanModel(
            prior_returns=prior, prior_cov=cov,
            views_p=P_ok, views_q=Q_ok,
            view_confidence=0.0,
        )


def test_result_bundle(four_asset_setup):
    """`.result()` returns a populated BLResult dataclass."""
    assets, prior, cov = four_asset_setup
    P = pd.DataFrame([[1.0, 0.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q = pd.Series([0.10], index=["v0"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=0.6,
    )
    res = bl.result(risk_aversion=2.5)
    assert isinstance(res, BLResult)
    assert list(res.posterior_returns.index) == assets
    assert res.posterior_cov.shape == (4, 4)
    assert list(res.prior_returns.index) == assets
    assert res.views_p.shape == (1, 4)
    assert res.views_q.shape == (1,)
    assert res.omega.shape == (1, 1)
    assert list(res.optimal_weights.index) == assets
    assert abs(res.optimal_weights.sum() - 1.0) < 1e-10


# --------------------------------------------------------------------------- #
# Confidence == 1.0 handling                                                  #
# --------------------------------------------------------------------------- #
def test_bl_rejects_confidence_one_or_clips(four_asset_setup):
    """Confidence == 1 must either raise ValueError or clip with warning."""
    assets, prior, cov = four_asset_setup
    P = pd.DataFrame([[1.0, 0.0, 0.0, 0.0]], columns=assets, index=["v0"])
    Q = pd.Series([0.10], index=["v0"])

    # Scalar confidence == 1: should warn and clip to _MAX_CONFIDENCE.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bl = BlackLittermanModel(
            prior_returns=prior, prior_cov=cov,
            views_p=P, views_q=Q,
            view_confidence=1.0,
        )
        msgs = [str(w.message) for w in caught]
    assert any("view_confidence == 1.0" in m for m in msgs), (
        f"Expected confidence-clip warning, got: {msgs}"
    )
    # Result must still be finite + posterior cov PSD.
    posterior = bl.posterior_returns()
    assert posterior.notna().all()
    sigma_post = bl.posterior_cov().values
    eig = np.linalg.eigvalsh(sigma_post)
    assert eig.min() >= -1e-10

    # Series confidence with one entry == 1: same behaviour.
    P2 = pd.DataFrame(
        [[1.0, 0.0, 0.0, 0.0],
         [0.0, 1.0, 0.0, 0.0]],
        columns=assets, index=["v0", "v1"],
    )
    Q2 = pd.Series([0.10, 0.05], index=["v0", "v1"])
    confidences = pd.Series([1.0, 0.5], index=["v0", "v1"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bl2 = BlackLittermanModel(
            prior_returns=prior, prior_cov=cov,
            views_p=P2, views_q=Q2,
            view_confidence=confidences,
        )
        msgs = [str(w.message) for w in caught]
    assert any("view_confidence == 1.0" in m for m in msgs)
    assert bl2.posterior_returns().notna().all()


# --------------------------------------------------------------------------- #
# Pinv warning on singular system                                             #
# --------------------------------------------------------------------------- #
def test_pinv_warns_on_singular(four_asset_setup):
    """A singular Sigma_post must trigger pinv warning in optimal_weights."""
    assets, prior, _ = four_asset_setup
    # Construct a degenerate (singular) prior cov so posterior also singular.
    # Use a rank-2 PSD matrix.
    rng = np.random.default_rng(0)
    F = rng.standard_normal((4, 2)) * 0.01
    sing_cov = pd.DataFrame(F @ F.T, index=assets, columns=assets)
    bl = BlackLittermanModel(prior_returns=prior, prior_cov=sing_cov)
    # Without views Sigma_post = Sigma + tau*Sigma is also rank-2 -> singular.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w = bl.optimal_weights(risk_aversion=1.0)
        msgs = [str(m.message) for m in caught]
    # solve will fail and the pinv branch must warn.
    assert any("pseudo-inverse" in m for m in msgs), (
        f"Expected pinv warning, got: {msgs}"
    )
    assert w.notna().all()


# --------------------------------------------------------------------------- #
# Posterior cov is PSD-clipped                                                #
# --------------------------------------------------------------------------- #
def test_posterior_cov_psd_after_clip(four_asset_setup):
    """`_project_psd` must lift any negative eigenvalues to >= 0."""
    assets, _, _ = four_asset_setup
    # Construct a symmetric matrix with a known negative eigenvalue.
    M = np.array([
        [1.0, 2.0, 0.0, 0.0],
        [2.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    eig_in = np.linalg.eigvalsh(M)
    assert eig_in.min() < -1e-6  # confirm input has negative eigenvalue
    fixed = _project_psd(M)
    eig_out = np.linalg.eigvalsh(fixed)
    assert eig_out.min() >= -1e-12, (
        f"PSD projection still has negative eig: {eig_out.min():.3e}"
    )
    # Symmetric.
    np.testing.assert_allclose(fixed, fixed.T, atol=1e-12)


def test_posterior_cov_psd_via_full_pipeline(four_asset_setup):
    """End-to-end: BL with high-confidence views -> posterior cov is PSD."""
    assets, prior, cov = four_asset_setup
    # Several near-deterministic views to stress numerical PSD.
    P = pd.DataFrame(
        [[1.0, 0.0, 0.0, 0.0],
         [0.0, 1.0, 0.0, 0.0],
         [0.0, 0.0, 1.0, -1.0]],
        columns=assets, index=["v0", "v1", "v2"],
    )
    Q = pd.Series([0.20, 0.15, 0.05], index=["v0", "v1", "v2"])
    bl = BlackLittermanModel(
        prior_returns=prior, prior_cov=cov,
        views_p=P, views_q=Q,
        view_confidence=_MAX_CONFIDENCE,  # safe value
    )
    sigma_post = bl.posterior_cov().values
    eig = np.linalg.eigvalsh(sigma_post)
    assert eig.min() >= -1e-10, (
        f"Posterior cov not PSD; min eig = {eig.min():.3e}"
    )


# --------------------------------------------------------------------------- #
# Issue 17: low-end confidence floor with warning
# --------------------------------------------------------------------------- #
def test_bl_low_confidence_clipped_with_warning(four_asset_setup):
    from quantforge.deployment.black_litterman import _MIN_CONFIDENCE
    assets, prior, cov = four_asset_setup
    # Single absolute view on asset A.
    P = pd.DataFrame([[1, 0, 0, 0]], columns=assets, index=["v1"]).astype(float)
    Q = pd.Series([0.20], index=["v1"])

    # Confidence below the floor should warn and clip.
    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter("always")
        bl = BlackLittermanModel(
            prior_returns=prior, prior_cov=cov,
            views_p=P, views_q=Q,
            view_confidence=1e-5,  # below _MIN_CONFIDENCE
        )
    msgs = [str(w.message) for w in wlist if "confidence" in str(w.message)]
    assert any(str(_MIN_CONFIDENCE) in m for m in msgs), msgs

    # And the BL solver should still produce a finite, PSD posterior.
    sigma_post = bl.posterior_cov().values
    eig = np.linalg.eigvalsh(sigma_post)
    assert np.all(np.isfinite(sigma_post))
    assert eig.min() >= -1e-9
