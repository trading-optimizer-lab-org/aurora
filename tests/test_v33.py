"""v33 checks: the shield's daily path with no variant is v26's, the limit entry (fill at the open, at the limit
only when the high trades 1% through it, no trade otherwise), the emergency exit at the open after a close beyond
the level, the variant lists, the variant choice on earlier years only, and the verdict."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v33", "run_v33_under_test")


def _D(O, H, L, C) -> dict:
    a = {k: np.array(v, float)[:, None] for k, v in (("O", O), ("H", H), ("L", L), ("C", C))}
    T = len(O)
    return {**a, "P": a["C"].copy(), "F": np.ones((T, 1)), "new": np.zeros((T, 1), bool),
            "DV1": np.full((T, 1), 1e9), "SO": np.full((T, 1), 1e7)}


@pytest.fixture
def free(V, monkeypatch):
    monkeypatch.setattr(V.v19, "_costs", lambda raw, *a, **k: (np.zeros(len(raw)), np.ones(len(raw))))
    monkeypatch.setattr(V.sh, "NIGHTS", None)

    def run(D, s, params, var=(None, None)):
        V.sh.set_params(params)
        V.VARIANT.update(limit=var[0], cat=var[1])
        try:
            return V.daily_path(D, s, {}, 1.0, 1.0, False, 0.2), V._ORIG_DAILY(D, s, {}, 1.0, 1.0, False, 0.2)
        finally:
            V.VARIANT.update(limit=None, cat=None)
            V.sh.set_params(None)
    return run


def _spec(V, kind, t=1):
    return V.v19.Spec(j=0, t=t, kind=kind, side=-1, hold=3, stop=np.nan, target=np.nan, trail=np.nan, rule="time",
                      prio=1.0)


P0 = {"hold": "d3", "stop": "pct20", "ext": "none", "rally": "none", "scale": "all", "target": "none"}


@pytest.mark.parametrize("kind", ["open", "close"])
@pytest.mark.parametrize("params", [P0, {**P0, "stop": "own"}, {**P0, "target": "t20"}, {**P0, "scale": "half"},
                                    {**P0, "hold": "d5", "stop": "pct50"}])
def test_no_variant_is_v26(V, free, kind, params) -> None:
    rng = np.random.default_rng(3)
    for _ in range(30):
        C = 10 * np.cumprod(1 + rng.normal(0, 0.15, 9))
        O = C * (1 + rng.normal(0, 0.05, 9))
        H = np.maximum(O, C) * (1 + np.abs(rng.normal(0, 0.1, 9)))
        L = np.minimum(O, C) * (1 - np.abs(rng.normal(0, 0.1, 9)))
        new, old = free(_D(O, H, L, C), _spec(V, kind), params)
        assert (new is None) == (old is None)
        if new is not None:
            assert new[0] == old[0] and np.allclose(new[1], old[1]) and new[3] == old[3]


def test_limit_entry(V, free) -> None:
    s = _spec(V, "open")
    p = {**P0, "hold": "d1"}
    out, _ = free(_D([10, 10.5, 10], [10, 11.2, 10], [10, 10, 10], [10, 10.4, 10]), s, p, (0.10, None))
    assert out[1][0] == pytest.approx((11 - 10.4) / 11)  # filled at the limit 11 (the high 11.2 >= 11.11)
    out, _ = free(_D([10, 10.5, 10], [10, 11.05, 10], [10, 10, 10], [10, 10.4, 10]), s, p, (0.10, None))
    assert out is None  # a touch is not a fill
    out, _ = free(_D([10, 12, 10], [10, 12.5, 10], [10, 11, 10], [10, 11.5, 10]), s, p, (0.10, None))
    assert out[1][0] == pytest.approx((12 - 11.5) / 12)  # the open is above the limit: filled at the open
    out, old = free(_D([10, 10, 10], [10, 10, 10], [10, 10, 10], [10, 10, 10]), _spec(V, "close"), p, (0.10, None))
    assert np.allclose(out[1], old[1])  # entries at a close are unchanged


def test_emergency_exit(V, free) -> None:
    s = _spec(V, "close", t=0)
    p = {**P0, "hold": "d5", "stop": "own"}
    D = _D([10, 11, 13, 18, 18, 18], [10, 12, 16, 19, 19, 19], [10, 11, 13, 17, 17, 17], [10, 12, 16, 18, 18, 18])
    out, old = free(D, s, p, (None, 0.5))
    assert np.allclose(out[1], [-0.2, -0.4, -0.2])  # out at the open of 18 after the close of 16 >= 15
    assert len(old[1]) == 5
    out, _ = free(D, s, p, (None, 1.0))
    assert len(out[1]) == 5  # never closed at or above 20


def test_variant_lists(V) -> None:
    assert len(V.variants("B:v19:DS1")) == 12 and len(V.variants("B:v20:NS")) == 24
    assert V.variants("B:v19:ON1")[0] == V.BASE_VAR


def test_choose_variant_uses_earlier_years(V) -> None:
    months = pd.date_range("2017-01-01", "2020-12-01", freq="MS")
    a, b = V.vname("X|1", V.BASE_VAR), V.vname("X|1", (0.1, None, False))
    ra = np.where(months.year < 2019, 0.01, -0.05) + np.tile([0.0, 0.002], len(months) // 2)
    rb = np.where(months.year < 2019, -0.01, 0.05) + np.tile([0.0, 0.002], len(months) // 2)
    monthly = pd.DataFrame({a: ra, b: rb}, index=months)
    counts = pd.DataFrame({a: 5.0, b: 5.0}, index=months)
    cm = np.zeros(len(months))
    allowed = [V.BASE_VAR, (0.1, None, False)]
    assert V.choose_variant("X|1", "B:v19:DS1", 2019, allowed, monthly, counts, cm) == V.BASE_VAR
    assert V.choose_variant("X|1", "B:v19:DS1", 2017, allowed, monthly, counts, cm) == V.BASE_VAR  # no history
    assert V.choose_variant("X|2", "B:v19:DS1", 2019, allowed, monthly, counts, cm) == V.BASE_VAR  # not computed


def test_verdict(V) -> None:
    get = {}
    for t, a1, arm in (("base", 10, 12), ("base_late", 20, 21), ("hot5", 8, 9), ("spread2", 9, 10)):
        get[("A1", t)] = {"med": a1, "p_ruin": 0.005}
        for name in V.ARMS[1:]:
            get[(name, t)] = {"med": arm if name != "limit" else a1 - 1, "p_ruin": 0.005}
    v = V.verdict(get)
    assert v["arms"]["repick"]["raises"] and not v["arms"]["limit"]["raises"] and v["choice"] in V.ARMS[1:]


def test_liquidation_uses_the_limit_fill(V) -> None:
    D = _D([10, 10.5, 10], [10, 11.2, 10], [10, 10, 10], [10, 10.4, 10])
    r0 = (11 - 10.4) / 11
    it = {"i0": 1, "t": 1, "j": 0, "side": -1, "w": 0.2, "r": [r0], "raw0": r0, "loc": 0.0, "entry": 11.0}
    P = V.R31.position_days([it], D, 3)
    assert P["a"][0] == pytest.approx(0.0) and P["b"][0] == pytest.approx(-0.2 * 0.2 / 11)
    assert P["m0"][0] == pytest.approx(0.2) and P["cl"][0] == pytest.approx(0.2 * r0)
