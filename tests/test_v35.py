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


def test_grid(V) -> None:
    assert len(V.BOOKS) == len(set(V.BOOKS)) == 384 and len(V.UNITS) == 24
    assert all(s in V.SIZES for sc in V.SCHEDULES for s in sc)


def test_schedule_uses_s1_below_10k(V) -> None:
    per = {0.2: np.arange(5)[:, None] * np.ones((5, 3)), 0.4: 10 + np.arange(5)[:, None] * np.ones((5, 3))}
    Rb = V.schedule_R(per.__getitem__, (0.2, 0.4))
    assert np.allclose(Rb[:, 0], [0, 1, 12, 13, 14])  # levels $2.5k and $5k from s1, $10k+ from s2


def test_pick_and_target(V) -> None:
    a = {"early": {"med": 20000, "p_ruin": 0.03}, "all": {"med": 40000, "p_ruin": 0.02}}
    b = {"early": {"med": 15000, "p_ruin": 0.02}, "all": {"med": 31000, "p_ruin": 0.02}}
    c = {"early": {"med": 12000, "p_ruin": 0.01}, "all": {"med": 29000, "p_ruin": 0.01}}
    assert V.pick([a, b, c]) is b and V.met(b) and not V.met(c) and not V.met(None)
    assert V.pick([a]) is None


def test_ladder_halves(V, monkeypatch) -> None:
    seen = []

    def fake(name, years, level, var, spread, fee, hot):
        seen.append((var, V.R33.CAP))
        return [{"prio": 2.0, "w": V.R33.CAP}]
    monkeypatch.setattr(V.R33, "member_items", fake)
    rows = [{"fam": "B:v19:DS1", "name": "x", "year": 2020, "var": [0.2, None, False]},
            {"fam": "B:v20:NS", "name": "y", "year": 2020, "var": [None, None, False]}]
    its = V.book_items(rows, 5000.0, 0.3, (0.2, 0.4))
    assert seen == [((0.2, None, False), 0.15), ((0.4, None, False), 0.15), ((None, None, False), 0.3)]
    assert [it.get("tranche") for it in its] == [0, 1, None] and its[1]["prio"] < its[0]["prio"]
    seen.clear()
    V.book_items(rows, 5000.0, 0.3, None)
    assert seen == [((0.2, None, False), 0.3), ((None, None, False), 0.3)]


def test_stress_jobs(V) -> None:
    r = {"book": [[0.3, 0.4], 1, 2]}
    jobs = V.stress_jobs({"choice": r, "top": [r, {"book": [[0.2, 0.3], 0, 0]}]})
    assert len(jobs) == 6 and jobs[0] == (((0.3, 0.4), 1, 2), "hot5")


def test_threshold_rows(V) -> None:
    parts = {li: {"free": np.full(3, li), "paid": np.full(3, 10 + li)} for li in range(2, 5)}
    parts.update({li: {"free": np.full(3, li)} for li in range(2)})
    assert np.allclose(V.threshold_R(parts, 10_000.0)[:, 0], [0, 1, 12, 13, 14])
    assert np.allclose(V.threshold_R(parts, 25_000.0)[:, 0], [0, 1, 2, 13, 14])
    assert np.allclose(V.threshold_R(parts, None)[:, 0], [0, 1, 2, 3, 4])


def test_data_fee_only_above_threshold(V) -> None:
    R = np.zeros((5, 1))
    idx = np.zeros((2, 21), int)
    lo, _ = V.paths_fee(R, idx, 10_000.0, e0=5_000.0)
    hi, _ = V.paths_fee(R, idx, 10_000.0, e0=12_000.0)
    assert lo[0] == pytest.approx(5_000 - 21 * V.FIXED * 12 / 252)
    assert hi[0] == pytest.approx(12_000 - 21 * V.PAID_FIXED * 12 / 252)
