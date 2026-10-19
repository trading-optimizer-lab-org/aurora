"""Tests for the v10 engine additions: progressive XG exits and the open-position limit."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc


def _setup(path: np.ndarray, ncols: int = 1):
    idx = pd.bdate_range("2020-01-01", periods=len(path))
    close = pd.DataFrame(np.tile(path[:, None], (1, ncols)), index=idx, columns=[f"S{i}" for i in range(ncols)])
    panel = {"open": close.copy(), "high": close * 1.001, "low": close * 0.999, "close": close.copy(),
             "volume": close * 0 + 1e6}
    ind = {k: close.rolling(n, min_periods=1).mean() for k, n in (("sma10", 10), ("sma20", 20), ("sma50", 50))}
    ind["adr"] = close * 0 + 0.05
    entries = pd.DataFrame(False, index=idx, columns=close.columns)
    entries.iloc[5, :] = True
    stops = close * 0.5
    return panel, ind, entries, stops, close


def _run(panel, ind, entries, stops, close, rule, trades=None, **kw):
    cash = pd.Series(0.0, index=close.index)
    return sc.simulate(panel, ind, entries, stops, rule, cash, close * 0 + 1.0, start=close.index[0],
                       trades=trades, **kw)


def test_xp_switches_to_the_slow_average_after_the_gain():
    # +3% a day for 40 days, then a pullback that breaks the 10-day average but not the 50-day one
    up = 10 * 1.03 ** np.arange(45)
    path = np.concatenate([np.full(5, 10.0), up, up[-1] * np.linspace(1, 0.9, 10)])
    panel, ind, entries, stops, close = _setup(path)
    fast: list = []
    _run(panel, ind, entries, stops, close, "XQC10", trades=fast)
    slow: list = []
    _run(panel, ind, entries, stops, close, "XG10_50_50_0", trades=slow)
    assert fast and fast[-1]["exit_date"] < close.index[-1]
    assert not slow or slow[-1]["exit_date"] == close.index[-1] or slow[-1]["return"] > fast[-1]["return"]


def test_xp_sells_a_third_on_day_d_and_moves_the_stop():
    path = np.concatenate([np.full(5, 10.0), 10 * 1.01 ** np.arange(30)])
    panel, ind, entries, stops, close = _setup(path)
    tr: list = []
    _run(panel, ind, entries, stops, close, "XG10_50_50_3", trades=tr)
    assert tr[0]["fraction"] == 1 / 3 and tr[0]["exit_date"] == close.index[8]


def test_max_pos_limits_open_positions():
    path = np.concatenate([np.full(5, 10.0), 10 * 1.01 ** np.arange(30)])
    panel, ind, entries, stops, close = _setup(path, ncols=6)
    full = _run(panel, ind, entries, stops, close, "XQC20", risk=0.01, cap=0.1)
    limited = _run(panel, ind, entries, stops, close, "XQC20", risk=0.01, cap=0.1, max_pos=2)
    assert full["invested"].iloc[10] > limited["invested"].iloc[10] > 0
    assert abs(limited["invested"].iloc[10] / full["invested"].iloc[10] - 2 / 6) < 0.02
