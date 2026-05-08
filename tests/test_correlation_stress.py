"""Tests for correlation breakdown stress (Task L.4)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.validation.correlation_stress import (
    CorrelationStressResult,
    force_correlation,
    stress_correlation_breakdown,
    diversification_ratio,
    custom_correlation_scenario,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def returns_matrix():
    """3-asset returns DataFrame, modest cross-correlation."""
    set_global_seed(42)
    rng = np.random.default_rng(42)
    T = 600
    common = rng.normal(0.0003, 0.01, T)
    idx = pd.date_range("2015-01-01", periods=T, freq="B")
    cols = {}
    for sym, mu, sd in [("AAA", 0.0005, 0.012),
                        ("BBB", 0.0004, 0.013),
                        ("CCC", 0.0006, 0.011)]:
        idio = rng.normal(0.0, sd, T)
        cols[sym] = 0.5 * common + 0.5 * idio + mu
    return pd.DataFrame(cols, index=idx)


@pytest.fixture
def prices_dict():
    """3-asset price dict, used for stress orchestrator tests."""
    set_global_seed(42)
    rng = np.random.default_rng(42)
    T = 600
    common = rng.normal(0.0003, 0.01, T)
    idx = pd.date_range("2015-01-01", periods=T, freq="B")
    out = {}
    for sym, mu, sd, p0 in [("AAA", 0.0005, 0.012, 100.0),
                            ("BBB", 0.0004, 0.013, 80.0),
                            ("CCC", 0.0006, 0.011, 120.0)]:
        idio = rng.normal(0.0, sd, T)
        rets = 0.5 * common + 0.5 * idio + mu
        prices = p0 * np.cumprod(1.0 + rets)
        out[sym] = pd.Series(prices, index=idx, name=sym)
    return out


# --------------------------------------------------------------------------- #
# force_correlation                                                           #
# --------------------------------------------------------------------------- #
def test_force_corr_identity(returns_matrix):
    """Force corr=0: off-diagonal correlations of synthetic output near 0."""
    set_global_seed(42)
    synth = force_correlation(
        returns_matrix, target_corr=0.0, preserve_marginals=False,
        seed_name="t_id",
    )
    C = synth.corr().to_numpy()
    n = C.shape[0]
    off_diag = C[~np.eye(n, dtype=bool)]
    # With T=600 and target=0, sample off-diag should hover near 0 (|.|<0.15)
    assert np.max(np.abs(off_diag)) < 0.15, (
        f"identity-forced corr off-diag should be near 0; got max|c|={np.max(np.abs(off_diag)):.3f}"
    )


def test_force_corr_high(returns_matrix):
    """Force corr=0.95: off-diagonal correlations of synthetic output > 0.9."""
    set_global_seed(42)
    synth = force_correlation(
        returns_matrix, target_corr=0.95, preserve_marginals=False,
        seed_name="t_hi",
    )
    C = synth.corr().to_numpy()
    n = C.shape[0]
    off_diag = C[~np.eye(n, dtype=bool)]
    assert np.min(off_diag) > 0.9, (
        f"high-forced corr off-diag should exceed 0.9; got min={np.min(off_diag):.3f}"
    )


def test_force_corr_preserves_means_stds(returns_matrix):
    """preserve_marginals=True: per-asset mean and std match the original."""
    set_global_seed(42)
    synth = force_correlation(
        returns_matrix, target_corr=0.0, preserve_marginals=True,
        seed_name="t_pm",
    )
    for col in returns_matrix.columns:
        m_orig = returns_matrix[col].mean()
        s_orig = returns_matrix[col].std()
        m_synth = synth[col].mean()
        s_synth = synth[col].std()
        # Inverse-rank mapping uses the empirical sorted values directly,
        # so the mean and std must match exactly (it is a permutation).
        assert np.isclose(m_orig, m_synth, atol=1e-12), (
            f"{col} mean changed: {m_orig} vs {m_synth}"
        )
        assert np.isclose(s_orig, s_synth, atol=1e-12), (
            f"{col} std changed: {s_orig} vs {s_synth}"
        )


# --------------------------------------------------------------------------- #
# diversification_ratio                                                       #
# --------------------------------------------------------------------------- #
def test_diversification_ratio_independent_assets():
    """Independent assets, equal weight: DR > 1."""
    set_global_seed(0)
    rng = np.random.default_rng(0)
    T = 1500
    df = pd.DataFrame({
        "X": rng.normal(0.0, 0.01, T),
        "Y": rng.normal(0.0, 0.01, T),
        "Z": rng.normal(0.0, 0.01, T),
    })
    w = pd.Series({"X": 1 / 3, "Y": 1 / 3, "Z": 1 / 3})
    dr = diversification_ratio(df, w)
    # For 3 iid equal-vol equal-weight assets DR -> sqrt(3) ~ 1.73
    assert dr > 1.4, f"independent-asset DR should be >1.4, got {dr:.3f}"
    assert dr < 2.0


def test_diversification_ratio_perfect_correlation():
    """Perfectly correlated identical assets: DR ~ 1."""
    set_global_seed(1)
    rng = np.random.default_rng(1)
    base = rng.normal(0.0, 0.01, 1000)
    df = pd.DataFrame({"A": base, "B": base, "C": base})
    w = pd.Series({"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})
    dr = diversification_ratio(df, w)
    assert abs(dr - 1.0) < 1e-6, f"DR should ~1 for identical assets, got {dr}"


# --------------------------------------------------------------------------- #
# stress_correlation_breakdown                                                #
# --------------------------------------------------------------------------- #
def test_stress_correlation_breakdown_returns_3_regimes(prices_dict):
    """Returns dict with base, decorrelated, correlated metrics."""
    set_global_seed(42)
    T = len(next(iter(prices_dict.values())))
    weights = {s: np.full(T, 1.0 / 3.0) for s in prices_dict}

    res = stress_correlation_breakdown(
        strategy_factory=None,
        prices_dict=prices_dict,
        weights_dict=weights,
        ppy=252,
        seed_name="cs_test",
    )
    assert isinstance(res, CorrelationStressResult)
    assert isinstance(res.base_metrics, dict)
    assert isinstance(res.decorrelated_metrics, dict)
    assert isinstance(res.correlated_metrics, dict)
    assert res.custom_metrics is None
    assert isinstance(res.base_correlation, pd.DataFrame)
    assert res.base_correlation.shape == (3, 3)
    assert "calmar" in res.base_metrics
    assert "sharpe" in res.decorrelated_metrics
    assert "mdd" in res.correlated_metrics
    assert isinstance(res.diversification_ratio, float)
    assert res.diversification_ratio > 0


# --------------------------------------------------------------------------- #
# custom_correlation_scenario                                                 #
# --------------------------------------------------------------------------- #
def test_custom_correlation_scenario_basic(returns_matrix):
    """Apply a custom block correlation matrix; output respects it."""
    set_global_seed(42)
    cols = list(returns_matrix.columns)
    # Custom: high (0.8) between AAA-BBB, low (0.1) for CCC
    target = pd.DataFrame(
        [[1.0, 0.8, 0.1],
         [0.8, 1.0, 0.1],
         [0.1, 0.1, 1.0]],
        index=cols, columns=cols,
    )
    synth = custom_correlation_scenario(
        returns_matrix, target, preserve_marginals=False,
        seed_name="t_cc",
    )
    C = synth.corr()
    # AAA-BBB should be much higher than AAA-CCC
    assert C.loc["AAA", "BBB"] > 0.6
    assert C.loc["AAA", "CCC"] < 0.35
    assert C.loc["BBB", "CCC"] < 0.35


# --------------------------------------------------------------------------- #
# Reproducibility                                                             #
# --------------------------------------------------------------------------- #
def test_correlation_stress_target_corr_matches(returns_matrix):
    """Apply a custom target correlation matrix and verify the empirical
    correlation of the synthesized output matches it within 0.05.

    With Z standardized before the Cholesky multiply, the target C is applied
    to truly unit-variance inputs and the finite-sample drift between
    requested and realized correlations should be small.
    """
    set_global_seed(2026)
    cols = list(returns_matrix.columns)
    target = pd.DataFrame(
        [[1.00, 0.70, 0.30],
         [0.70, 1.00, 0.50],
         [0.30, 0.50, 1.00]],
        index=cols, columns=cols,
    )
    synth = custom_correlation_scenario(
        returns_matrix, target, preserve_marginals=False,
        seed_name="t_match",
    )
    C_emp = synth.corr().to_numpy()
    C_tar = target.to_numpy()
    diff = np.abs(C_emp - C_tar)
    assert diff.max() < 0.05, (
        f"empirical corr deviates from target by {diff.max():.3f}\n"
        f"target=\n{C_tar}\nempirical=\n{C_emp}"
    )


def test_reproducibility(returns_matrix):
    """Same seed -> identical synthetic matrix and metrics."""
    set_global_seed(42)
    a = force_correlation(
        returns_matrix, target_corr=0.5, preserve_marginals=True,
        seed_name="rep",
    )
    set_global_seed(42)
    b = force_correlation(
        returns_matrix, target_corr=0.5, preserve_marginals=True,
        seed_name="rep",
    )
    assert np.allclose(a.to_numpy(), b.to_numpy())
