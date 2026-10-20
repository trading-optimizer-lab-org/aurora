"""v19 engine checks on small synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19

TABLE = {}  # empty availability table: every short is fully available at the default 100% fee


def _bars(prices: list[float]) -> tuple:
    p = np.array(prices, dtype=float)
    m = np.arange(len(p), dtype=np.int16)
    return (m, p, p * 1.001, p * 0.999, p, np.full(len(p), 1000.0), p)


def _daily(n: int = 40, k: int = 3) -> dict:
    dates = pd.bdate_range("2020-01-01", periods=n)
    C = np.full((n, k), 10.0)
    D = {"dates": dates, "O": C.copy(), "H": C * 1.01, "L": C * 0.99, "C": C.copy(), "P": C.copy(),
         "F": np.ones_like(C), "DV": np.full_like(C, 5e6), "SO": np.full_like(C, 5e7),
         "valid": np.ones_like(C, bool), "new": np.zeros_like(C, bool)}
    D["new"][0] = True
    return _finish(D)


def _finish(D: dict) -> dict:
    k = D["C"].shape[1]
    D["valid1"] = np.vstack([np.zeros((1, k), bool), D["valid"][:-1]]) & ~D["new"]
    D["P1"] = np.vstack([np.full((1, k), np.nan), D["P"][:-1]])
    D["DV1"] = np.vstack([np.full((1, k), np.nan), D["DV"][:-1]])
    return D


def test_grid_size_and_no_nan_dimensions() -> None:
    sizes = {k: len(core.grid(d)) for k, d in {**v19.INTRA_DIMS, **v19.DAILY_DIMS}.items()}
    assert sum(sizes.values()) == 5542
    for d in {**v19.INTRA_DIMS, **v19.DAILY_DIMS}.values():
        for vals in d.values():
            assert all(not (isinstance(x, float) and np.isnan(x)) for x in vals)  # nan would break neighbours


def test_short_target_two_r() -> None:
    b = _bars([10.0, 9.8, 9.6, 9.2, 8.5, 8.0, 8.0])
    px, held = v19.session_exit(-1, 1, 9.8, 10.3, "r2", b, b[4], 12.0)
    assert not held and px == pytest.approx(min(8.5, 9.8 - 2 * 0.5))


def test_short_trailing_stop_follows_the_low() -> None:
    b = _bars([10.0, 9.0, 8.0, 7.0, 8.6, 8.6])
    px, _ = v19.session_exit(-1, 1, 9.0, 11.0, "trail20", b, b[4], 12.0)
    assert px == pytest.approx(max(8.6, 7.0 * 0.999 * 1.2))


def test_time_exit_and_stop_first() -> None:
    b = _bars([10.0] + [9.5] * 70)
    px, _ = v19.session_exit(-1, 1, 9.5, 11.0, "t60", b, b[4], 12.0)
    assert px == pytest.approx(9.5)
    b = _bars([10.0, 9.5, 11.5, 9.0] + [9.0] * 70)
    px, _ = v19.session_exit(-1, 1, 9.5, 11.0, "t60", b, b[4], 12.0)
    assert px == pytest.approx(11.5)  # gapped through the stop at that bar's open


def test_carry_next_open_and_multi_day_stop() -> None:
    D = _daily()
    D["O"][11, 0] = 9.0
    assert v19.carry(D, 10, 0, -1, 10.0, 9.5, 11.0, "next_open") == [pytest.approx(0.05)]
    D["H"][12, 0], D["O"][12, 0] = 12.0, 11.5
    r = v19.carry(D, 10, 0, -1, 10.0, 9.5, 11.0, "d3")
    assert r[0] == pytest.approx(-(10.0 - 9.5) / 10.0) and r[1] == pytest.approx(-(11.5 - 10.0) / 10.0)


def test_path_target_stop_and_entry_price_cap() -> None:
    D = _daily()
    D["O"][11, 1] = 10.0
    D["L"][13, 1], D["C"][13, 1] = 4.0, 6.0
    s = v19.Spec(1, 11, "open", -1, 10, np.nan, 0.5, np.nan, "time", 0.0)
    first, r, _, w = v19.path19(D, s, TABLE, 1.0, gross=True)
    assert first == 11 and len(r) == 3 and r.sum() == pytest.approx(0.5)  # out at the 5.0 target
    D["H"][12, 2], D["O"][12, 2] = 20.0, 16.0
    s = v19.Spec(2, 11, "open", -1, 10, 0.5, np.nan, np.nan, "time", 0.0)
    _, r, _, _ = v19.path19(D, s, TABLE, 1.0, gross=True)
    assert r.sum() == pytest.approx(-(16.0 - 10.0) / 10.0)  # gapped through the 15.0 stop


def test_path_strength_rule_and_close_entry() -> None:
    D = _daily()
    D["C"][13, 0], D["H"][12, 0] = 10.5, 10.1
    s = v19.Spec(0, 11, "open", -1, 10, np.nan, np.nan, np.nan, "strength", 0.0)
    _, r, _, _ = v19.path19(D, s, TABLE, 1.0, gross=True)
    assert len(r) == 3  # out at the close above the prior day's high
    s = v19.Spec(0, 11, "close", -1, 1, np.nan, np.nan, np.nan, "open1", 0.0)
    D["O"][12, 0] = 9.0
    first, r, _, _ = v19.path19(D, s, TABLE, 1.0, gross=True)
    assert first == 12 and r[0] == pytest.approx(0.1)


def test_costs_charge_borrow_per_night() -> None:
    D = _daily()
    s = v19.Spec(0, 11, "open", -1, 4, np.nan, np.nan, np.nan, "time", 0.0)
    _, r_net, _, _ = v19.path19(D, s, TABLE, 1.0)
    _, r_gross, _, _ = v19.path19(D, s, TABLE, 1.0, gross=True)
    expect = 2 * (core.half_spread(np.array([10.0]), "mid")[0] + core.COMMISSION / 10.0) + 100.0 / 100 / 360 * 3
    assert r_gross.sum() - r_net.sum() == pytest.approx(expect)


def test_runup_triggers_enter_after_the_signal() -> None:
    D = _daily()
    D["O"][9, 0] = D["C"][9, 0] = D["L"][9, 0] = 5.0
    D["C"][10, 0], D["H"][10, 0], D["L"][10, 0] = 15.0, 15.0, 14.0  # +200% day
    D["O"][11, 0], D["C"][11, 0], D["L"][11, 0], D["H"][11, 0] = 15.5, 12.5, 12.0, 16.0  # red, below prior low
    D["O"][12, 0] = 11.5
    D["P"] = D["C"].copy()
    D = _finish(D)
    g = {"rise": 1.0, "window": 1, "hold": 3, "stop": "none", "exit": "time"}
    by = {trig: v19.daily_specs(D, {}, "DS1_RUNUP", {**g, "trig": trig}) for trig in
          ("open", "lowclose", "redclose", "redclose_c", "gapdown")}
    assert [(s.t, s.kind) for s in by["open"]] == [(11, "open")]
    assert [(s.t, s.kind) for s in by["lowclose"]] == [(12, "open")]
    assert [(s.t, s.kind) for s in by["redclose_c"]] == [(11, "close")]
    assert [(s.t, s.kind) for s in by["gapdown"]] == [(12, "open")]  # 23 <= 0.95 x 25, entered at that open


def test_book_caps_gross_and_reports_taken() -> None:
    dates = pd.bdate_range("2020-01-01", periods=10)
    paths = [(0, np.full(5, 0.01), 1.0, 0.6), (1, np.full(5, 0.01), 2.0, 0.6), (6, np.full(2, 0.01), 0.0, 0.6)]
    s, taken = v19.book_paths(paths, dates)
    assert taken.tolist() == [True, False, True]
    assert s.iloc[0] == pytest.approx(0.006)


def test_intraday_triggers() -> None:
    b = _bars([10.0, 10.2, 10.4, 10.1, 9.7, 9.5, 9.4, 9.3])
    line = np.full(8, 10.0)
    ok = np.ones(8, bool)
    j, e = v19.trigger("orl1", -1, b, line, ok)
    assert j == 4 and e == pytest.approx(9.7)  # filled at the bar's open below the 1-minute low
    assert v19.trigger("open", -1, b, line, ok) == (0, 10.0)
    assert v19.trigger("vwaploss", -1, b, line, ok)[0] == -1  # nothing before minute 15
    b = _bars([10.5] * 20 + [9.8] * 10)
    assert v19.trigger("vwaploss", -1, b, np.full(30, 10.0), np.ones(30, bool)) == (21, pytest.approx(9.8))


def test_slippage_on_stop_type_fills_only() -> None:
    b = _bars([10.0, 10.2, 10.4, 10.1, 9.7, 9.5, 9.4, 9.3])
    line, ok = np.full(8, 10.0), np.ones(8, bool)
    try:
        v19.set_costs("r1", 0.5)
        j, e = v19.trigger("orl1", -1, b, line, ok)
        assert j == 4 and e == pytest.approx(9.7)  # opened below the level: the open, no slippage
        m = np.arange(4, dtype=np.int16)
        o, c = np.array([10.0, 10.0, 10.0, 9.9]), np.array([10.0, 10.0, 9.95, 9.9])
        b2 = (m, o, o + 0.01, np.array([9.99, 9.995, 9.90, 9.85]), c, np.full(4, 1e3), c)
        j, e = v19.trigger("orl1", -1, b2, np.full(4, 9.0), np.ones(4, bool))
        assert j == 2 and e == pytest.approx(9.99 + 0.5 * (9.90 - 9.99))  # halfway to the bar's low
        b3 = _bars([10.0, 9.0, 9.0, 10.8, 10.8])
        px, _ = v19.session_exit(-1, 1, 9.0, 10.5, "close", b3, b3[4], 12.0)
        assert px == pytest.approx(10.8)  # opened above the stop: the open
        b4 = _bars([10.0, 9.0, 10.4, 10.8])
        b4 = (b4[0], b4[1], np.array([10.01, 9.009, 10.9, 10.81]), b4[3], b4[4], b4[5], b4[6])
        px, _ = v19.session_exit(-1, 1, 9.0, 10.5, "close", b4, b4[4], 12.0)
        assert px == pytest.approx(10.5 + 0.5 * (10.9 - 10.5))
        px, _ = v19.session_exit(-1, 1, 9.8, 10.3, "r2", _bars([10.0, 9.8, 9.6, 9.2, 8.5, 8.0]), np.full(6, 9.0), 12.0)
        assert px == pytest.approx(8.5)  # a target is a limit order: no slippage
    finally:
        v19.set_costs("r1", 0.0)


def test_realistic_costs() -> None:
    try:
        v19.set_costs("r3", 0.0)
        cost, avail = v19._costs(np.array([3.0, 3.0]), np.array([2e7, 2e7]), np.array([-1, 1]), np.array([2, 2]),
                                 np.array([1, 0]), {("2-5", "10-50M"): (0.9, 40.0, 50)}, 1.0, 1.0, False)
        comm = 2 * 0.0065 / 3.0 + 0.0000278 + 0.000166 / 3.0
        assert cost[0] == pytest.approx(0.0036 * 2.5 + comm + 100.0 / 100 / 360 * 2)  # fee max(2 x 40, 100)
        assert cost[1] == pytest.approx(0.0036 * 2 + comm)  # a long pays no borrow
        assert avail.tolist() == pytest.approx([0.72, 1.0])
    finally:
        v19.set_costs("r1", 0.0)
