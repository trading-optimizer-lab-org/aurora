"""v35 checks: the profit factor, the daily book (gross, open positions, contributions by member) and the members'
table."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v35", "run_v35_under_test")


def test_pf(V) -> None:
    assert V.pf(np.array([0.2, -0.1, 0.1, -0.1])) == pytest.approx(1.5)
    assert V.pf(np.array([0.1])) == float("inf")


def test_daily_book(V) -> None:
    taken = [{"r": [0.1, -0.2], "w": 0.3, "i0": 1, "member": "a"},
             {"r": [0.05, 0.05, 0.05], "w": 0.2, "i0": 2, "member": "b"},
             {"r": [0.1, 0.1], "w": 0.3, "i0": 4, "member": "a"}]
    gross, n_open, by = V.daily_book(taken, 5)
    assert np.allclose(gross, [0, 0.3, 0.5, 0.2, 0.5])
    assert np.allclose(n_open, [0, 1, 2, 1, 2])
    assert np.allclose(by["a"], [0, 0.03, -0.06, 0, 0.03]) and np.allclose(by["b"], [0, 0, 0.01, 0.01, 0.01])


def test_members_table(V) -> None:
    taken = [{"member": "a", "net": 0.2, "contrib": 0.06, "w": 0.3}, {"member": "a", "net": -0.1, "contrib": -0.03,
                                                                       "w": 0.3}]
    t = V.members_table(taken)["a"]
    assert t["n"] == 2 and t["pf"] == pytest.approx(2.0) and t["contrib"] == pytest.approx(0.03)
