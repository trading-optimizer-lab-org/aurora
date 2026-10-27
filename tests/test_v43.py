"""v43 checks: the grid, the minute fills, a trade walked on minutes (stop, close, scale-out, delay, flat time), the
broker's minute liquidation and the walk-forward choice."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v43", "run_v43_under_test")


def test_grid(V) -> None:
    assert V.NR == 3600 and V.NU == 115_200
    assert V.rule_of(V.BASE_RULE) == (0, 1.0, "hold", None, None, 1.0)
    assert len(V.FILLS) * len(V.PARTS) * len(V.LIQS) * len(V.EFILLS) == 96


def _B(n: int = 960) -> dict:
    B = {k: np.full(n, np.nan) for k in ("o", "h", "l", "c", "v", "vw")}
    return B


def _bar(B: dict, s: int, o, h, lo, c, v=1000.0, vw=None) -> None:
    for k, x in (("o", o), ("h", h), ("l", lo), ("c", c), ("v", v), ("vw", c if vw is None else vw)):
        B[k][s] = x


def test_market_and_limit(V, monkeypatch) -> None:
    monkeypatch.setattr(V.v19, "SLIP", 0.25)
    B = _B()
    _bar(B, 600, 10, 13, 10, 12)
    _bar(B, 601, 12.5, 14, 12, 13, v=100, vw=13.2)
    _bar(B, 610, 11, 11.5, 10.5, 11, v=100)
    f = V.market(B, 600, V.LAST, 12.0, "slip", 1000, None, (V.LAST, 9.0))
    assert f == [(600, 1.0, pytest.approx(12.25))]
    assert V.market(B, 600, V.LAST, 12.0, "next_open", 1000, None, (V.LAST, 9.0)) == [(601, 1.0, 12.5)]
    assert V.market(B, 600, V.LAST, 12.0, "next_vwap", 1000, None, (V.LAST, 9.0))[0][2] == pytest.approx(13.2)
    assert V.market(B, 600, V.LAST, 12.0, "next_high", 1000, None, (V.LAST, 9.0))[0][2] == 14
    f = V.market(B, 600, V.LAST, 12.0, "next_open", 100, 0.10, (V.LAST, 9.0))  # 10 shares a bar of 100
    assert [s for s, _, _ in f] == [601, 610, V.LAST] and sum(p for _, p, _ in f) == pytest.approx(1.0)
    assert f[0][1] == pytest.approx(0.1) and f[-1][2] == 9.0
    g = V.limit(B, 601, V.LAST, 11.0, 1000, None, (V.LAST, 9.0))
    assert g == [(610, 1.0, 11.0)]


def _world(V, C: list[float], bars: dict) -> None:
    T = len(C)
    C = np.array(C, float)[:, None]
    V._G["D"] = {"O": C.copy(), "H": C * 1.05, "L": C * 0.95, "C": C, "F": np.ones((T, 1)),
                 "new": np.zeros((T, 1), bool), "dates": pd.bdate_range("2020-01-01", periods=T),
                 "cols": pd.Index(["X"])}
    V._G["bars"] = bars
    V._G["tl"] = {}


def _flat(price: float) -> tuple:
    m = np.arange(330, 720)
    p = np.full(len(m), price)
    return (m, p, p, p, p, np.full(len(m), 1e6), p)


def _meta(**kw) -> dict:
    m = {"kind": "open", "stop": 12.0, "hold": "d1", "scale": "all", "cat": np.nan, "target": "none",
         "ext": "none", "rally": "none", "lim": np.nan}
    return {**m, **kw}


IT = {"t": 1, "j": 0, "side": -1, "entry": 10.0, "w": 0.1, "price": 10.0}
RULE = (0, 1.0, "hold", None, None, 1.0)


def test_replay_open(V, monkeypatch) -> None:
    monkeypatch.setattr(V.v19, "SLIP", 0.25)
    b = list(_flat(10.0))
    k = 400 - 330
    b[2] = b[2].copy()
    b[2][k] = 13.0  # a high of 13 at 10:40
    b[1] = b[1].copy()
    b[1][k + 1] = 12.5
    _world(V, [10, 9, 9], {(1, 0): tuple(b)})
    V._G["D"]["C"][1, 0] = 9.0
    r = V.replay(IT, _meta(), RULE, "slip", None, "auction")
    assert r["u"] == [1] and r["g"][0] == pytest.approx((10 - 12.25) / 10)
    assert V.replay(IT, _meta(), RULE, "next_open", None, "auction")["g"][0] == pytest.approx(-0.25)
    no_stop = V.replay(IT, _meta(stop=20.0), RULE, "slip", None, "auction")
    assert no_stop["g"][0] == pytest.approx(0.1)  # covered at the close of 9
    assert no_stop["Q"][0][V.OPEN - 1] == 0 and no_stop["Q"][0][V.OPEN] == 1
    flat = V.replay(IT, _meta(stop=20.0), (0, 1.0, 945, None, None, 1.0), "slip", None, "auction")
    assert flat["g"][0] == pytest.approx(0.0)  # 15:45 at the bar's open of 10
    late = V.replay(IT, _meta(stop=20.0), (30, 1.0, "hold", None, None, 1.0), "slip", None, "auction")
    assert late["es"] == V.OPEN + 30


def test_replay_scale_out(V) -> None:
    _world(V, [10, 10, 9, 8], {(2, 0): _flat(9.0), (3, 0): _flat(8.0)})
    r = V.replay(IT, _meta(kind="close", stop=20.0, hold="d2", scale="half"), RULE, "slip", None, "auction")
    assert r["u"] == [2, 3]
    assert r["g"] == [pytest.approx(0.1), pytest.approx(0.05)]
    assert r["nights"] == 2


def test_liquidation_threshold(V) -> None:
    p = np.r_[np.full(570, 10.0), np.linspace(10, 30, 390)]
    G = (10 - p) / 10
    rec = {"u": [2], "G": [G], "Q": [np.ones(960)], "M": [p / 10], "es": 0, "kind": "open", "t": 2, "j": 0,
           "e": 10.0, "n": 100.0, "cost": 0.0}
    out = V.liquidate([{"_rec": 0, "w": 1.0}], [rec], 5, "threshold", None)
    p_star = 2 / (0.1 + V.THETA / 10)  # 1 + (10 - p) / 10 = theta x p / 10
    assert out[2] == pytest.approx(V.THETA * p_star / 10 - 1, abs=1e-3)
    calm = {**rec, "G": [np.zeros(960)], "M": [np.ones(960)]}
    assert V.liquidate([{"_rec": 0, "w": 1.0}], [calm], 5, "threshold", None)[2] == 0.0


def test_walk_forward(V) -> None:
    ys = [2018, 2019, 2020]
    G = np.zeros((V.NR, 3))
    DD = np.full((V.NR, 3), -0.2)
    G[7] = [1.0, 0.0, 0.0]
    DD[8] = -0.5
    G[8] = [2.0, 0.0, 0.0]
    pk = V.walk_forward(G, DD, ys)
    assert pk[2018] == V.BASE_RULE and pk[2019] == 7
