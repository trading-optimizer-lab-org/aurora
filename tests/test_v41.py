"""v41 checks: the grid, the point-in-time multipliers (mean 1 over earlier trades) and the walk-forward choice."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v41", "run_v41_under_test")


def test_grid(V) -> None:
    assert len(V.VARIANTS) == 49 and V.VARIANTS[V.BASE_ID] == "base"
    assert V.name(V.VARIANTS.index(("gc", 1.5, "runup"))) == "gc x1.5 runup"
    assert V.R40.STOPS == (None,)


def test_raw(V) -> None:
    f = {("dil", "event"): np.array([1, 0, 1, 0], bool), ("dil", "runway"): np.array([1, 0, 0, 0], bool),
         ("dil", "so"): np.array([1, 0, 0, 1], bool), ("dil", "gc"): np.array([1, 0, 0, 0], bool)}
    assert V.raw(f, "event", 2.0).tolist() == [2.0, 1.0, 2.0, 1.0]
    assert V.raw(f, "score", 3.0).tolist() == [3.0, 1.0, 1.5, 1.5]


def test_multipliers(V, monkeypatch) -> None:
    monkeypatch.setattr(V, "MIN_PRIOR", 2)
    m_raw = np.array([2.0, 1.0, 2.0, 1.0, 2.0, 9.0])
    i0 = np.array([0, 1, 1, 2, 3, 2])
    scope = np.array([True, True, True, True, True, False])
    m = V.multipliers(m_raw, i0, scope)
    assert m[5] == 1.0  # out of scope
    assert m[0] == m[1] == m[2] == 1.0  # fewer than 2 trades entered before
    assert m[3] == pytest.approx(1.0 / (5 / 3))  # earlier trades: 2, 1, 2 (same-session trades not counted)
    assert m[4] == pytest.approx(2.0 / 1.5)


def test_apply_keeps_exposure(V) -> None:
    rng = np.random.default_rng(0)
    n = 400
    flag = rng.random(n) < 0.3
    f = {("dil", g): flag for g in ("event", "runway", "so", "gc", "any")}
    its = [{"i0": q, "w": 0.2, "member": "B:v19:DS1" if q % 2 else "B:v20:NS"} for q in range(n)]
    v = V.VARIANTS.index(("any", 2.0, "all"))
    w = np.array([it["w"] for it in V.apply(its, f, v)])
    late = np.arange(n) >= 200
    assert abs(w[late].mean() / 0.2 - 1) < 0.1 and w[late & flag].mean() > 0.2 > w[late & ~flag].mean()
    v2 = V.VARIANTS.index(("any", 2.0, "runup"))
    w2 = np.array([it["w"] for it in V.apply(its, f, v2)])
    assert np.all(w2[::2] == 0.2)  # NS out of scope
    assert V.apply(its, f, V.BASE_ID) is its


def test_walk_forward(V) -> None:
    G = np.array([[0.1, 0.2, 0.0], [0.5, 0.0, 0.0], [0.9, 0.9, 0.0]])
    DD = np.array([[-0.3, -0.3, 0], [-0.2, -0.2, 0], [-0.5, -0.1, 0]])
    picks = V.walk_forward(G, DD, [2018, 2019, 2020])
    assert picks == {2018: 0, 2019: 1, 2020: 1}  # 2 grows most but its drawdown is deeper than the base book's
