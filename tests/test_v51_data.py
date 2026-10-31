"""v51 data checks on a synthetic panel: the event superset and the symbol-days to fetch."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def M():
    from test_v24 import _script
    return _script("run_v51_data", "run_v51_data_under_test")


def _panel(T: int = 12, N: int = 3) -> dict:
    dates = pd.bdate_range("2018-01-01", periods=T)
    C = np.full((T, N), 2.0, np.float32)
    D = {"dates": dates, "cols": pd.Index(["AAA", "BBB", "CCC"][:N]), "C": C, "H": C * 1.05, "L": C * 0.95,
         "P1": np.full((T, N), 2.0), "DV1": np.full((T, N), 1e6), "valid": np.ones((T, N), bool),
         "valid1": np.ones((T, N), bool)}
    D["H"][5, 0] = 2.0 * 1.25  # +25% at the high: an event
    D["L"][7, 1] = 2.0 * 0.80  # -20% at the low: an event
    D["H"][8, 2] = 2.0 * 1.10  # +10%: not an event
    D["DV1"][7, 1] = 1e5  # too little dollar volume: the -20% day is out
    return D


def test_superset(M) -> None:
    D = _panel()
    ev = M.superset(D)
    assert ev[5, 0] and not ev[7, 1] and not ev[8, 2]
    assert ev.sum() == 1
    D["dates"] = pd.bdate_range("2017-12-01", periods=12)  # before 2018: nothing
    assert M.superset(D).sum() == 0


def test_need_days(M) -> None:
    D = _panel()
    ev = M.superset(D)
    need = M.need_days(D, ev, 3)
    days = [str(D["dates"][u].date()) for u in range(5, 9)]
    assert list(need) == days and all(need[d] == ["AAA"] for d in days)
    D["valid"][7, 0] = False
    assert len(M.need_days(D, ev, 3)) == 3
