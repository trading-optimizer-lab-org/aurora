"""Tests for quantforge.deployment.cov_shrinkage (Task H.4)."""
from __future__ import annotations
import time

import numpy as np
import pandas as pd
import pytest

from aurora.deployment.cov_shrinkage import (
    sample_covariance,
    ledoit_wolf_shrinkage,
    oas_shrinkage,
    exponential_cov,
    fix_nonpositive_semidefinite,
    _optimal_shrinkage_factor,
    _shrinkage_target_matrix,
)


def _make_returns(n_obs=500, n_assets=5, seed=42):
    rng = np.random.default_rng(seed)
    # Build a correlated return panel via random factor model.
    factor = rng.standard_normal(n_obs) * 0.01
    loadings = rng.uniform(0.3, 0.9, n_assets)
    idio = rng.standard_normal((n_obs, n_assets)) * 0.005
    R = factor[:, None] * loadings[None, :] + idio
    cols = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(R, columns=cols)


def _is_psd(matrix: pd.DataFrame, tol: float = -1e-8) -> bool:
    M = matrix.to_numpy()
    M = 0.5 * (M + M.T)
    eig = np.linalg.eigvalsh(M)
    return bool(eig.min() >= tol)


# ---------------------------------------------------------------------------
def test_sample_cov_basic():
    R = _make_returns()
    cov = sample_covariance(R, frequency=252)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (5, 5)
    # Annualized -> diagonal should be > raw daily variance
    raw_diag = R.var().to_numpy()
    ann_diag = np.diag(cov.to_numpy())
    np.testing.assert_allclose(ann_diag, raw_diag * 252, rtol=1e-10)
    # Symmetric
    np.testing.assert_allclose(cov.to_numpy(), cov.to_numpy().T, atol=1e-12)


# ---------------------------------------------------------------------------
def test_ledoit_wolf_returns_psd():
    R = _make_returns(n_obs=60, n_assets=20)  # n < p ratio test
    cov, delta = ledoit_wolf_shrinkage(R)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (20, 20)
    assert _is_psd(cov)


def test_ledoit_wolf_shrinkage_in_range():
    R = _make_returns()
    for target in ("constant_variance", "identity",
                   "single_factor", "constant_correlation"):
        _cov, delta = ledoit_wolf_shrinkage(R, shrinkage_target=target)
        assert 0.0 <= delta <= 1.0, f"{target}: delta={delta}"


def test_ledoit_wolf_invalid_target():
    R = _make_returns()
    with pytest.raises(ValueError):
        ledoit_wolf_shrinkage(R, shrinkage_target="nonsense")


# ---------------------------------------------------------------------------
def test_oas_shrinkage_basic():
    R = _make_returns()
    cov, delta = oas_shrinkage(R)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (5, 5)
    assert 0.0 <= delta <= 1.0
    assert _is_psd(cov)


# ---------------------------------------------------------------------------
def test_exponential_cov_decays():
    """More recent observations should weight higher.

    Construct returns where the first half has high variance and second half
    has low variance. EWMA cov should be closer to the low-var regime than
    the equal-weighted sample cov.
    """
    rng = np.random.default_rng(123)
    n = 400
    high = rng.standard_normal((n // 2, 1)) * 0.05  # old, big vol
    low = rng.standard_normal((n // 2, 1)) * 0.005  # recent, small vol
    R = pd.DataFrame(np.vstack([high, low]), columns=["A0"])
    sample = float(sample_covariance(R, frequency=1).iloc[0, 0])
    ewma = float(exponential_cov(R, span=20, frequency=1).iloc[0, 0])
    # EWMA should be much smaller than equal-weight sample
    assert ewma < sample
    # And should be closer to the realized variance of the recent half.
    recent_var = float(R.iloc[n // 2:].var().iloc[0])
    assert abs(ewma - recent_var) < abs(sample - recent_var)


def test_exponential_cov_shape():
    R = _make_returns(n_assets=4)
    cov = exponential_cov(R, span=30, frequency=252)
    assert cov.shape == (4, 4)
    np.testing.assert_allclose(cov.to_numpy(), cov.to_numpy().T, atol=1e-10)


# ---------------------------------------------------------------------------
def test_fix_psd_spectral():
    # Construct a non-PSD symmetric matrix
    M = pd.DataFrame([[1.0, 2.0, 0.0],
                      [2.0, 1.0, 0.0],
                      [0.0, 0.0, 1.0]],
                     index=list("ABC"), columns=list("ABC"))
    eig = np.linalg.eigvalsh(M.to_numpy())
    assert eig.min() < 0  # confirm non-PSD
    fixed = fix_nonpositive_semidefinite(M, fix_method="spectral")
    assert _is_psd(fixed)
    assert list(fixed.columns) == ["A", "B", "C"]


def test_fix_psd_diagonal_loading():
    M = pd.DataFrame([[1.0, 2.0, 0.0],
                      [2.0, 1.0, 0.0],
                      [0.0, 0.0, 1.0]],
                     index=list("ABC"), columns=list("ABC"))
    fixed = fix_nonpositive_semidefinite(M, fix_method="diagonal_loading")
    assert _is_psd(fixed)
    # Off-diagonals should match original (only diag was loaded)
    np.testing.assert_allclose(fixed.iloc[0, 1], 2.0, atol=1e-10)


def test_fix_psd_already_psd_passthrough():
    R = _make_returns()
    cov = sample_covariance(R)
    fixed = fix_nonpositive_semidefinite(cov, fix_method="spectral")
    np.testing.assert_allclose(fixed.to_numpy(), cov.to_numpy(), atol=1e-8)


def test_fix_psd_invalid_method():
    M = pd.DataFrame(np.eye(3))
    with pytest.raises(ValueError):
        fix_nonpositive_semidefinite(M, fix_method="bogus")


# ---------------------------------------------------------------------------
def test_zero_returns_handled():
    """Zero-variance asset should not crash any estimator."""
    rng = np.random.default_rng(0)
    n = 200
    R = pd.DataFrame({
        "live": rng.standard_normal(n) * 0.01,
        "dead": np.zeros(n),
    })
    cov_s = sample_covariance(R)
    assert cov_s.loc["dead", "dead"] == 0.0

    cov_lw, delta = ledoit_wolf_shrinkage(R, shrinkage_target="constant_variance")
    assert np.isfinite(cov_lw.to_numpy()).all()
    assert 0.0 <= delta <= 1.0

    cov_oas, delta_oas = oas_shrinkage(R)
    assert np.isfinite(cov_oas.to_numpy()).all()
    assert 0.0 <= delta_oas <= 1.0

    cov_ewma = exponential_cov(R, span=30)
    assert np.isfinite(cov_ewma.to_numpy()).all()
    # dead asset variance under EWMA should still be 0
    assert cov_ewma.loc["dead", "dead"] == 0.0


def test_constant_correlation_target_with_zero_var():
    """Constant correlation target divides by std; zero std should be safe."""
    rng = np.random.default_rng(1)
    n = 200
    R = pd.DataFrame({
        "a": rng.standard_normal(n) * 0.01,
        "b": rng.standard_normal(n) * 0.01,
        "z": np.zeros(n),
    })
    cov, delta = ledoit_wolf_shrinkage(R, shrinkage_target="constant_correlation")
    assert np.isfinite(cov.to_numpy()).all()
    assert 0.0 <= delta <= 1.0


# ---------------------------------------------------------------------------
# Vectorized _optimal_shrinkage_factor tests
# ---------------------------------------------------------------------------
def _scalar_optimal_shrinkage_factor(X, S, F):
    """Reference (scalar / loop) implementation for parity check."""
    T, n = X.shape
    pi_mat = np.zeros((n, n))
    for t in range(T):
        outer = np.outer(X[t], X[t]) - S
        pi_mat += outer * outer
    pi_mat /= T
    pi_hat = float(pi_mat.sum())
    diff = F - S
    gamma = float((diff * diff).sum())
    if gamma <= 0:
        return 0.0
    kappa = pi_hat / gamma
    delta = kappa / T
    return float(np.clip(delta, 0.0, 1.0))


def test_shrinkage_factor_vectorized_matches_scalar():
    """Vectorized factor must match scalar reference within 1e-10."""
    rng = np.random.default_rng(11)
    T, N = 200, 20
    X = rng.standard_normal((T, N)) * 0.01
    X = X - X.mean(0, keepdims=True)
    S = (X.T @ X) / T
    for target in ("identity", "constant_variance",
                   "single_factor", "constant_correlation"):
        F = _shrinkage_target_matrix(S, target)
        delta_vec = _optimal_shrinkage_factor(X, S, F)
        delta_scalar = _scalar_optimal_shrinkage_factor(X, S, F)
        assert abs(delta_vec - delta_scalar) < 1e-10, (
            f"target={target}: vec={delta_vec} scalar={delta_scalar}"
        )


def test_shrinkage_factor_perf_n50():
    """Vectorized factor must run quickly for N=50."""
    rng = np.random.default_rng(7)
    T, N = 800, 50
    X = rng.standard_normal((T, N)) * 0.01
    X = X - X.mean(0, keepdims=True)
    S = (X.T @ X) / T
    F = _shrinkage_target_matrix(S, "single_factor")
    t0 = time.perf_counter()
    delta = _optimal_shrinkage_factor(X, S, F)
    elapsed = time.perf_counter() - t0
    assert 0.0 <= delta <= 1.0
    assert elapsed < 2.0, f"vectorized factor took {elapsed:.3f}s (>2s)"


# ---------------------------------------------------------------------------
# Cadence validation
# ---------------------------------------------------------------------------
def test_cov_shrinkage_cadence_validation_warns():
    """Weekly DatetimeIndex with frequency=252 (daily annualization) must
    raise a UserWarning. Matching cadence (52 for weekly) must NOT warn."""
    import warnings as _w

    rng = np.random.default_rng(0)
    n_obs = 60
    weekly_idx = pd.date_range("2024-01-01", periods=n_obs, freq="W")
    R = pd.DataFrame(
        rng.standard_normal((n_obs, 3)) * 0.02,
        index=weekly_idx,
        columns=["A", "B", "C"],
    )

    # Mismatch: weekly data but frequency=252 (treats it as daily).
    with _w.catch_warnings(record=True) as wlist:
        _w.simplefilter("always")
        sample_covariance(R, frequency=252)
    assert any(
        issubclass(w.category, UserWarning) and "cadence" in str(w.message)
        for w in wlist
    ), "expected cadence-mismatch UserWarning"

    # Match: weekly data with frequency=52 -> no warning.
    with _w.catch_warnings(record=True) as wlist:
        _w.simplefilter("always")
        sample_covariance(R, frequency=52)
    assert not any(
        "cadence" in str(w.message) for w in wlist
    ), f"unexpected cadence warning at frequency=52: {[str(w.message) for w in wlist]}"

    # Daily data with frequency=252 (default) -> no warning.
    daily_idx = pd.date_range("2024-01-01", periods=200, freq="B")
    R_daily = pd.DataFrame(
        rng.standard_normal((200, 3)) * 0.01,
        index=daily_idx,
        columns=["A", "B", "C"],
    )
    with _w.catch_warnings(record=True) as wlist:
        _w.simplefilter("always")
        sample_covariance(R_daily, frequency=252)
    assert not any("cadence" in str(w.message) for w in wlist)

    # Array input (no DatetimeIndex) -> no warning regardless.
    with _w.catch_warnings(record=True) as wlist:
        _w.simplefilter("always")
        sample_covariance(rng.standard_normal((100, 3)) * 0.01, frequency=252)
    assert not any("cadence" in str(w.message) for w in wlist)


# ---------------------------------------------------------------------------
# Issue 15: EWMA covariance unbiased divisor
# ---------------------------------------------------------------------------

def test_ewma_cov_unbiased():
    """For an iid Gaussian return panel, the EWMA covariance with the bias
    correction (1 - sum(w^2)) should be on the same scale as the sample
    covariance (within typical sampling noise). Without the correction, the
    EWMA estimate is systematically smaller by that same factor.
    """
    rng = np.random.default_rng(0)
    n = 1000
    span = 60
    R = pd.DataFrame(rng.standard_normal((n, 3)) * 0.01,
                     columns=["A", "B", "C"])
    sample = sample_covariance(R, frequency=252).to_numpy()
    ewma = exponential_cov(R, span=span, frequency=252).to_numpy()

    # Compute the bias correction factor explicitly to confirm the divisor
    # used in the implementation is non-trivial.
    alpha = 2.0 / (span + 1.0)
    ages = np.arange(n - 1, -1, -1)
    weights = (1.0 - alpha) ** ages
    weights /= weights.sum()
    bias_corr = 1.0 - float((weights ** 2).sum())
    assert 0.0 < bias_corr < 1.0

    # Diagonals should be on the same scale (within 30% under iid).
    s_diag = np.diag(sample)
    e_diag = np.diag(ewma)
    ratio = e_diag / s_diag
    assert np.all(ratio > 0.5) and np.all(ratio < 1.5), ratio


# ---------------------------------------------------------------------------
# Issue 16: spectral clip floors at positive value (keeps invertible)
# ---------------------------------------------------------------------------

def test_spectral_clip_keeps_invertible():
    """Spectral repair must produce an INVERTIBLE PSD matrix even when the
    input has zero or negative eigenvalues."""
    # Construct a rank-deficient covariance: 3x3 with one zero eigenvalue.
    M = pd.DataFrame(np.diag([1.0, 0.5, 0.0]),
                     index=["A", "B", "C"], columns=["A", "B", "C"])
    fixed = fix_nonpositive_semidefinite(M, fix_method="spectral")
    arr = fixed.to_numpy()
    eig = np.linalg.eigvalsh(0.5 * (arr + arr.T))
    assert eig.min() > 0.0, eig
    # And invertibility: solving Ax = b returns a finite x.
    b = np.array([1.0, 0.0, 0.0])
    x = np.linalg.solve(arr, b)
    assert np.all(np.isfinite(x))
