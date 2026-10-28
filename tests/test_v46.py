"""v46 checks: the grid, the indicators, triggers and TA exits from the bars up to each bar, the replay hooks (close
entries in the after-hours, stops, TA exits, covers before the open and their cost), the features at the decision,
the filters from earlier years and the stage 2 selection."""
from __future__ import annotations

import numpy as np
import pytest
from test_v44 import _after, _bars_of, _session


@pytest.fixture(scope="module")
def W():
    from test_v24 import _script
    return _script("run_v46", "run_v46_under_test")


def _world(W, C: list[float], bars: dict) -> None:
    from test_v43 import _world as w43
    w43(W.R43, C, bars)
    W.R43._G["D"]["DV1"] = np.full((len(C), 1), 5e6)
    W.M44._G["D"] = W.R43._G["D"]
    W._G["xm"] = {}


def _bars(minutes: np.ndarray, price) -> tuple:
    p = np.broadcast_to(np.asarray(price, float), minutes.shape).copy()
    return (minutes, p, p.copy(), p.copy(), p.copy(), np.full(len(minutes), 1e6), p.copy())


def test_grid_matches_the_preregistration(W) -> None:
    assert [len(d) for d in W.DIMS] == [81, 14, 13, 38, 20, 3] and len(W.FILTERS) == 55
    assert len(W.NF_CONT) == 22 and len(W.NFEATS) == 24
    assert len(W.S1) == 164 == len(set(W.S1)) and W.S1[0] == W.BASE_COMBO
    assert all(sum(v != 0 for v in c) == 1 for c in W.S1[1:])
    sel = {"top": [list(range(8))] * 5 + [[0, 1, 2]], "filters": list(range(8))}
    assert len(W.s2_combos(sel)) == 98_304 and W.s2_combos(sel)[0] == W.BASE_COMBO
    dealt = [c for s in range(300) for c in W.s2_units(sel, s, 300)]
    assert len(dealt) == len(set(dealt)) == 98_304
    assert sorted(u for s in range(164) for u in W.s1_units(s, 164)) == list(range(164))
    for f in range(len(W.FILTERS)):
        W.filter_name(f)
    W.combo_name((1, 1, 1, 1, 1, 1))


def test_triggers_and_exits_use_bars_up_to_k(W) -> None:
    rng = np.random.default_rng(46)
    hits = 0
    for _ in range(6):
        B = _session(rng)
        F = W.session_ind(B)
        steps = W.trigger_steps(F)
        for i, s in enumerate(steps):
            if s >= 10_000:
                continue
            hits += 1
            assert W.trigger_steps(W.session_ind(_after(B, int(s), rng)))[i] == s, W.TRIG_KINDS[i]
        for k in (600, 700, 850):
            F2 = W.session_ind(_after(B, k, rng))
            for x in W.TEXITS[1:]:
                a, b = W._texit_mask(x, F), W._texit_mask(x, F2)
                assert (a[: k + 1] == b[: k + 1]).all(), x
    assert hits >= 40


def test_indicators_on_known_series(W) -> None:
    c = np.r_[np.linspace(10, 20, 60), np.linspace(20, 10, 60)]
    h, lo = c * 1.001, c * 0.999
    r = W.rsi(c, 14)
    assert np.isnan(r[:14]).all() and r[50] > 95 and r[110] < 5
    assert W.supertrend(h, lo, c, 10, 3)[50] == 1 and W.supertrend(h, lo, c, 10, 3)[115] == -1
    assert W.psar(h, lo)[50] == 1 and W.psar(h, lo)[115] == -1
    assert W.heikin(c - 0.01, h, lo, c)[50] and not W.heikin(c + 0.01, h, lo, c)[115]
    assert list(W.run_len(np.array([1, 1, 0, 1, 1, 1], bool))) == [1, 2, 0, 1, 2, 3]
    assert W.delay_of(np.r_[W.OPEN + 20, np.full(15, 10_000)], W.TRIGS.index(("T9", 30, "skip"))) == 21
    assert W.delay_of(np.r_[W.OPEN + 20, np.full(15, 10_000)], W.TRIGS.index(("T9", 15, "skip"))) is None
    assert W.delay_of(np.full(16, 10_000), W.TRIGS.index(("T10", 90, "deadline"))) == 90


def test_close_entry_in_the_after_hours(W) -> None:
    from test_v43 import IT, _meta
    s1 = _bars(np.arange(330, 960), np.where(np.arange(330, 960) >= 720, 10.5, 10.0))
    _world(W, [10, 10, 9, 9], {(1, 0): s1, (2, 0): _bars(np.arange(0, 720), 9.0)})
    m = _meta(kind="close", stop=20.0, hold="d1")
    rule = (0, 1.0, "hold", None, None, 1.0)
    exe = W.exe_of(W.CENTRIES.index(("ah", 30)), 0)
    r = W.R43.replay(IT, m, rule, "next_open", None, "auction", exe=exe)
    e = 10.5 * (1 - W._hs(10.5))
    assert r["es"] == 30 and r["e"] == pytest.approx(e) and r["u"][0] == 2
    assert r["Q"][0][29] == 0 and r["Q"][0][30] == 1 and r["g"][0] == pytest.approx((e - 9) / e)
    lim = W.R43.replay(IT, m, rule, "next_open", None, "auction", exe=W.exe_of(W.CENTRIES.index(("ahlim", 0.02)), 0))
    assert lim["es"] == 0 and lim["e"] == pytest.approx(10.5)
    assert W.R43.replay(IT, m, rule, "next_open", None, "auction",
                        exe=W.exe_of(W.CENTRIES.index(("ahlim", 0.10)), 0)) is None
    mkt = W.exe_of(W.CENTRIES.index(("mkt", 955)), 0)(IT, m, 10.0, -1)
    assert mkt == (pytest.approx(10.0), -1)
    assert W.exe_of(0, 0) is None


def test_stop_and_ta_exit_hooks(W) -> None:
    from test_v43 import IT, _flat, _meta
    b = [x.copy() for x in _flat(10.0)]
    k = 400 - 330
    b[2][k], b[1][k + 1] = 13.0, 12.5
    _world(W, [10, 9, 9], {(1, 0): tuple(b)})
    rule = (0, 1.0, "hold", None, None, 1.0)
    m = _meta(stop=20.0)
    assert W.R43.replay(IT, m, rule, "next_open", None, "auction")["g"][0] == pytest.approx(0.1)
    pct = W.stop_of(W.STOPS.index(("pct", 0.10)))
    assert pct(IT, m, 10.0, W.OPEN, 20.0) == pytest.approx(11.0)
    assert W.R43.replay(IT, m, rule, "next_open", None, "auction", stopf=pct)["g"][0] == pytest.approx(-0.25)
    assert W.stop_of(W.STOPS.index("none"))(IT, m, 10.0, W.OPEN, 12.0) == np.inf and W.stop_of(0) is None
    _world(W, [10, 9, 9], {(1, 0): _flat(9.0)})
    W._G["ind"] = {(1, 0): W.session_ind(W.R43.timeline(1, 0))}
    xm = W.texit_of(W.TEXITS.index(("time", 600)))
    r = W.R43.replay(IT, m, rule, "next_open", None, "auction", xmask=xm)
    assert r["Q"][0][600] == 1 and r["Q"][0][601] == 0 and r["g"][0] == pytest.approx(0.1)
    W._G["ind"] = {}


def test_cover_before_the_open_and_its_cost(W) -> None:
    from test_v43 import IT, _meta
    s2 = _bars(np.arange(0, 720), np.where(np.arange(0, 720) < 330, 9.5, 9.0))
    _world(W, [10, 9, 9, 9], {(1, 0): _bars(np.arange(0, 720), 9.0), (2, 0): s2})
    m = _meta(stop=20.0, hold="d2")
    rule = (0, 1.0, "hold", None, None, 1.0)
    pmx = W.pmx_of(W.PMX.index(("at", 300)))
    r = W.R43.replay(IT, m, rule, "next_open", None, "auction", pmx=pmx)
    assert r["u"] == [1, 2] and r["pmx"] == [(1, 1.0, 299)]
    assert r["g"][0] == pytest.approx(0.1) and r["g"][1] == pytest.approx((9 - 9.5) / 10)
    tgt = W.pmx_of(W.PMX.index(("tgt", 0.03)))
    assert tgt(W.R43.timeline(2, 0), 2, 0, 10.0, 9.0, 0) is None  # 9.5 and 9.0 are not 3% under 9
    assert tgt(W.R43.timeline(2, 0), 2, 0, 10.0, 9.9, 0) == W.AH  # 9.5 is 4% under 9.9
    stp = W.pmx_of(W.PMX.index(("pmstop", 0.05)))
    assert stp(W.R43.timeline(2, 0), 2, 0, 10.0, 9.0, 0) == W.AH
    it = {**IT, "raw0": 0.0, "r": [0.0], "sym": "X", "prio": 0.0}
    combo = (0, 0, 0, 0, W.PMX.index(("at", 300)), 0)
    items, recs = W.items_for([it], [m], combo)
    hs = W._hs(10.0)
    assert items[0]["r"][1] == pytest.approx(r["g"][1] - hs)
    assert recs[0]["G"][1][W.LAST] == pytest.approx(r["G"][1][W.LAST] - hs)
    assert recs[0]["G"][1][298] == pytest.approx(r["G"][1][298])


def test_features_stop_at_the_decision(W) -> None:
    rng = np.random.default_rng(11)
    B = _session(rng)
    it = {"t": 1, "j": 0, "price": 10.0}
    _world(W, [10, 10, 10], {(1, 0): _bars_of(B)})
    fo, fc = W.trade_features(it, "open"), W.trade_features(it, "close")
    _world(W, [10, 10, 10], {(1, 0): _bars_of(_after(B, W.OPEN - 1, rng))})
    assert np.allclose(W.trade_features(it, "open"), fo, equal_nan=True)
    _world(W, [10, 10, 10], {(1, 0): _bars_of(_after(B, 949, rng))})
    assert np.allclose(W.trade_features(it, "close"), fc, equal_nan=True)
    assert np.isfinite(fc).sum() >= 22 and np.isfinite(fo).sum() >= 20


def test_filters_use_earlier_years(W) -> None:
    rng = np.random.default_rng(5)
    years = np.r_[np.full(90, 2018), np.full(3, 2019)]
    XN = rng.normal(0, 1, (93, len(W.NFEATS)))
    XN[:, len(W.NF_CONT):] = rng.choice([-1.0, 1.0], (93, 2))
    XN[:90, 0] = np.arange(1, 91)
    XN[90:, 0] = [100.0, 10.0, 45.0]
    XM = np.hstack([rng.normal(0, 1, (93, 26)), XN])
    y = rng.integers(0, 2, 93)
    keys = [(t, 0, 0.0) for t in range(93)]
    out = W.fit_filters(keys, years, XN, XM, y, years)
    assert not out[keys[0]]["skip"].any() and np.isnan(out[keys[0]]["p"]).all() and np.isnan(out[keys[0]]["bin"]).all()
    assert out[keys[90]]["skip"][0] and not out[keys[90]]["skip"][1]
    assert out[keys[91]]["skip"][1] and not out[keys[91]]["skip"][0]
    assert ((out[keys[92]]["p"] >= 0) & (out[keys[92]]["p"] <= 1)).all()
    W._G["flt"] = {k: out[k] for k in keys[90:]}
    its = [{"t": t, "j": 0, "prio": 0.0, "w": 0.1} for t in (90, 91, 92, 5)]
    assert [x["t"] for x in W.filtered(its, W.FILTERS.index(("terc", 0, "top")))] == [91, 92, 5]
    v = out[keys[90]]["bin"][0]
    kept = W.filtered(its, W.FILTERS.index(("bin", 0, int(v))))
    assert 90 not in [x["t"] for x in kept] and 5 in [x["t"] for x in kept]
    W._G["flt"] = {}


def test_selection_uses_2018_2022_only(W) -> None:
    rng = np.random.default_rng(7)
    ys = list(range(2018, 2027))
    s1 = {}
    for c in W.S1:
        S = rng.normal(0, 0.2, (len(W.FILTERS), len(W.TASKS), len(ys), 2))
        S[..., 1] = -rng.uniform(0, 0.5, S[..., 1].shape)
        s1[c] = (S, rng.normal(0, 0.2, (2, len(ys), 2)))
    sel = W.selection(s1, ys)
    late = {c: (S.copy(), H) for c, (S, H) in s1.items()}
    for S, _ in late.values():
        S[:, :, 5:, :] = rng.normal(0, 5, S[:, :, 5:, :].shape)
    assert W.selection(late, ys) == sel
    assert all(len(t) == 8 and t[0] == 0 and len(set(t)) == 8 for t in sel["top"][:5]) and sel["top"][5] == [0, 1, 2]
    assert len(sel["filters"]) == 8 and sel["filters"][0] == 0
    early = np.arange(len(ys)) < 5
    base_dd = s1[W.BASE_COMBO][0][0, 0, early, 1].min()
    cands = [c for c in W.S1 if c[2] != 0]
    elig = [c for c in cands if s1[c][0][0, 0, early, 1].min() >= base_dd]
    best = sorted(elig, key=lambda c: -s1[c][0][0, 0, early, 0].sum())[:7]
    if len(elig) >= 7:
        assert sel["top"][2][1:] == [c[2] for c in best]
