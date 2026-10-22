"""v28 checks: the profit target, the new filters (unknown values keep a trade), the squeeze model fit on earlier
years only, event setups known before the entry, the premarket and after-hours entries, the books' signs and the
registry."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh
from aurora.research import v28_ideas as v28
from test_v26 import _D, _nights, _reset  # noqa: F401  (the fixture resets costs and the shield)


@pytest.fixture(autouse=True)
def _undo():
    yield
    v28.uninstall()
    v28.PM_STORE = None


def _D28(T: int = 300, N: int = 3) -> dict:
    D = _D(T, N)
    D["valid"] = np.isfinite(D["C"])
    D["valid1"] = np.vstack([np.zeros((1, N), bool), D["valid"][:-1]])
    D["P1"] = np.vstack([np.full((1, N), np.nan), D["P"][:-1]])
    D["DV"] = np.full((T, N), 5e6)
    return D


def _extras(D: dict) -> dict:
    shp = D["C"].shape
    return {"ftd_so": np.full(shp, np.nan, np.float32), "thr": np.zeros(shp, bool),
            "runway": np.full(shp, np.nan, np.float32), "roa": np.full(shp, np.nan, np.float32),
            "eq_neg": np.zeros(shp, bool), "so_g250": np.zeros(shp, np.float32), "gc": np.zeros(shp, bool),
            "sic": np.array(["2834", "2834", "7372"]), "vix": np.full(shp[0], 20.0, np.float32), "events": {}}


def _prep(D: dict, extras: dict | None = None) -> None:
    sh.prepare(D)
    v28.install()
    v28.prepare(D, {"V": np.full(D["C"].shape, 1e6)}, extras or _extras(D), None)


def test_target_covers_at_the_level_and_v26_is_unchanged() -> None:
    D = _D28()
    sh.prepare(D)
    t, j = 60, 0
    e = float(D["C"][t, j])
    D["O"][t + 1, j], D["H"][t + 1, j], D["L"][t + 1, j], D["C"][t + 1, j] = e * 0.95, e * 0.97, e * 0.65, e * 0.9
    P = {**{"hold": "d3", "stop": "pct50", "ext": "none", "rally": "none", "scale": "all"}}
    base = sh.walk(D, t, j, e, e * 1.5, e, 1.0, [0.0, 0.0], P)
    assert base[0][0] == pytest.approx(0.1)
    got = sh.walk(D, t, j, e, e * 1.5, e, 1.0, [0.0, 0.0], {**P, "target": "t30"})
    assert got[0] == [pytest.approx(0.3)] and sh.EXIT["kind"] == "target"


def test_filters_keep_unknown_values_and_use_known_data() -> None:
    D = _D28()
    ex = _extras(D)
    ex["ftd_so"][100, 1] = 0.03
    ex["thr"][101, 2] = True
    _prep(D, ex)
    t, j = np.array([100, 100, 101]), np.array([0, 1, 2])
    assert list(v28.keep28(D, t, j, "ftd1")) == [True, False, True]
    assert list(v28.keep28(D, t, j, "thr")) == [True, True, False]
    assert list(v28.keep28(D, t, j, "si20")) == [True, True, True]  # no short interest loaded: keep
    assert not v28.keep28(D, t, j, "run12").any()  # 'keep only' rules need the value
    assert v28.keep28(D, t, j, "runok").all()
    v28.X["mania"][99] = 50.0
    v28.X["mania_q80"][100] = 10.0
    assert not v28.keep28(D, np.array([100]), np.array([0]), "mania80")[0]
    assert v28.keep28(D, np.array([101]), np.array([0]), "mania80")[0] or v28.X["mania"][100] >= v28.X["mania_q80"][101]
    assert sh.keep(D, np.array([60]), np.array([0]), "so10")[0]  # v26's own rules still go to v26


def test_squeeze_model_uses_earlier_years_only() -> None:
    rng = np.random.default_rng(5)
    T, N = 1300, 40
    dates = pd.bdate_range("2016-01-01", periods=T)
    C = 5 * np.exp(np.cumsum(rng.normal(0, 0.08, (T, N)), axis=0))
    O = C * (1 + rng.normal(0, 0.12, (T, N)))
    H, L = np.maximum(O, C) * (1 + rng.uniform(0, 0.4, (T, N))), np.minimum(O, C) * 0.95
    D = {"dates": dates, "O": O, "H": H, "L": L, "C": C, "P": C.copy(), "F": np.ones((T, N)),
         "cols": np.array([f"S{i}" for i in range(N)]),
         "SO": np.full((T, N), 2e7), "new": np.zeros((T, N), bool), "events": {"offering": pd.DataFrame({"t": [5], "j": [0]})}}
    D["valid"] = np.ones((T, N), bool)
    D["valid1"] = np.vstack([np.zeros((1, N), bool), D["valid"][:-1]])
    D["P1"] = np.vstack([np.full((1, N), np.nan), C[:-1]])
    D["DV1"] = np.full((T, N), 5e6)
    D["DV"] = D["DV1"]
    ex = _extras(D)
    ex["sic"] = np.array([""] * N)
    ex["vix"] = np.full(T, 20.0)
    _prep(D, ex)
    p1 = v28.X["sq_p"].copy()
    y2019 = int(np.searchsorted(dates, pd.Timestamp("2019-01-01")))
    D2 = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in D.items()}
    D2["H"][y2019 + 5:] *= 3.0  # later highs change the labels of later years only
    _prep(D2, ex)
    p2 = v28.X["sq_p"]
    early = np.arange(T) < y2019 - 3
    assert np.allclose(np.nan_to_num(p1[early]), np.nan_to_num(p2[early]))
    assert np.isfinite(p1).any() and 2018 in v28.X["sq_cut"]


def test_event_setup_enters_at_the_event_session_open() -> None:
    D = _D28()
    _prep(D)
    rows = pd.DataFrame({"t": [80], "j": [1]})
    v28.X["events"]["nt"] = rows
    g = {"param": "any", "run": "any", "band": "low", "trig": "open", "hold": "d3", "stop": "pct35", "ext": "none"}
    D["P"][:, 1] = 3.0
    specs = v28.event_specs(D, "C:NT_SHORT", g)
    assert [(s.t, s.j, s.kind, s.side) for s in specs] == [(80, 1, "open", -1)]


def test_premarket_entry_stop_and_hold() -> None:
    D = _D28()
    _prep(D)
    t, j = 61, 0
    pc = float(D["P"][t - 1, j])
    bars = [(240 + 100, pc * 1.6, pc * 1.7, pc * 1.5, pc * 1.6), (240 + 240, pc * 1.5, pc * 1.55, pc * 1.45, pc * 1.5),
            (240 + 250, pc * 1.5, pc * 1.52, pc * 1.4, pc * 1.45)]
    v28.PM_STORE = _nights({(t - 1, j): bars})
    v28.PM_STORE.a["v"] = np.full(3, 1000.0, np.float32)
    g = {"gap": 0.4, "minute": 240, "rule": "any", "stop": "pct35", "hold": "d1", "band": "low", "ext": "none"}
    D["P1"][:, j] = 3.0
    D["O"][t, j], D["H"][t, j], D["C"][t, j] = pc * 1.4, pc * 1.45, pc * 1.2
    tr = v28.pm_trades(D, g)
    assert len(tr) == 1
    r = tr.iloc[0]
    assert r["entry"] == pytest.approx(pc * 1.5) and r["leg_in"] == sh.LEG_PM
    assert float(r["rets"][0]) == pytest.approx((1.5 - 1.2) / 1.5, rel=1e-5)
    bars[2] = (240 + 250, pc * 1.5, pc * 2.1, pc * 1.4, pc * 1.45)  # 35% stop at 2.025 hit in the premarket
    v28.PM_STORE = _nights({(t - 1, j): bars})
    tr = v28.pm_trades(D, g)
    assert float(tr.iloc[0]["rets"][0]) < -0.35 and tr.iloc[0]["leg_out"] == sh.LEG_PM
    v28.PM_STORE = None


def test_after_hours_entry_books_from_the_next_session() -> None:
    D = _D28()
    _prep(D)
    t, j = 70, 2
    D["C"][t, j] = D["C"][t - 1, j] * 1.8
    D["P"][t, j] = D["C"][t, j]
    D["P1"][:, j] = 3.0
    c = float(D["C"][t, j])
    sh.NIGHTS = _nights({(t, j): [(30, c * 0.95, c * 0.96, c * 0.94, c * 0.95)]})
    D["O"][t + 1, j], D["H"][t + 1, j], D["C"][t + 1, j] = c * 0.9, c * 0.92, c * 0.8
    g = {"up": 0.6, "minute": 30, "rule": "below", "stop": "pct35", "hold": "d1", "band": "low", "ext": "none"}
    tr = v28.ah_trades(D, g)
    assert len(tr) == 1 and int(tr.iloc[0]["t"]) == t + 1 and tr.iloc[0]["nights"] == 1.0
    assert float(tr.iloc[0]["rets"][0]) == pytest.approx((0.95 - 0.8) / 0.95, rel=1e-5)


def test_books_and_registry() -> None:
    D = _D28()
    D["cols"] = np.array(["TNA", "TZA", "X"])
    D["C"][:, 0] = 10 * np.exp(np.linspace(0, 0.5, len(D["dates"])))
    D["C"][:, 1] = 10 * np.exp(np.linspace(0, -0.5, len(D["dates"])))
    _prep(D)
    s, _, _ = v28.lev_book(D, {"set": "iwm", "reb": "month", "vix": "none"}, 0.0, 0.0, True)
    assert s.sum() < 0.05  # a trending pair: one short leg loses as much as the other gains
    keys = list(v28.EVENT_FAMS) + list(v28.LONG_FAMS)
    fams = [k.split("_")[0] for k in keys]
    assert len(set(fams)) == len(fams)
    g = v28.event_grid("C:LOCKUP_SHORT")
    assert {x["trig"] for x in g} == {"open"}
    assert len(v19.COLS) >= 17


def test_margin_by_price_and_the_joint_book() -> None:
    from test_v24 import _script
    A = _script("run_v28_after", "run_v28_after_under_test")
    m = A.margin(np.array([1.5, 3.0, 10.0]), np.array([-1, -1, -1]), "tzi", "intra")
    assert m == pytest.approx([2.5 / 1.5, 1.0, 1 / 6])
    assert A.margin(np.array([10.0]), np.array([-1]), "tzi", "night")[0] == pytest.approx(0.5)
    assert A.margin(np.array([3.0]), np.array([-1]), "tzus", "intra")[0] == pytest.approx(5 / 3)
    dates = pd.bdate_range("2020-01-01", periods=20)
    v28.X.clear()

    def it(i0, j, w, price, r=(0.01,)):
        return {"i0": i0, "r": np.array(r), "prio": 0.0, "w": w, "j": j, "price": price, "side": -1, "nights": 0.0,
                "ah": False, "liq": 1e6, "fam": "F", "sym": "S"}
    s, taken = A.joint([it(2, 0, 0.8, 1.5)], dates, 2.0, rule="tzi", locate=0.0)
    assert taken == []  # 0.8 of the account at $1.50 needs 133% of the equity
    s, taken = A.joint([it(2, 0, 0.8, 1.5)], dates, 2.0, rule="none", locate=0.0)
    assert len(taken) == 1 and s.iloc[2] == pytest.approx(0.008)
    s, taken = A.joint([it(2, 0, 0.3, 10.0, (0.01, 0.02)), it(3, 0, 0.3, 10.0)], dates, 2.0, rule="tzi", locate=0.01)
    assert len(taken) == 1 and s.iloc[2] == pytest.approx(0.3 * (0.01 - 0.01))  # same symbol still held: skipped
