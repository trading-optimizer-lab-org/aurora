"""Tests for the v11 combination helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import v11


def test_to_trading_compounds_weekend_returns_into_monday():
    cal = pd.DatetimeIndex(["2021-01-08", "2021-01-11"])
    r = pd.Series([0.01, 0.02, 0.03, 0.04], index=pd.DatetimeIndex(["2021-01-08", "2021-01-09", "2021-01-10",
                                                                     "2021-01-11"]))
    out = v11.to_trading(r, cal)
    assert np.isclose(out.iloc[0], 0.01) and np.isclose(out.iloc[1], 1.02 * 1.03 * 1.04 - 1)


def test_ivol_weights_favour_the_calmer_stream():
    rng = np.random.default_rng(0)
    R = pd.DataFrame({"a": rng.normal(0, 0.01, 500), "b": rng.normal(0, 0.03, 500)})
    w = v11.ivol_weights(R)
    assert np.isclose(w.sum(), 1) and w["a"] > 2 * w["b"]


def test_greedy_adds_an_uncorrelated_stream_and_stops():
    idx = pd.bdate_range("2016-01-04", "2020-12-31")
    rng = np.random.default_rng(1)
    R = pd.DataFrame({"a": rng.normal(0.001, 0.01, len(idx)), "b": rng.normal(0.001, 0.01, len(idx))}, index=idx)
    R["a_copy"] = R["a"]
    chosen, path = v11.greedy(R, pd.Series(0.0, index=idx))
    assert set(chosen) <= {"a", "b", "a_copy"} and "b" in chosen and path == sorted(path)
