"""Tests for the proper risk-parity allocator (convex solver).

Run: pytest quantforge/tests/test_risk_parity.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.risk_parity import (
    RPResult,
    equal_risk_contribution,
    risk_budget,
    risk_contributions,
    risk_parity_weights,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def cov_2_equal_vol():
    """Two assets, identical variance, zero correlation."""
    return pd.DataFrame(
        [[0.04, 0.0], [0.0, 0.04]],
        index=["A", "B"], columns=["A", "B"],
    )


@pytest.fixture
def cov_2_diff_vol():
    """Two assets: A is low vol, B is high vol, mild positive correlation."""
    return pd.DataFrame(
        [[0.01, 0.005], [0.005, 0.09]],
        index=["LO", "HI"], columns=["LO", "HI"],
    )


@pytest.fixture
def cov_5_diversified():
    """5-asset diversified covariance with realistic structure."""
    rng = np.random.default_rng(42)
    n = 5
    vols = np.array([0.10, 0.15, 0.20, 0.25, 0.30])
    # Structured correlation: 0.3 baseline, jitter
    rho = 0.3 * np.ones((n, n)) + 0.05 * (rng.random((n, n)) - 0.5)
    rho = 0.5 * (rho + rho.T)
    np.fill_diagonal(rho, 1.0)
    cov = np.outer(vols, vols) * rho
    cov = 0.5 * (cov + cov.T)
    # Project onto PSD by clipping eigenvalues
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.maximum(eigvals, 1e-6)
    cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
    cov = 0.5 * (cov + cov.T)
    names = [f"A{i}" for i in range(n)]
    return pd.DataFrame(cov, index=names, columns=names)


@pytest.fixture
def cov_diag_3():
    """Diagonal covariance: vols 10%, 20%, 40%."""
    vols = np.array([0.10, 0.20, 0.40])
    return pd.DataFrame(
        np.diag(vols ** 2),
        index=["X", "Y", "Z"], columns=["X", "Y", "Z"],
    )


# --------------------------------------------------------------------------- #
# Test: 2 assets, equal vol -> 50/50                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_2_asset_equal_vol(cov_2_equal_vol, method):
    res = risk_parity_weights(cov_2_equal_vol, method=method)
    assert isinstance(res, RPResult)
    assert pytest.approx(res.weights["A"], abs=1e-4) == 0.5
    assert pytest.approx(res.weights["B"], abs=1e-4) == 0.5
    assert pytest.approx(res.weights.sum(), abs=1e-9) == 1.0


# --------------------------------------------------------------------------- #
# Test: 2 assets, different vol -> high-vol gets less weight                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_2_asset_diff_vol(cov_2_diff_vol, method):
    res = risk_parity_weights(cov_2_diff_vol, method=method)
    assert res.weights["LO"] > res.weights["HI"]
    # Both strictly positive
    assert (res.weights > 0).all()
    assert pytest.approx(res.weights.sum(), abs=1e-9) == 1.0


# --------------------------------------------------------------------------- #
# Test: 5-asset diversified ERC -> approximately equal contributions          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_5_asset_diversified(cov_5_diversified, method):
    res = risk_parity_weights(cov_5_diversified, method=method,
                              max_iter=2000, tol=1e-10)
    n = len(res.weights)
    # Each normalized contribution close to 1/N
    rc_norm = res.risk_contributions / res.risk_contributions.sum()
    assert np.max(np.abs(rc_norm - 1.0 / n)) < 1e-3
    # Sanity: weights non-negative and sum to 1
    assert (res.weights >= 0).all()
    assert pytest.approx(res.weights.sum(), abs=1e-9) == 1.0


# --------------------------------------------------------------------------- #
# Test: ERC has equal risk contributions                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_risk_contributions_equal(cov_5_diversified, method):
    res = equal_risk_contribution(cov_5_diversified, method=method,
                                  max_iter=2000, tol=1e-10)
    rc = res.risk_contributions.to_numpy()
    # All contributions within 0.5% of the mean
    assert np.max(np.abs(rc - rc.mean())) / rc.mean() < 5e-3
    # Sum of RC == portfolio vol
    assert pytest.approx(rc.sum(), rel=1e-6) == res.portfolio_vol


# --------------------------------------------------------------------------- #
# Test: risk budget 60/40 -> resulting RC matches budget                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_risk_budget_60_40(cov_2_diff_vol, method):
    budget = pd.Series({"LO": 0.6, "HI": 0.4})
    res = risk_budget(cov_2_diff_vol, budget, method=method,
                      max_iter=2000, tol=1e-10)
    rc_norm = res.risk_contributions / res.risk_contributions.sum()
    assert pytest.approx(rc_norm["LO"], abs=1e-3) == 0.6
    assert pytest.approx(rc_norm["HI"], abs=1e-3) == 0.4
    # Targets stored in result are normalized to budget
    assert pytest.approx(res.target_contributions["LO"], abs=1e-12) == 0.6
    assert pytest.approx(res.target_contributions["HI"], abs=1e-12) == 0.4


# --------------------------------------------------------------------------- #
# Test: SQP converges                                                         #
# --------------------------------------------------------------------------- #
def test_sqp_converges(cov_5_diversified):
    res = risk_parity_weights(cov_5_diversified, method="sqp",
                              max_iter=2000, tol=1e-10)
    assert res.converged is True
    assert res.n_iterations >= 1
    assert res.method == "sqp"


# --------------------------------------------------------------------------- #
# Test: weights non-negative                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_weights_non_negative(cov_5_diversified, method):
    res = risk_parity_weights(cov_5_diversified, method=method,
                              max_iter=2000, tol=1e-10)
    assert (res.weights >= -1e-10).all()


# --------------------------------------------------------------------------- #
# Test: diagonal covariance -> weights ~ 1/vol_i                              #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["sqp", "cyclic"])
def test_diagonal_cov_inverse_vol_weights(cov_diag_3, method):
    """Closed form for diagonal Sigma + ERC: w_i ~ 1 / sigma_i."""
    res = risk_parity_weights(cov_diag_3, method=method,
                              max_iter=2000, tol=1e-10)
    vols = np.sqrt(np.diag(cov_diag_3.to_numpy()))
    inv_vol = 1.0 / vols
    expected = inv_vol / inv_vol.sum()
    actual = res.weights.to_numpy()
    assert np.max(np.abs(actual - expected)) < 1e-3


# --------------------------------------------------------------------------- #
# Misc validation tests                                                       #
# --------------------------------------------------------------------------- #
def test_unknown_method_raises(cov_2_equal_vol):
    with pytest.raises(ValueError, match="unknown method"):
        risk_parity_weights(cov_2_equal_vol, method="bogus")


def test_non_square_cov_raises():
    bad = pd.DataFrame(np.zeros((2, 3)),
                       index=["A", "B"], columns=["X", "Y", "Z"])
    with pytest.raises(ValueError, match="square"):
        risk_parity_weights(bad)


def test_mismatched_index_columns_raises():
    bad = pd.DataFrame([[1.0, 0.0], [0.0, 1.0]],
                       index=["A", "B"], columns=["X", "Y"])
    with pytest.raises(ValueError, match="index"):
        risk_parity_weights(bad)


def test_nan_cov_raises():
    bad = pd.DataFrame([[1.0, np.nan], [np.nan, 1.0]],
                       index=["A", "B"], columns=["A", "B"])
    with pytest.raises(ValueError, match="NaN"):
        risk_parity_weights(bad)


def test_non_positive_diagonal_raises():
    bad = pd.DataFrame([[0.0, 0.0], [0.0, 0.04]],
                       index=["A", "B"], columns=["A", "B"])
    with pytest.raises(ValueError, match="non-positive diagonal"):
        risk_parity_weights(bad)


def test_negative_budget_raises(cov_2_diff_vol):
    bad_budget = pd.Series({"LO": -0.5, "HI": 1.5})
    with pytest.raises(ValueError, match="strictly positive"):
        risk_budget(cov_2_diff_vol, bad_budget)


def test_risk_contributions_helper(cov_2_diff_vol):
    weights = pd.Series({"LO": 0.7, "HI": 0.3})
    rc = risk_contributions(weights, cov_2_diff_vol)
    arr = cov_2_diff_vol.to_numpy()
    w = weights.reindex(["LO", "HI"]).to_numpy()
    sigma_w = arr @ w
    sigma_p = float(np.sqrt(w @ sigma_w))
    expected = w * sigma_w / sigma_p
    assert np.allclose(rc.to_numpy(), expected)
    # Sum equals portfolio vol
    assert pytest.approx(rc.sum(), rel=1e-9) == sigma_p
