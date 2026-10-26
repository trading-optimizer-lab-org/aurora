"""v39 checks: the grid, the trade volatility (known before the entry) and the cut (only lowers weights)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v39", "run_v39_under_test")


def test_grid(V) -> None:
    assert len(V.BOOKS) == len(set(V.BOOKS)) == 108 and len(V.JOBS) == 24
    assert (0.3, 0.5, 0.3, 0.2, 0.0) in V.BOOKS
    assert V.R38.MEMBER_SIZES is V.MEMBER_SIZES


def test_trade_vol(V) -> None:
    C = np.exp(np.cumsum(np.r_[0.0, np.tile([0.1, -0.1], 15)]))[:, None]
    assert np.isnan(V.trade_vol(C, 20, 0))
    assert V.trade_vol(C, 21, 0) == pytest.approx(0.1)
    C2 = C.copy()
    C2[25:] *= 5.0  # a jump on the entry session or later is not seen
    assert V.trade_vol(C2, 25, 0) == pytest.approx(0.1)
    assert np.isnan(V.trade_vol(C, 25, -1))


def test_cut_and_refs(V) -> None:
    rng = np.random.default_rng(1)
    calm = np.exp(np.cumsum(rng.normal(0, 0.01, 60)))
    wild = np.exp(np.cumsum(rng.normal(0, 0.04, 60)))
    C = np.c_[calm, wild]
    its = [{"member": "B:v19:DS1", "t": 50, "j": 0, "w": 0.3}, {"member": "B:v19:DS1", "t": 50, "j": 1, "w": 0.3}]
    dates = pd.date_range("2020-01-01", periods=60)
    refs = V.v_refs({("B:v19:DS1", 0.3): its}, C, dates)
    assert refs["B:v19:DS1"] == pytest.approx(np.mean([V.trade_vol(C, 50, 0), V.trade_vol(C, 50, 1)]))
    assert V.cut(its, 0.0, refs, C) is its
    out = V.cut(its, 1.0, refs, C)
    assert out[0]["w"] == pytest.approx(0.3) and out[1]["w"] < 0.3
    assert out[1]["w"] == pytest.approx(0.3 * refs["B:v19:DS1"] / V.trade_vol(C, 50, 1))
    assert V.cut(its, 0.5, refs, C)[1]["w"] > out[1]["w"]
    late = V.v_refs({("B:v19:DS1", 0.3): its}, C, pd.date_range("2023-01-01", periods=60))
    assert np.isnan(late["B:v19:DS1"])  # v_ref uses only 2018-2022 trades
    assert V.cut(its, 1.0, late, C)[1]["w"] == pytest.approx(0.3)
