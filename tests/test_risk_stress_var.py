"""Tests for StressVaR (Basel III SVaR)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.risk.stress_var import StressVaR


def _make_returns(seed: int, start: str = "2007-01-01", n: int = 4000) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="B")
    # Inject high vol during 2008-2009
    vol = np.where((idx >= pd.Timestamp("2008-09-01")) & (idx <= pd.Timestamp("2009-08-31")),
                   0.04, 0.01)
    r = rng.normal(0.0, vol)
    return pd.Series(r, index=idx)


def test_svar_2008_window():
    s = _make_returns(7)
    sv = StressVaR(window="2008", confidence=0.99, holding_period=10)
    val = sv.compute(s)
    assert val > 0


def test_svar_invalid_confidence():
    with pytest.raises(ValueError):
        StressVaR(confidence=0.0)
    with pytest.raises(ValueError):
        StressVaR(confidence=1.0)


def test_svar_invalid_window():
    with pytest.raises(ValueError):
        StressVaR(window="bogus")


def test_svar_custom_window_requires_dates():
    with pytest.raises(ValueError):
        StressVaR(window="custom")


def test_svar_invalid_method():
    with pytest.raises(ValueError):
        StressVaR(method="bayesian")


def test_svar_invalid_holding_period():
    with pytest.raises(ValueError):
        StressVaR(holding_period=0)


def test_svar_parametric_method():
    s = _make_returns(11)
    sv = StressVaR(window="2008", method="parametric")
    val = sv.compute(s)
    assert val > 0


def test_svar_allocate_simplex():
    rng = np.random.default_rng(13)
    idx = pd.date_range("2007-01-01", periods=4000, freq="B")
    df = pd.DataFrame({
        "A": rng.normal(0.0, 0.01, 4000),
        "B": rng.normal(0.0, 0.02, 4000),
        "C": rng.normal(0.0, 0.04, 4000),
    }, index=idx)
    sv = StressVaR(window="2008")
    w = sv.allocate(df)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert np.all(w >= 0)


def test_svar_allocate_validates_df():
    sv = StressVaR(window="2008")
    with pytest.raises(TypeError):
        sv.allocate(np.array([[1.0, 2.0]]))


def test_svar_custom_window_works():
    rng = np.random.default_rng(17)
    idx = pd.date_range("2019-01-01", periods=1500, freq="B")
    s = pd.Series(rng.normal(0.0, 0.02, 1500), index=idx)
    sv = StressVaR(window="custom",
                   custom_start="2020-02-15",
                   custom_end="2021-02-15")
    val = sv.compute(s)
    assert val > 0
