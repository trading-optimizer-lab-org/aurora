"""v26 checks: the shield reproduces v19's d3 exit and v19's daily path when it adds nothing, the extended-session
stops and rally exits, split covers, name filters from earlier sessions only, the night store's minute offsets and
the event universe of the data script."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v26_shield as sh
from test_v24 import _day, _script

BASE = {"hold": "d3", "stop": "own", "ext": "none", "rally": "none", "scale": "all"}


def _D(T: int = 120, N: int = 3, seed: int = 3) -> dict:
    rng = np.random.default_rng(seed)
    C = 5 * np.exp(np.cumsum(rng.normal(0, 0.04, (T, N)), axis=0))
    O = C * (1 + rng.normal(0, 0.02, (T, N)))
    H, L = np.maximum(O, C) * 1.03, np.minimum(O, C) * 0.97
    off = pd.DataFrame({"t": [50], "j": [1]})
    return {"dates": pd.bdate_range("2019-01-01", periods=T), "O": O, "H": H, "L": L, "C": C, "P": C.copy(),
            "F": np.ones((T, N)), "DV1": np.full((T, N), 5e6), "new": np.zeros((T, N), bool),
            "SO": np.full((T, N), 3e7), "cols": np.array(["A", "B", "C"]), "events": {"offering": off}}


def _nights(rows: dict) -> sh.Nights:
    """rows: {(u, j): [(minute, o, h, l, c), ...]}; every listed night counts as downloaded."""
    idx, arr, off = [], {k: [] for k in ("m", "o", "h", "l", "c")}, 0
    for (u, j), bars in rows.items():
        idx.append({"u": u, "j": j, "off": off, "n": len(bars)})
        for k, col in zip(("m", "o", "h", "l", "c"), zip(*bars)):
            arr[k].append(np.array(col, np.float32 if k != "m" else np.int16))
        off += len(bars)
    arrays = {k: np.concatenate(v) for k, v in arr.items()}
    arrays["fetched"] = np.array(sorted({u for u, _ in rows}), np.int32)
    return sh.Nights(pd.DataFrame(idx), arrays)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(v19.v15, "lookup", lambda table, px, so: (np.ones(len(px)), np.full(len(px), 50.0)))
    before = (v19.MODEL, v19.SLIP, v19.R4_HALF)
    base = v19.R4_HALF[:, :3]
    v19.set_costs("r4", 0.25, np.hstack([base, base[:, 1:2], base[:, 1:2]]))
    yield
    v19.set_costs(*before)
    sh.set_params(None)
    sh.NIGHTS = None


def _intra(D: dict, rng: np.random.Generator, t: int = 60, j: int = 0):
    b = _day(rng, start=float(D["O"][t, j]))
    cd = {"date": D["dates"][t], "t": t, "j": j, "symbol": str(D["cols"][j]), "open": float(b[1][0]),
          "pc": float(D["C"][t - 1, j]), "pmv": 1e6, "so": 2e7, "gap": 0.3}
    line = vi.vwap(b[4], b[5], b[6])
    k = int(rng.integers(5, 200))
    e = float(b[1][k])
    stop = e * 1.15
    return cd, b, line, k, e, stop


def test_shield_without_additions_is_v19_d3() -> None:
    D = _D()
    sh.prepare(D)
    rng = np.random.default_rng(0)
    for _ in range(40):
        cd, b, line, k, e, stop = _intra(D, rng, t=int(rng.integers(30, 100)))
        want = v19.trade_row(D, cd, b, line, -1, k, e, stop, "d3", 1.0)
        sh.set_params(BASE)
        got = sh.intra_row(D, cd, b, line, k, e, stop, 1.0)
        sh.set_params(None)
        assert np.allclose(got["rets"], want["rets"])
        assert got["nights"] == want["nights"] and got["leg_out"] == want["leg_out"]
        assert got["leg_in"] == want["leg_in"] and got["liq"] == pytest.approx(want["liq"])


@pytest.mark.parametrize("kind", ["open", "close"])
def test_daily_shield_without_additions_is_path19(kind: str) -> None:
    D = _D()
    sh.prepare(D)
    table: dict = {}
    for t in range(30, 100, 7):
        for j in range(3):
            s = v19.Spec(j, t, kind, -1, 3, 0.25, np.nan, np.nan, "time", 1.0)
            want = v19.path19(D, s, table, 1.0)
            sh.set_params(BASE)
            got = sh.daily_path(D, s, table, 1.0, 1.0, False, 0.05)
            sh.set_params(None)
            if want is None:
                assert got is None
                continue
            assert got[0] == want[0] and got[3] == pytest.approx(want[3])
            assert np.allclose(got[1], want[1])


def test_after_hours_stop_and_rally_exit() -> None:
    D = _D()
    sh.prepare(D)
    t, j = 60, 0
    e = float(D["C"][t, j])
    stop = e * 1.10
    sh.NIGHTS = _nights({(t, j): [(30, e, e * 1.02, e, e * 1.01), (90, e * 1.05, e * 1.12, e * 1.05, e * 1.11)]})
    s = v19.Spec(j, t, "close", -1, 3, 0.10, np.nan, np.nan, "time", 1.0)
    sh.set_params({**BASE, "stop": "pct10", "ext": "ah"})
    r = sh.walk(D, t, j, e, stop, e, 1.0, [0.0, 0.0, 0.0], sh.PARAMS)
    assert r[2] == sh.LEG_AH and r[1] == 0.0  # out at 17:30 before the night: no borrow night
    assert r[0][0] == pytest.approx((e - v19._slip(stop, e * 1.12)) / e)
    sh.set_params({**BASE, "stop": "pct10", "ext": "pm"})
    r = sh.walk(D, t, j, e, stop, e, 1.0, [0.0, 0.0, 0.0], sh.PARAMS)
    assert r[2] != sh.LEG_AH  # the after-hours rise does not count when only the premarket stop is live
    sh.set_params({**BASE, "rally": "r5"})
    r = sh.walk(D, t, j, e, stop, e, 1.0, [0.0, 0.0, 0.0], sh.PARAMS)
    assert r[2] == sh.LEG_AH and r[0][0] == pytest.approx((e - e * 1.11) / e)
    assert sh.daily_path(D, s, {}, 1.0, 1.0, True, 0.05) is not None


def test_premarket_minutes_use_the_next_sessions_split_scale() -> None:
    D = _D()
    sh.prepare(D)
    t, j = 60, 2
    D["F"][t + 1:, j] = 0.5  # a 2-for-1 split effective on t + 1: raw prices halve the adjusted scale
    e = float(D["C"][t, j])
    raw = e / 0.5 * 1.2  # a premarket print 20% over the entry on the adjusted scale
    sh.NIGHTS = _nights({(t, j): [(300, raw, raw, raw, raw)]})
    sh.set_params({**BASE, "stop": "pct10", "ext": "pm"})
    r = sh.walk(D, t, j, e, e * 1.10, e, 1.0, [0.0, 0.0], sh.PARAMS)
    assert r[2] == sh.LEG_PM and r[0][0] == pytest.approx((e - raw * 0.5) / e) and r[1] == 1.0


def test_split_cover_and_returns_add_up() -> None:
    D = _D()
    sh.prepare(D)
    t, j = 40, 1
    e = float(D["C"][t, j])
    sh.set_params({**BASE, "stop": "pct50"})
    full = sh.walk(D, t, j, e, e * 10, e, 1.0, [0.0, 0.0, 0.0], sh.PARAMS)
    half = sh.walk(D, t, j, e, e * 10, e, 1.0, [0.5, 0.0, 0.0], sh.PARAMS)
    assert sum(full[0]) == pytest.approx((e - D["C"][t + 3, j]) / e)
    assert half[0][0] == pytest.approx(full[0][0]) and half[0][1] == pytest.approx(full[0][1] / 2)
    assert sh.fractions("third", 3) == pytest.approx([1 / 3, 1 / 3, 0.0])
    assert sh.fractions("half", 1) == [0.0]


def test_offering_and_squeeze_windows() -> None:
    D = _D(T=200)
    D["C"][70, 2] = D["C"][69, 2] * 2.5  # a +150% day on session 70
    sh.prepare(D)
    off = sh.FACTS["offer"][:, 1]
    assert not off[49] and off[50] and off[50 + sh.OFFER_ROWS - 1] and not off[50 + sh.OFFER_ROWS]
    sq = sh.FACTS["squeeze"][:, 2]
    assert not sq[71] and sq[72] and sq[70 + sh.SQUEEZE_ROWS] and not sq[71 + sh.SQUEEZE_ROWS]
    assert sh.keep(D, np.array([72, 72]), np.array([2, 0]), "nosq60").tolist() == [False, True]
    assert sh.keep(D, np.array([60, 60]), np.array([1, 0]), "offer90").tolist() == [True, False]
    D["SO"][60, 0] = np.nan
    D["SO"][60, 2] = 1.5e7
    assert sh.keep(D, np.array([60, 60, 60]), np.array([0, 1, 2]), "so20").tolist() == [False, True, False]


def test_atr_does_not_see_the_entry_session() -> None:
    D = _D()
    sh.prepare(D)
    a = sh.FACTS["atr"][80].copy()
    D["H"][80:] *= 4.0
    sh.prepare(D)
    assert np.allclose(sh.FACTS["atr"][80], a)


def test_grid_and_registry_counts() -> None:
    R = _script("run_v26", "run_v26_under_test")
    ent = R.entries_of()
    assert len(ent) == 23
    kinds = {k: kind for k, (kind, _) in ent.items()}
    assert kinds["v19:DS1_RUNUP"] == "daily" and kinds["v25:PS_PATTERN"] == "intra"
    g = R.shield_grid("intra", ["X|1"])
    assert len(g) == 7 * 5 + 3 * 7 * 5 * 4 * 3 * 3
    assert len(R.shield_grid("daily", ["X|1"])) == 4 * 7 * 5 * 4 * 3 * 3
    reg = R.registry()
    assert sum(len(c) for _, c in reg.values()) == len(R.configs())
    half = R.ext_halves(pd.DataFrame({"session": [0] * 60, "tier": [1] * 60, "spread": [0.02] * 60}), v19.R4_HALF[:, :3])
    assert half[1, sh.LEG_AH] == pytest.approx(0.01) and half[0, sh.LEG_AH] == pytest.approx(2 * v19.R4_HALF[0, 1])


def test_capture_records_each_trade_once() -> None:
    R = _script("run_v26", "run_v26_capture")
    D = _D()
    rng = np.random.default_rng(2)
    cd, b, line, k, e, stop = _intra(D, rng)
    R._CAP = []
    try:
        row = v19.trade_row(D, cd, b, line, -1, k, e, stop, "d3", 1.0)
        assert len(R._CAP) == 1 and set(row) == set(v19.COLS)
    finally:
        R._CAP = None
    sh.prepare(D)
    sh.set_params(BASE)
    assert np.allclose(v19.trade_row(D, cd, b, line, -1, k, e, stop, "close", 1.0)["rets"],
                       sh.intra_row(D, cd, b, line, k, e, stop, 1.0)["rets"])
    sh.set_params(None)


def test_night_offsets_and_event_universe() -> None:
    m = _script("run_v26_data", "run_v26_data_under_test")
    dates = pd.bdate_range(core.DESIGN_START - pd.Timedelta(days=60), periods=60)
    T, N = len(dates), 5
    C = np.full((T, N), 5.0)
    O, H = C.copy(), C.copy()
    t = 50
    O[t, 0] = 6.0  # a 20% gap
    H[t, 1] = 7.5  # a 50% run
    C[t, 2] = 7.0  # a 40% close
    D = {"dates": dates, "O": O, "H": H, "C": C, "P1": np.vstack([C[:1], C[:-1]]), "DV1": np.full((T, N), 1e6),
         "valid": np.ones((T, N), bool), "valid1": np.ones((T, N), bool), "cols": np.arange(N)}
    ev = m.events(D)
    assert sorted(ev[t]) == [0, 1, 2]
    nights = m.night_sets(D)
    assert all(set(nights[u]) >= {0, 1, 2} for u in range(t, t + m.NIGHTS))
    assert 2 not in nights.get(t - 1, [])


def test_after_report_helpers() -> None:
    R = _script("run_v26", "run_v26_helpers")
    b = (np.array([0, 1, 2, 5, 6], np.int16), np.array([1.0, 1.1, 1.2, 1.3, 1.4]), np.ones(5), np.ones(5) * 0.9,
         np.ones(5), np.ones(5), np.ones(5))
    a = ({"t": 3, "j": 0, "pc": 1.0}, b, np.ones(5), 1, 1.1, 1.21, 0.5)
    d = R._delayed(a, 3)
    assert d[3] == 3 and d[4] == 1.3 and d[5] == pytest.approx(1.3 * 1.1)
    assert R._delayed(a, 30) is None
    D = _D()
    D["L"][9, 0] = 0.85 * D["C"][8, 0]
    assert R._ssr_day(D, 10, 0, np.inf, 1.0) and not R._ssr_day(D, 10, 1, np.inf, 1.0)
    assert R._ssr_day(D, 10, 1, 0.89, 1.0)
    dates = pd.bdate_range("2020-01-01", periods=10)
    paths = [(0, np.array([0.10]), 1.0, 0.1), (1, np.array([0.01]), 1.0, 0.1), (2, np.array([-0.02]), 1.0, 0.1)]
    s = R.without_top(paths, np.array([True, True, True]), dates, 0.3)
    assert s.iloc[0] == 0.0 and s.iloc[1] == pytest.approx(0.001)
    net = R._net([(0, np.zeros(3), 1.0, 0.1, 7), (1, np.zeros(2), 2.0, 0.1, 7), (3, np.zeros(1), 1.0, 0.1, 7),
                  (1, np.zeros(1), 1.0, 0.1, 8)])
    assert [p[0] for p in net] == [0, 1, 3]
    st = R.stitch({"a": pd.Series(1.0, index=dates), "b": pd.Series(2.0, index=dates)},
                  {2020: "a"}, dates, dates[-1])
    assert (st == 1.0).all()
