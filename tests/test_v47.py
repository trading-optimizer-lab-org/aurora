"""v47 checks: the variants as pre-registered, the close cover at market (v43's xclose hook), close entries at
market, O1's classes, decision values and the restore of D, the per-share locate, the floors, the short-sale price
test, the seeded missing locates and days, and the 2:1 measure."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def W():
    from test_v24 import _script
    return _script("run_v47", "run_v47_under_test")


def _world(W, C: list[float], bars: dict) -> None:
    from test_v43 import _world as w43
    w43(W.R43, C, bars)


def _bars(minutes: np.ndarray, price) -> tuple:
    p = np.broadcast_to(np.asarray(price, float), minutes.shape).copy()
    return (minutes, p, p.copy(), p.copy(), p.copy(), np.full(len(minutes), 1e6), p.copy())


def test_variants_match_the_preregistration(W) -> None:
    assert W.NAMES == ["base", "O1", "C955", "X951", "X955", "X958", "L1", "L2", "L3", "F050", "F100", "F200",
                       "F250", "SSR", "U10", "U25", "U50", "M05", "M10", "M20", "TZA", "TZB", "TZA0"]
    assert W.VARIANTS["TZA"] == {"o1": True, "xclose": 955, "loc": (0.01, 0.03), "floor": 0.5, "ssr": True}
    assert W.VARIANTS["TZB"] == {**W.VARIANTS["TZA"], "loc": (0.03, 0.10), "floor": 2.0, "unavail": 0.25,
                                 "miss": 0.10}
    assert W.VARIANTS["TZA0"] == {"xclose": 955, "loc": (0.01, 0.03), "floor": 0.5, "ssr": True, "cmkt": 955}
    assert W.VARIANTS["F250"] == {"floor": 2.5} and W.VARIANTS["U50"] == {"unavail": 0.5}
    import ast
    from pathlib import Path
    gen = ast.parse((Path(__file__).resolve().parents[1] / "scripts" / "gen_v47_wf.py").read_text(encoding="utf-8"))
    got = {n.targets[0].id: ast.literal_eval(n.value) for n in gen.body if isinstance(n, ast.Assign)
           and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("NAMES", "QUICK")}
    assert got["NAMES"] == W.NAMES and got["QUICK"] == W.QUICK_NAMES


def test_close_cover_at_market(W) -> None:
    from test_v43 import IT, _meta
    rule = (0, 1.0, "hold", None, None, 1.0)
    s1 = _bars(np.arange(330, 720), np.where(np.arange(330, 720) >= 954 - 240, 9.0, 10.0))
    _world(W, [10, 9.5, 9.5], {(1, 0): s1})
    m = _meta(stop=20.0)
    auction = W.R43.replay(IT, m, rule, "next_open", None, "auction")
    assert auction["g"][0] == pytest.approx((10 - 9.5) / 10)  # covered at the day's close
    x = W.R43.replay(IT, m, rule, "next_open", None, "auction", xclose=955)
    assert x["Q"][0][954] == 1 and x["Q"][0][955] == 0 and x["g"][0] == pytest.approx(0.1)
    early = W.R43.replay(IT, m, rule, "next_open", None, "auction", xclose=951)
    assert early["g"][0] == pytest.approx(0.0)  # 15:51 at 10.0, before the drop
    part = W.R43.replay(IT, m, rule, "next_open", 0.10, "auction", xclose=955)
    assert part["Q"][0][W.LAST] == 0 and part["g"][0] == pytest.approx(0.1)


def test_close_entry_at_market(W) -> None:
    from test_v43 import IT, _meta
    s1 = _bars(np.arange(330, 720), np.where(np.arange(330, 720) >= 955 - 240, 10.4, 10.0))
    _world(W, [10, 10, 9], {(1, 0): s1})
    m = _meta(kind="close")
    assert W.cmkt_exe(955)(IT, m, 10.0, -1) == (pytest.approx(10.4), -1)
    assert W.cmkt_exe(951)(IT, m, 10.0, -1) == (pytest.approx(10.0), -1)
    assert W.cmkt_exe(955)(IT, _meta(kind="open"), 10.0, W.OPEN) == (10.0, W.OPEN)
    W.R43._G["count"] = {}
    assert W.cmkt_exe(955)({**IT, "t": 2}, m, 9.0, -1) == (9.0, -1) and W.R43._G["count"]["cmkt_no_bars"] == 1


def test_o1_classes_and_decision(W) -> None:
    days = [(5, 0), (10, 0), (40, 0), (12, 1), (5, 1)]
    cl = W.classes(days, window=30)
    assert sorted(x for c in cl for x in c) == sorted(days)
    for c in cl:
        by = {}
        for t, j in c:
            by.setdefault(j, []).append(t)
        assert all(abs(a - b) > 30 for ts in by.values() for a in ts for b in ts if a != b)
    p = np.where(np.arange(330, 720) < 600 - 240, 10.0, 12.0)
    p[(949 - 240) - 330] = 11.0
    p[(952 - 240) - 330] = 20.0  # after the decision: unseen
    _world(W, [10, 10, 10], {(1, 0): _bars(np.arange(330, 720), p)})
    B = W.R43.timeline(1, 0)
    assert W.at_decision(B) == (11.0, 12.0, 10.0)
    D = W.R43._G["D"]
    D["C"].setflags(write=False)
    keep = W.patch(D, {(1, 0), (2, 0)})
    assert list(keep) == [(1, 0)] and D["C"][1, 0] == 11.0 and D["H"][1, 0] == 12.0 and D["L"][1, 0] == 10.0
    W.restore(D, keep)
    assert D["C"][1, 0] == 10.0 and D["H"][1, 0] == pytest.approx(10.5) and D["L"][1, 0] == pytest.approx(9.5)
    assert W.candidates() == [(1, 0)]


def test_cache_clear(W) -> None:
    import sys
    for mod, names in W.CACHES.items():
        for n in names:
            getattr(sys.modules[mod], n)["x"] = 1
    st = sys.modules["run_v28_after"]._ST
    st["keep"] = 1
    W._clear_caches()
    assert all(not getattr(sys.modules[m], n) for m, ns in W.CACHES.items() for n in ns) and st.pop("keep") == 1


def test_locate_floor_missing(W) -> None:
    base = {"sym": "X", "t": 3, "j": 0, "price": 1.5, "tier": 1, "loc": 0.01}
    assert W.locate(base, {}) == 0.01
    assert W.locate(base, {"loc": (0.03, 0.10)}) == pytest.approx(0.02)
    hot = {**base, "tier": 2, "loc": 0.05}  # the HOT 5% cost set: 5/3 of the base share
    assert W.locate(hot, {"loc": (0.01, 0.03)}) == pytest.approx(0.03 / 1.5 * 5 / 3)
    assert W.locate({**base, "tier": 0, "loc": 0.0}, {"loc": (0.01, 0.03)}) == 0.0
    m = {"kind": "open"}
    W.R43._G["D"] = {"C": np.full((5, 1), 1.5), "L": np.full((5, 1), 1.4)}
    assert W.kept(base, m, {"floor": 1.0}) and not W.kept(base, m, {"floor": 2.0})
    its = [{**base, "sym": f"S{k}", "t": k} for k in range(2000)]
    u = [not W.kept(it, m, {"unavail": 0.25}) for it in its]
    assert 0.2 < np.mean(u) < 0.3 and u == [not W.kept(it, m, {"unavail": 0.25}) for it in its]
    assert all(W.kept({**it, "tier": 0}, m, {"unavail": 0.5}) for it in its[:50])
    miss = [not W.kept(it, m, {"miss": 0.10}) for it in its]
    assert 0.07 < np.mean(miss) < 0.13
    same_day = [W.kept({**base, "sym": s, "t": 7}, m, {"miss": 0.5}) for s in "ABCDEFGH"]
    assert len(set(same_day)) == 1  # missed days are whole days


def test_short_sale_price_test(W) -> None:
    from test_v43 import _world as w43
    w43(W.R43, [10, 10, 8.9, 9, 9], {(4, 0): _bars(np.arange(330, 720), np.where(np.arange(330, 720) < 500, 9.0,
                                                                                  8.0))})
    D = W.R43._G["D"]
    D["L"] = D["C"] * 0.99
    it = {"t": 3, "j": 0}
    assert W.ssr_on(it, "open")  # the prior session's low 8.81 <= 0.9 x 10
    assert not W.ssr_on({"t": 4, "j": 0}, "open")
    assert W.ssr_on({"t": 4, "j": 0}, "close")  # 8.0 before 15:50 <= 0.9 x 9
    assert not W.kept({"price": 9.0, "t": 3, "j": 0, "sym": "X"}, {"kind": "open"}, {"ssr": True})


def test_gross_check(W) -> None:
    G = np.zeros(960)
    M = np.full(960, 1.0)
    recs = [{"u": [2], "G": [G], "M": [M], "es": -1, "cost": 0.0, "kind": "close", "t": 1},
            {"u": [1], "G": [G], "M": [M * 0.5], "es": W.OPEN, "cost": 0.0, "kind": "open", "t": 1}]
    taken = [{"w": 1.5, "_rec": 0}, {"w": 1.0, "_rec": 1}]
    d = W.gross_check(taken, recs)
    # session 1: 0.5 open at 15:45, 0.5 + the 1.5 close entry at the close; session 2: 1.5 all day
    assert d["sessions"] == 2 and d["over_2x_1545"] == 0 and d["over_2x_close"] == 0
    taken[0]["w"] = 2.5
    d = W.gross_check(taken, recs)
    assert d["over_2x_1545"] == 0.5 and d["over_2x_close"] == 1.0 and d["worst"] == pytest.approx(3.0)
