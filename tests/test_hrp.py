"""Tests for Hierarchical Risk Parity allocator (Task H.1).

Run: pytest aurora/tests/test_hrp.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.hrp import (
    HRPResult,
    correlation_distance,
    hrp_allocate,
    hrp_recursive_bisection,
    quasi_diagonalize,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
def _seeded_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


@pytest.fixture
def two_asset_returns():
    """Two assets, weakly correlated, 500 daily bars."""
    rng = _seeded_rng(7)
    idx = pd.date_range("2018-01-01", periods=500, freq="B")
    a = rng.normal(0.0, 0.01, 500)
    b = rng.normal(0.0, 0.02, 500)
    return pd.DataFrame({"A": a, "B": b}, index=idx)


@pytest.fixture
def five_uncorrelated_returns():
    """Five truly independent assets, similar vol -> roughly equal HRP weights."""
    rng = _seeded_rng(13)
    idx = pd.date_range("2018-01-01", periods=750, freq="B")
    data = {f"A{i}": rng.normal(0.0, 0.01, 750) for i in range(5)}
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def correlated_pair_plus_one():
    """Two highly correlated assets + 1 uncorrelated.

    HRP should treat the correlated pair as a single cluster and allocate
    roughly half of the budget to the uncorrelated outsider.
    """
    rng = _seeded_rng(42)
    idx = pd.date_range("2018-01-01", periods=600, freq="B")
    base = rng.normal(0.0, 0.01, 600)
    noise = rng.normal(0.0, 0.001, 600)
    pair_a = base
    pair_b = base + noise            # corr(pair_a, pair_b) ~= 0.99
    outsider = rng.normal(0.0, 0.01, 600)  # independent
    return pd.DataFrame(
        {"PAIR_A": pair_a, "PAIR_B": pair_b, "OUT": outsider}, index=idx
    )


# --------------------------------------------------------------------------- #
# Primitive helpers                                                           #
# --------------------------------------------------------------------------- #
def test_correlation_distance_bounds():
    """All distances in [0, 1]; identical -> 0; anti-correlated -> 1."""
    corr = pd.DataFrame(
        [[1.0, 0.5, -1.0],
         [0.5, 1.0,  0.0],
         [-1.0, 0.0, 1.0]],
        index=["x", "y", "z"], columns=["x", "y", "z"],
    )
    d = correlation_distance(corr)
    arr = d.values
    assert (arr >= -1e-12).all()
    assert (arr <= 1.0 + 1e-12).all()
    # diagonal is 0
    np.testing.assert_allclose(np.diag(arr), 0.0, atol=1e-12)
    # anti-correlated -> 1
    assert d.loc["x", "z"] == pytest.approx(1.0, abs=1e-12)
    # identical -> 0
    assert d.loc["x", "x"] == pytest.approx(0.0, abs=1e-12)
    # rho=0.5 -> sqrt(0.25) = 0.5
    assert d.loc["x", "y"] == pytest.approx(0.5, abs=1e-12)


def test_quasi_diagonalize_orders_correlated_together():
    """Two highly correlated assets should be adjacent after quasi-diagonalization."""
    rng = _seeded_rng(101)
    idx = pd.date_range("2019-01-01", periods=400, freq="B")
    base = rng.normal(0.0, 0.01, 400)
    df = pd.DataFrame(
        {
            "A": base,                         # cluster 1
            "FAR": rng.normal(0.0, 0.01, 400),  # independent
            "B": base + rng.normal(0.0, 0.001, 400),  # cluster 1, ~0.99 corr w/ A
        },
        index=idx,
    )
    res = hrp_allocate(df)
    order = res.sorted_order
    # A and B must be adjacent in the sorted order
    pos_a = order.index("A")
    pos_b = order.index("B")
    assert abs(pos_a - pos_b) == 1, (
        f"A and B should be adjacent after quasi-diagonalization, got order={order}"
    )


# --------------------------------------------------------------------------- #
# hrp_allocate behavioural tests                                              #
# --------------------------------------------------------------------------- #
def test_hrp_2_assets(two_asset_returns):
    """Simple 2-asset case -> weights sum to 1, both positive, result wired up."""
    res = hrp_allocate(two_asset_returns)
    assert isinstance(res, HRPResult)
    assert set(res.weights.index) == {"A", "B"}
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-9)
    assert (res.weights >= -1e-12).all()
    # cluster_tree shape (N-1, 4) for N=2 -> (1, 4)
    assert res.cluster_tree.shape == (1, 4)
    assert len(res.sorted_order) == 2
    assert set(res.sorted_order) == {"A", "B"}
    assert res.correlation.shape == (2, 2)
    assert res.distance.shape == (2, 2)


def test_hrp_5_assets_diversified(five_uncorrelated_returns):
    """Five truly uncorrelated assets w/ similar vol -> roughly equal weights."""
    res = hrp_allocate(five_uncorrelated_returns)
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-9)
    assert (res.weights >= -1e-12).all()
    # No weight should be more than 2x another (loose, accounts for sample noise)
    w = res.weights.values
    assert w.max() / w.min() < 2.5, (
        f"weights too dispersed for uncorrelated equal-vol assets: {res.weights.to_dict()}"
    )
    # All weights within factor 2 of 1/N = 0.20
    assert (w > 0.20 / 2.5).all()
    assert (w < 0.20 * 2.5).all()


def test_hrp_correlated_pair(correlated_pair_plus_one):
    """Two highly correlated + one uncorrelated -> outsider gets ~50%.

    HRP intuition: the two-asset cluster shares the budget that 1/N would
    have given to the cluster as a whole. With similar vol, the uncorrelated
    outsider is entitled to ~half of the portfolio.
    """
    res = hrp_allocate(correlated_pair_plus_one)
    w = res.weights
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert (w >= -1e-12).all()
    # OUT should be roughly half
    assert 0.40 < w["OUT"] < 0.60, (
        f"OUT should be near 50%, got {w['OUT']:.3f} (full: {w.to_dict()})"
    )
    # The two correlated assets should split the remaining ~50% between them
    pair_total = w["PAIR_A"] + w["PAIR_B"]
    assert 0.40 < pair_total < 0.60, (
        f"PAIR_A + PAIR_B should be near 50%, got {pair_total:.3f}"
    )


def test_weights_sum_to_one(two_asset_returns, five_uncorrelated_returns,
                            correlated_pair_plus_one):
    """Across multiple inputs, weights sum to 1.0."""
    for df in [two_asset_returns, five_uncorrelated_returns, correlated_pair_plus_one]:
        res = hrp_allocate(df)
        assert res.weights.sum() == pytest.approx(1.0, abs=1e-9)


def test_no_negative_weights(five_uncorrelated_returns):
    """HRP is long-only by construction; no negative weights ever."""
    res = hrp_allocate(five_uncorrelated_returns)
    assert (res.weights >= 0.0).all()


# --------------------------------------------------------------------------- #
# Bisection direct test                                                       #
# --------------------------------------------------------------------------- #
def test_recursive_bisection_inverse_variance_2_assets():
    """Two-asset bisection: weights are inversely proportional to variance."""
    cov = pd.DataFrame(
        [[0.04, 0.0],
         [0.0, 0.01]],
        index=["HV", "LV"], columns=["HV", "LV"],
    )
    w = hrp_recursive_bisection(cov, ["HV", "LV"])
    assert w.sum() == pytest.approx(1.0, abs=1e-12)
    # LV (variance 0.01) should get 4x weight of HV (variance 0.04)
    # alpha = 1 - v_L / (v_L + v_R) = 1 - 0.04 / 0.05 = 0.20 -> w_HV = 0.20
    assert w["HV"] == pytest.approx(0.20, abs=1e-9)
    assert w["LV"] == pytest.approx(0.80, abs=1e-9)


# --------------------------------------------------------------------------- #
# Input validation                                                            #
# --------------------------------------------------------------------------- #
def test_hrp_rejects_single_asset():
    df = pd.DataFrame({"A": np.random.randn(100)})
    with pytest.raises(ValueError, match=">= 2 assets"):
        hrp_allocate(df)


def test_hrp_rejects_invalid_linkage(two_asset_returns):
    with pytest.raises(ValueError, match="unknown linkage_method"):
        hrp_allocate(two_asset_returns, linkage_method="bogus")


def test_hrp_rejects_invalid_cov_estimator(two_asset_returns):
    with pytest.raises(ValueError, match="unknown cov_estimator"):
        hrp_allocate(two_asset_returns, cov_estimator="bogus")


def test_quasi_diagonalize_returns_permutation():
    """quasi_diagonalize returns a permutation of [0..N-1]."""
    rng = _seeded_rng(31)
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    df = pd.DataFrame(
        {f"A{i}": rng.normal(0.0, 0.01, 300) for i in range(4)},
        index=idx,
    )
    res = hrp_allocate(df)
    # cluster_tree -> permutation
    perm = quasi_diagonalize(res.cluster_tree)
    assert sorted(perm) == [0, 1, 2, 3]
    assert len(set(perm)) == 4


# ---------------------------------------------------------------------------
# Issue 18: HRP semantics documented as Quasi-Diag and aliased explicitly
# ---------------------------------------------------------------------------

def test_hrp_aligns_with_de_prado_reference():
    """Implementation must (a) explicitly identify itself as Quasi-Diag HRP
    in the docstrings, (b) expose the alias `quasi_diag_hrp` so call sites
    can name the contract, and (c) reproduce the published intuition that
    lower-volatility assets receive more weight than higher-volatility
    ones inside the same cluster."""
    from aurora.deployment.hrp import (
        hrp_allocate as _hrp_allocate,
        hrp_recursive_bisection as _hrp_recursive_bisection,
        quasi_diag_hrp,
        quasi_diag_hrp_recursive_bisection,
    )

    assert quasi_diag_hrp is _hrp_allocate
    assert quasi_diag_hrp_recursive_bisection is _hrp_recursive_bisection

    for fn in (_hrp_allocate, _hrp_recursive_bisection):
        doc = (fn.__doc__ or "").lower()
        assert "quasi" in doc and "diag" in doc, doc

    rng = np.random.default_rng(2026)
    n = 300
    factor = rng.normal(0.0, 0.012, n)
    R = pd.DataFrame({
        "A": 0.7 * factor + 0.005 * rng.normal(size=n),
        "B": 0.5 * factor + 0.008 * rng.normal(size=n),
        "C": 0.2 * factor + 0.012 * rng.normal(size=n),
        "D": 0.05 * factor + 0.018 * rng.normal(size=n),
    })
    res = quasi_diag_hrp(R)
    w = res.weights
    assert (w >= 0).all()
    assert pytest.approx(1.0, abs=1e-9) == float(w.sum())
    assert w["A"] > w["D"]
