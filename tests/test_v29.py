"""v29 checks: locate tiers from facts known at the entry, TradeZero's commission minimum and odd-lot borrow, the
locate gate on earlier years only, one-year paths across equity levels with fixed costs, the late night stop, the
item locate and the sleeve in the joint book, and the choice rule."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v26_shield as sh
from aurora.research import v28_ideas as v28
from test_v26 import _D, _nights, _reset  # noqa: F401  (the fixture resets costs and the shield)


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v29", "run_v29_under_test")


@pytest.fixture(autouse=True)
def _undo():
    yield
    v28.X.clear()
    sh.EXT_DELAY = False


def _setup(V, T: int = 300) -> dict:
    D = _D(T, 3)
    D["SO"][:, 2] = 80e6
    D["DV1"][:, 2] = 30e6
    D["C"][:, 2] *= 4  # about $20
    D["O"][:, 2] = D["C"][:, 2]
    V.R14._G["D"] = D
    V.R16._W["table"] = {}
    shp = D["C"].shape
    v28.X.clear()
    v28.X.update({"thr": np.zeros(shp, bool), "si_so": np.zeros(shp), "low20s2": D["C"] * 0.9})
    return D


def _item(t, j, w, price, r=(0.02,), nights=0.0, fam="F", sym="S"):
    return {"i0": t, "t": t, "r": np.array(r, float), "prio": 0.0, "w": w, "j": j, "price": price, "side": -1,
            "nights": nights, "ah": False, "liq": 1e7, "fam": fam, "sym": sym, "so": 3e7}


def test_tiers_use_the_state_at_the_entry(V) -> None:
    D = _setup(V)
    t = 100
    D["O"][t, 0] = D["C"][t - 1, 0] * 1.6  # a gap of 60%
    v28.X["thr"][t, 1] = True
    got = V.tiers(D, np.array([t, t, t, t + 1]), np.array([0, 1, 2, 1]),
                  np.array([D["O"][t, 0], 5.0, 20.0, 5.0]))
    assert got.tolist() == [2, 2, 0, 1]
    v28.X["low20s2"][t + 1, 1] = D["C"][t, 1] / 2.5  # the prior close 2.5x the 20-session low
    assert V.tiers(D, np.array([t + 1]), np.array([1]), np.array([5.0]))[0] == 2


def test_tradezero_costs_whole_shares_minimum_and_odd_lots(V) -> None:
    _setup(V)
    big = V.tz_items([_item(100, 1, 0.06, 3.0)], 5000.0, 0.01, 0.03)[0]  # 100 shares: $0.50 an order
    assert big["r"][0] == pytest.approx(0.02 - 2 * 0.01 / 300)  # the reporting fee only
    assert big["loc"] == pytest.approx(0.01) and big["tier"] == 1
    small = V.tz_items([_item(100, 1, 0.03, 3.0, nights=2.0)], 5000.0, 0.01, 0.03)[0]  # 50 shares held two nights
    comm = 2 * (0.49 - 0.25) / 150
    odd = 100 / 100 / 360 * 2 * 1.0  # borrow on 100 shares instead of 50 (the fixture's fee 50 -> doubled to 100)
    assert small["r"][0] == pytest.approx(0.02 - comm - 2 * 0.01 / 150 - odd)
    assert V.tz_items([_item(100, 1, 0.0005, 3.0)], 5000.0, 0.01, 0.03) == []  # under one share
    assert V.tz_items([_item(100, 1, 0.06, 2.0)], 5000.0, 0.01, 0.03, floor=2.5) == []
    same = V.tz_items([_item(100, 1, 0.06, 3.0)], 5000.0, 0.01, 0.03, credit=0.5)[0]
    assert same["loc"] == pytest.approx(0.005)  # closed the session it opened: half the locate back
    v28.X["thr"][100, 1] = True
    assert V.tz_items([_item(100, 1, 0.06, 3.0, nights=1.0)], 5000.0, 0.01, 0.03, nohot=True) == []
    assert V.tz_items([_item(100, 1, 0.06, 3.0, nights=1.0)], 5000.0, 0.01, 0.03)[0]["loc"] == pytest.approx(0.03)


def test_gate_reads_earlier_years_only(V) -> None:
    D = _setup(V, 600)
    y1 = int(np.flatnonzero(D["dates"].year == D["dates"][0].year)[5])
    y2 = int(np.flatnonzero(D["dates"].year == D["dates"][0].year + 1)[5])
    items = [{**_item(y1, 1, 0.1, 3.0, (0.02,)), "loc": 0.05},  # first year: never skipped
             {**_item(y2, 1, 0.1, 3.0, (0.02,)), "loc": 0.03},  # locate over the earlier mean of 2%: skipped
             {**_item(y2 + 1, 1, 0.1, 3.0, (0.02,)), "loc": 0.01},
             {**_item(y2, 1, 0.1, 3.0, (0.02,), fam="G"), "loc": 0.03}]  # another family's first year
    kept = V.gate(items)
    assert [(it["fam"], it["loc"]) for it in kept] == [("F", 0.05), ("F", 0.01), ("G", 0.03)]


def test_paths_switch_levels_and_pay_fixed_costs(V) -> None:
    R = np.zeros((len(V.LEVELS), 400))
    R[1] = 0.01  # the $5k level grows 1% a session, the $10k level is flat
    eq, low = V.paths(R, np.arange(400)[None, :], 0.0)
    assert 10_000 <= eq[0] < 10_100 and low[0] == pytest.approx(5000)
    eq, _ = V.paths(np.zeros((len(V.LEVELS), 252)), np.arange(252)[None, :], 21.0)
    assert eq[0] == pytest.approx(5000 - 252 * 1.0)  # $21 a month
    R[:] = -1.5
    eq, low = V.paths(R, np.arange(10)[None, :], 6.0)
    assert eq[0] == 0 and low[0] == 0
    st = V.year_stats(np.array([1000.0, 6000.0, 9000.0]), np.array([1000.0, 4000.0, 5000.0]))
    assert st["p_ruin"] == pytest.approx(1 / 3) and st["p_half"] == pytest.approx(1 / 3)
    idx = V.draws(500, paths=50)
    assert idx.shape == (50, V.DAYS) and idx.min() >= 0 and idx.max() < 500


def test_history_windows_start_each_month(V) -> None:
    cal = pd.bdate_range("2018-01-01", periods=600)
    h = V.history(np.full((len(V.LEVELS), 600), 0.001), cal, 0.0)
    assert h["windows"][0]["start"] == "2018-01-01" and h["windows"][1]["start"] == "2018-02-01"
    assert all(pd.Timestamp(w["start"]) <= cal[600 - V.DAYS] for w in h["windows"])
    assert h["end"] == pytest.approx(5000 * 1.001 ** 600)


def test_night_stop_one_bar_late(V) -> None:
    D = _D(120, 3)
    sh.NIGHTS = _nights({(60, 0): [(10, 5.0, 6.5, 5.0, 6.2), (30, 7.0, 7.2, 6.8, 7.0)]})
    P = {"hold": "d3", "stop": "pct20", "ext": "ah", "rally": "none", "scale": "all"}
    now = sh._night(60, 0, 6.0, 5.0, D["F"], P)
    assert now[0] == pytest.approx(6.0 + 0.25 * 0.5) and now[2] == 10  # the slipped stop (SLIP 0.25)
    sh.EXT_DELAY = True
    late = sh._night(60, 0, 6.0, 5.0, D["F"], P)
    assert late[0] == pytest.approx(7.0) and late[2] == 30
    sh.NIGHTS = _nights({(60, 0): [(10, 5.0, 6.5, 5.0, 6.2)]})
    assert sh._night(60, 0, 6.0, 5.0, D["F"], P) is None  # no later bar: the next open covers it
    sh.NIGHTS = None


def test_joint_item_locate_and_sleeve(V) -> None:
    dates = pd.bdate_range("2020-01-01", periods=20)
    it = {**_item(2, 0, 0.5, 10.0, (0.02,)), "loc": 0.01}
    s, taken = V.A.joint([it], dates, 2.0, rule="tzi", locate=0.5)
    assert s.iloc[2] == pytest.approx(0.5 * 0.01)  # the item's own locate, not the argument
    lt = np.full(20, 0.001)
    s, taken = V.A.joint([it], dates, 2.0, rule="tzi", locate=0.0, sleeve=(lt, 0.5, 0.75))
    assert s.iloc[2] == pytest.approx(0.5 * 0.01 + 0.0005) and len(taken) == 1
    big = {**_item(2, 0, 0.6, 3.0, (0.02,)), "loc": 0.0}  # needs 60% of the equity at $3
    assert V.A.joint([big], dates, 2.0, rule="tzi", locate=0.0, sleeve=(lt, 0.6, 0.75))[1] == []


def test_choice_rule(V) -> None:
    df = pd.DataFrame([{"plan": "FREE", "med": 9000, "p_ruin": 0.02, "p_half": 0.1},
                       {"plan": "FREE", "med": 8000, "p_ruin": 0.01, "p_half": 0.05},
                       {"plan": "FREE", "med": 7000, "p_ruin": 0.0, "p_half": 0.0}])
    assert V.pick(df)["med"] == 8000 and V.pick(df, "p_half")["med"] == 7000
    assert V.pick(df[df["p_ruin"] > 0.01]) is None
