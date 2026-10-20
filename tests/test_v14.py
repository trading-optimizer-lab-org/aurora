"""v14 engine checks on small synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v13
from aurora.research import v14_core as core
from aurora.research import v14_intraday as vi
from aurora.research import v14_macro as vm
from aurora.research import v14_swing as vs


def test_sortino_matches_v13() -> None:
    rng = np.random.default_rng(1)
    M = rng.normal(0.01, 0.03, (60, 4))
    cm = np.full(60, 0.001)
    assert np.allclose(core.sortino_cols(M, cm), v13.sortino_cols(M, cm))


def test_seal_defaults_to_design_end(monkeypatch) -> None:
    monkeypatch.delenv(core.UNLOCK_ENV, raising=False)
    assert core.last_day() == core.DESIGN_END
    s = pd.Series(1.0, index=pd.bdate_range("2023-06-01", "2023-08-01"))
    assert core.seal(s).index.max() <= core.DESIGN_END
    monkeypatch.setenv(core.UNLOCK_ENV, "yes-the-owner-asked")
    assert core.last_day() == core.SEALED_END


def test_costs_by_price_tier() -> None:
    c = core.stock_cost(np.array([1.5, 30.0]), "mid")
    assert np.isclose(c[0], 2 * (0.0075 + 0.005 / 1.5))
    assert np.isclose(c[1], 2 * (0.0005 + 0.005 / 30))
    assert core.short_cost(np.array([5.0]), np.array([0]), "mid")[0] == pytest.approx(0.005)
    assert not core.shortable_high(np.array([5.0]), np.array([np.nan]))[0]


def _bars(prices: list[float], start: int = 0) -> tuple:
    p = np.array(prices, dtype=np.float32)
    m = np.arange(start, start + len(p), dtype=np.int16)
    return (m, p, p * 1.001, p * 0.999, p, np.full(len(p), 1000, np.float32), p)


def test_orb_long_entry_and_close_exit() -> None:
    prices = [10.0] * 5 + [10.2, 10.4, 10.6] + [10.5] * 20
    b = _bars(prices)
    j, entry, stop = vi.entry_orb(b, 5, 1)
    assert j == 5 and entry == pytest.approx(max(10.0 * 1.001, 10.2), rel=1e-6)
    assert stop == pytest.approx(10.0 * 0.999, rel=1e-6)
    ex, k = vi.run_exit(1, j, entry, stop, "close", b, vi.vwap(b[4], b[5], b[6]))
    assert k == len(prices) - 1 and ex == pytest.approx(10.5)


def test_short_stop_fills_at_open_when_gapping_through() -> None:
    prices = [10.0] * 5 + [9.8, 9.6, 12.0, 12.0]
    b = _bars(prices)
    ex, k = vi.run_exit(-1, 5, 9.8, 10.5, "close", b, vi.vwap(b[4], b[5], b[6]))
    assert k == 7 and ex == pytest.approx(12.0)


def test_ssr_needs_an_up_minute() -> None:
    b = _bars([8.5, 8.4, 8.3, 8.4])
    j, px = vi._ssr_fill(1, b, 10.0, 8.4)
    assert j == 3 and px == pytest.approx(8.4)


def test_intraday_book_sizes_by_risk_and_caps() -> None:
    d = pd.Timestamp("2020-01-02")
    t = pd.DataFrame([{"date": d, "minute": 5, "side": 1, "entry": 10.0, "exit": 11.0, "stop": 9.0, "price": 10.0,
                       "liq": 1e9, "prio": 1.0, "nights": 0, "so": 1e8}])
    daily, used = core.intraday_book(t, pd.DatetimeIndex([d]), "low")
    assert used["w"].iloc[0] == pytest.approx(0.05)  # 0.5% risk over a 10% stop
    assert daily.iloc[0] == pytest.approx(0.05 * (0.1 - core.stock_cost(np.array([10.0]), "low")[0]))


def test_swing_book_limits_gross() -> None:
    dates = pd.bdate_range("2020-01-01", periods=10)
    paths = [(0, np.full(5, 0.01), 1.0, 0.6), (1, np.full(5, 0.01), 1.0, 0.6)]
    r = core.swing_book(paths, dates)
    assert r.iloc[0] == pytest.approx(0.006) and r.iloc[2] == pytest.approx(0.006)


def _daily(n: int = 30, k: int = 3) -> dict:
    dates = pd.bdate_range("2020-01-01", periods=n)
    C = np.full((n, k), 10.0)
    D = {"dates": dates, "cols": pd.Index([f"S{i}" for i in range(k)]), "O": C.copy(), "H": C * 1.01,
         "L": C * 0.99, "C": C.copy(), "P": C.copy(), "F": np.ones_like(C), "DV": np.full_like(C, 5e6),
         "SO": np.full_like(C, 5e7), "valid": np.ones_like(C, bool), "new": np.zeros_like(C, bool)}
    D["new"][0] = True
    D["valid1"] = np.vstack([np.zeros((1, k), bool), D["valid"][:-1]]) & ~D["new"]
    D["P1"] = np.vstack([np.full((1, k), np.nan), D["P"][:-1]])
    D["DV1"] = np.vstack([np.full((1, k), np.nan), D["DV"][:-1]])
    return D


def test_fade_short_finds_spike_and_stops() -> None:
    D = _daily()
    D["C"][10, 0] = D["H"][10, 0] = 20.0  # +100% day
    D["O"][11, 0], D["C"][11, 0], D["H"][11, 0] = 19.0, 18.0, 19.5
    D["H"][12, 0], D["O"][12, 0], D["C"][12, 0] = 40.0, 30.0, 35.0  # gaps through a 50% stop
    D["P"] = D["C"].copy()
    D["P1"] = np.vstack([np.full((1, 3), np.nan), D["P"][:-1]])
    sp = vs.specs(D, "B12_FADE", {"up": 0.5, "hold": 5, "stop": 0.5})
    assert len(sp) == 1 and sp[0].t == 11 and sp[0].side == -1
    first, r, _, w = vs.path(D, sp[0], "low")
    assert first == 11 and len(r) == 2
    assert r[1] == pytest.approx(-(30.0 / 18.0 - 1))  # stopped at the open above the 28.5 stop


def test_overnight_short_holds_one_night() -> None:
    D = _daily()
    D["C"][10, 1] = D["H"][10, 1] = 20.0
    D["L"][10, 1] = 10.0
    D["C"][10, 1] = 15.0  # +50% close in the middle of the range
    D["P"] = D["C"].copy()
    D["O"][11, 1] = 12.0
    sp = vs.specs(D, "B10_OVERNIGHT", {"up": 0.40, "loc": 1.0})
    sp = [s for s in sp if s.j == 1]
    assert len(sp) == 1 and sp[0].kind == "close"
    first, r, _, _ = vs.path(D, sp[0], "low")
    assert first == 11 and len(r) == 1
    assert r[0] == pytest.approx(-(12.0 / 15.0 - 1) - core.stock_cost(np.array([15.0]), "low")[0]
                                 - core.short_cost(np.array([15.0]), np.array([1]), "low")[0])


def test_positions_and_placebo_shift() -> None:
    ix = pd.bdate_range("2020-01-01", periods=6)
    pos = pd.DataFrame({"A": [0, 1, 1, 0, 0, 0]}, index=ix, dtype=float)
    rets = pd.DataFrame({"A": [0.01] * 6}, index=ix)
    r = vm.returns_from_positions(pos, rets, 0.001)
    assert r.iloc[1] == pytest.approx(0.01 - 0.001) and r.iloc[2] == pytest.approx(0.01)
    assert vm.shift_positions(pos, 2)["A"].tolist() == [0, 0, 0, 1, 1, 0]


def test_walk_forward_uses_only_earlier_years() -> None:
    ix = pd.bdate_range("2016-01-01", "2019-12-31")
    good_early = pd.Series(np.where(ix.year < 2018, 0.002, -0.002), index=ix)
    good_late = pd.Series(np.where(ix.year < 2018, -0.001, 0.003), index=ix)
    R = pd.DataFrame({"a": good_early, "b": good_late})
    cash = pd.Series(0.0, index=ix)
    wf, picks = core.walk_forward(R, cash, [[0], [1]], end=pd.Timestamp("2019-12-31"))
    assert picks[2018][0] == "a"
