from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import stocks_sepa as ss
from aurora.research import x_swing as xs


def _dates(n: int, start: str = "1995-01-02") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _panel(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"open": close.copy(), "high": close * 1.01, "low": close * 0.99, "close": close,
            "volume": close * 0 + 1e6, "dollar_volume": close * 1e6, "real_price": close}


def _ind(dates, cols, entry_day: int, stop: float, entry: str = "b1") -> dict:
    sig = pd.DataFrame(False, index=dates, columns=cols)
    sig.iloc[entry_day, 0] = True
    frame = pd.DataFrame(0.0, index=dates, columns=cols)
    return {"entries": {entry: sig}, "common": sig | True, "market": pd.Series(True, index=dates),
            "rs": frame + 90, "stops": {entry: frame + stop}, "sma20": frame, "ema9": frame,
            "industry": frame + 99}


def test_grid() -> None:
    assert len(xs.CANDIDATES) == 8
    assert xs.CANDIDATES["b2_ma20_ind"] == {"entry": "b2", "exit": "ma20", "industry": True}


def test_hold5_risk_sizing_and_close_exit() -> None:
    dates = _dates(12)
    close = pd.DataFrame({"A": [100.0] * 7 + [110.0] * 5}, index=dates)
    cash = pd.Series(0.0, index=dates)
    d, trades = xs.run_candidate(_panel(close), _ind(dates, ["A"], 2, 95.0), cash,
                                 {"entry": "b1", "exit": "hold5", "industry": False}, start=dates[0])
    # Risk 0.5% on a 5% stop distance: 10% of equity, bought at the close of session 2, sold at the close of 7.
    assert d["invested"].iloc[2] == pytest.approx(0.1, rel=1e-2)
    assert d["invested"].iloc[6] > 0 and d["invested"].iloc[7] == 0
    assert len(trades) == 1 and trades["return"].iloc[0] == pytest.approx(1.1 * (1 - ss.COST) / (1 + ss.COST) - 1)


def test_stop_fills_at_gap_open_and_position_cap() -> None:
    dates = _dates(8)
    close = pd.DataFrame({"A": [100.0] * 8}, index=dates)
    panel = _panel(close)
    panel["low"] = close * 0.999
    panel["open"].iloc[4, 0] = 90.0
    panel["low"].iloc[4, 0] = 89.0
    cash = pd.Series(0.0, index=dates)
    d, trades = xs.run_candidate(panel, _ind(dates, ["A"], 2, 99.5), cash,
                                 {"entry": "b1", "exit": "ma20", "industry": False}, start=dates[0])
    assert d["invested"].iloc[2] == pytest.approx(0.2 / (1 + ss.COST), rel=1e-2)  # 0.5% stop: the 20% cap binds
    assert d["invested"].iloc[4] == 0
    assert trades["return"].iloc[0] == pytest.approx(0.9 * (1 - ss.COST) / (1 + ss.COST) - 1)


def test_quick_exit_half_at_2r_then_ema9() -> None:
    dates = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 3 + [111.0, 112.0, 105.0, 105.0, 105.0, 105.0, 105.0]}, index=dates)
    ind = _ind(dates, ["A"], 2, 95.0, "b3")
    ind["ema9"].iloc[5, 0] = 108.0  # the rest goes at the close of 5, under EMA9
    cash = pd.Series(0.0, index=dates)
    d, trades = xs.run_candidate(_panel(close), ind, cash, {"entry": "b3", "exit": "quick", "industry": False},
                                 start=dates[0])
    assert 0 < d["invested"].iloc[4] < d["invested"].iloc[2] and d["invested"].iloc[5] == 0
    proceeds = 0.5 * 1.11 * (1 - ss.COST) + 0.5 * 1.05 * (1 - ss.COST)
    assert trades["return"].iloc[0] == pytest.approx(proceeds / (1 + ss.COST) - 1)


def test_quick_exit_no_progress_by_session_3() -> None:
    dates = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=dates)
    cash = pd.Series(0.0, index=dates)
    d, _ = xs.run_candidate(_panel(close), _ind(dates, ["A"], 2, 95.0, "b3"), cash,
                            {"entry": "b3", "exit": "quick", "industry": False}, start=dates[0])
    assert d["invested"].iloc[4] > 0 and d["invested"].iloc[5] == 0


def test_industry_filter_and_market_gate() -> None:
    dates = _dates(5)
    ind = _ind(dates, ["A"], 2, 95.0)
    ind["industry"].iloc[2, 0] = 40.0
    assert not xs.signal_matrix(ind, {"entry": "b1", "industry": True}).any()
    assert xs.signal_matrix(ind, {"entry": "b1", "industry": False})[2, 0]
    ind["market"].iloc[2] = False
    assert not xs.signal_matrix(ind, {"entry": "b1", "industry": False}).any()


def test_industry_strength() -> None:
    dates = _dates(2)
    cols = ["a1", "a2", "a3", "b1", "b2", "b3", "c1"]
    rs = pd.DataFrame([[90, 80, 70, 10, 20, 30, 99]] * 2, index=dates, columns=cols, dtype=float)
    uni = pd.DataFrame(True, index=dates, columns=cols)
    industry = pd.Series(["A", "A", "A", "B", "B", "B", "C"], index=cols)
    out = xs.industry_strength(rs, uni, industry)
    assert out["a1"].iloc[0] == 100 and out["b2"].iloc[0] == 50 and np.isnan(out["c1"].iloc[0])  # C has 1 stock


def test_burst_signal_uses_only_data_to_the_close() -> None:
    n = 300
    dates = _dates(n, "1993-01-04")
    c = 20 * np.exp(np.linspace(0, 0.3, n))
    c[290:] *= 1.05
    close = pd.DataFrame({"A": c}, index=dates)
    panel = _panel(close)
    panel["high"], panel["low"] = close * 1.04, close * 0.99
    panel["high"].iloc[289, 0], panel["low"].iloc[289, 0] = c[289] * 1.005, c[289] * 0.995
    panel["volume"].iloc[289, 0] = 5e5
    panel["volume"].iloc[290, 0] = 3e6
    ind = xs.indicators(panel, pd.Series(c, index=dates), pd.Series({"A": "X"}))
    b3 = ind["entries"]["b3"]["A"]
    assert b3.iloc[290] and not b3.iloc[291]
    panel["close"] = close.copy()
    panel["close"].iloc[295:, 0] *= 10  # a later move does not change the signal at 290
    assert xs.indicators(panel, pd.Series(c, index=dates), pd.Series({"A": "X"}))["entries"]["b3"]["A"].iloc[290]
