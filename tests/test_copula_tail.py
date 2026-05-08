"""Tests for CopulaTailDependence."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.validation.copula_tail import CopulaTailDependence


@pytest.fixture
def returns_df():
    set_global_seed(42)
    rng = np.random.default_rng(0)
    T = 500
    common = rng.normal(0, 0.01, T)
    a = 0.6 * common + 0.4 * rng.normal(0, 0.01, T)
    b = 0.6 * common + 0.4 * rng.normal(0, 0.01, T)
    idx = pd.date_range("2015-01-01", periods=T, freq="B")
    return pd.DataFrame({"AAA": a, "BBB": b}, index=idx)


def test_gaussian_basic(returns_df):
    res = CopulaTailDependence(family="gaussian").run(returns_df)
    assert res.n_obs == len(returns_df)
    assert -1.0 <= res.rho <= 1.0
    # Gaussian copula: tail dependence is exactly 0
    assert res.lambda_lower == 0.0
    assert res.lambda_upper == 0.0


def test_student_t_has_tail_dependence(returns_df):
    res = CopulaTailDependence(family="student_t", df_t=4.0).run(returns_df)
    assert res.lambda_lower > 0.0
    assert res.lambda_upper > 0.0
    # Symmetric
    assert abs(res.lambda_lower - res.lambda_upper) < 1e-9


def test_clayton_lower_only(returns_df):
    res = CopulaTailDependence(family="clayton").run(returns_df)
    assert res.theta_clayton > 0.0
    assert res.lambda_lower > 0.0
    # Clayton has zero upper tail dependence by construction
    assert res.lambda_upper == 0.0


def test_invalid_family_raises(returns_df):
    with pytest.raises(ValueError):
        CopulaTailDependence(family="bad").run(returns_df)
    with pytest.raises(ValueError):
        CopulaTailDependence(tail_quantile=0.6).run(returns_df)
