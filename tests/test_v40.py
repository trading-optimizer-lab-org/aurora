"""v40 checks: the grid, the exits (consistent with v31's position_days), the flags, the weights, the smoothing and
the walk-forward choice."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v40", "run_v40_under_test")


def test_grid(V) -> None:
    assert V.NV == 5_174_400 and V.SHAPE == (25, 7, 4, 11, 7, 4, 3, 2, 4)
    assert V.decode(V.BASE_ID) == V.BASE and V.name(V.BASE_ID) == "base book"
    assert "stop 0.3" in V.name(int(np.ravel_multi_index((0, 0, 0, 0, 0, 1, 0, 0, 2), V.SHAPE)))


def _bars():
    C = np.array([10, 10, 9, 12, 6, 6], float)[:, None]
    O = np.array([10, 10, 10, 10, 11, 6], float)[:, None]
    H = np.array([10, 10, 12, 14, 11, 6], float)[:, None]
    L = np.array([10, 10, 9, 8.5, 5.5, 6], float)[:, None]
    return O, H, L, C


def _item():
    return {"side": -1, "member": "B:v19:DS1", "i0": 2, "t": 2, "j": 0, "entry": 10.0, "raw0": 0.1,
            "r": np.array([0.09, -0.3, 0.6]), "w": 0.2, "price": 10.0}


def test_exit_path(V) -> None:
    O, H, L, C = _bars()
    it = _item()
    assert V.exit_path(it, None, None, None, O, H, L, C) is None
    r, raw0 = V.exit_path(it, 0.3, None, None, O, H, L, C)  # stop 13 hit on day 1 (high 14)
    assert r == pytest.approx([0.09, -0.4]) and raw0 == pytest.approx(0.1)
    r, _ = V.exit_path(it, None, 0.3, None, O, H, L, C)  # target 7 hit on day 2 (low 5.5)
    assert r == pytest.approx([0.09, -0.3, 0.5])
    r, _ = V.exit_path(it, None, None, 2, O, H, L, C)
    assert r == pytest.approx([0.09, -0.3])
    r, raw0 = V.exit_path(it, 0.15, None, None, O, H, L, C)  # the entry session's high 12 reaches 11.5
    assert r == pytest.approx([-0.16]) and raw0 == pytest.approx(-0.15)
    assert V.exit_path({**it, "member": "B:v20:NS"}, 0.3, None, None, O, H, L, C) is None
    D = {"O": O, "H": H, "L": L, "C": C}
    for st, tg, hd in ((0.3, None, None), (None, 0.3, None), (0.15, None, None), (None, None, 2)):
        r, raw0 = V.exit_path(it, st, tg, hd, O, H, L, C)
        pd_ = V.R35.R31.position_days([{**it, "r": r, "raw0": raw0}], D, len(C))  # its checks pass
        assert pd_["cl"].sum() == pytest.approx(0.2 * r.sum())


def test_flags(V) -> None:
    m = np.r_[np.zeros(200), np.ones(100) * 5.0]
    hi, lo = V.pct_flags(m, 0.9)
    assert not hi[:126].any() and hi[200] and not lo[200]
    dates = pd.bdate_range("2020-03-01", "2020-07-10")
    qe = V.quarter_end(dates)
    assert qe[dates.get_loc(pd.Timestamp("2020-03-31"))] and not qe[dates.get_loc(pd.Timestamp("2020-03-24"))]
    assert qe.sum() == 10  # March and June; the July quarter is not over


def test_weights_and_apply(V) -> None:
    f = {"n": 3, ("reg", "runners", 0.8): np.array([True, False, False]), "cluster": np.array([0, 12, 3]),
         "june": np.array([False, False, True]), "qend": np.zeros(3, bool),
         ("dil", "event"): np.array([True, False, False]), ("crowd", "si15"): np.array([False, True, False])}
    v = list(V.BASE)
    assert V.weights(f, tuple(v)).tolist() == [1.0, 1.0, 1.0]
    v[0] = V.REGIME.index(("runners", 0.8, "half"))
    v[1] = V.CLUSTER.index((10, "skip"))
    v[2] = V.CALENDAR.index("june")
    v[3] = V.DILUTION.index(("event", "boost"))
    v[4] = V.CROWD.index(("si15", "half"))
    v[8] = V.SCALES.index(0.8)
    assert V.weights(f, tuple(v)) == pytest.approx([0.8 * 0.5 * 1.5, 0.0, 0.0])
    v2 = list(V.BASE)
    v2[3] = V.DILUTION.index(("event", "cut"))
    assert V.weights(f, tuple(v2)) == pytest.approx([1.0, 0.5, 0.5])
    its = [{"w": 0.2, "r": np.zeros(2)} for _ in range(3)]
    ex = {"n": 3, **{k: f[k] for k in f if k != "n"}, ("exit", 0.3, None, None): {1: (np.ones(1), 0.5)}}
    vid = int(np.ravel_multi_index(tuple(V.BASE[:5]) + (1, 0, 0, V.BASE[8]), V.SHAPE))
    out = V.apply(its, ex, vid)
    assert [o["w"] for o in out] == [0.2] * 3 and out[1]["raw0"] == 0.5 and "raw0" not in out[0]


def test_smooth_and_walk_forward(V, monkeypatch) -> None:
    monkeypatch.setattr(V, "SHAPE", (3, 2))
    G = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    sm = V.smooth(G, np.ones(6, bool))
    # variant (0, 0): neighbours (1, 0), (2, 0), (0, 1) -> values 3, 5, 2
    assert sm[0] == pytest.approx(0.5 * 1 + 0.5 * (3 + 5 + 2) / 3)
    monkeypatch.setattr(V, "BASE_ID", 0)
    Gy = np.array([[0.1, 0.0], [0.5, 0.0], [0.2, 0.0], [0.9, 0.0], [0.3, 0.0], [0.4, 0.0]])
    DD = np.array([[-0.3, 0], [-0.2, 0], [-0.3, 0], [-0.5, 0], [-0.1, 0], [-0.2, 0]])
    picks = V.walk_forward(Gy, DD, [2018, 2019])
    assert picks[2018] == 0 and picks[2019] != 3  # 3 has the best growth but a deeper drawdown than the base
