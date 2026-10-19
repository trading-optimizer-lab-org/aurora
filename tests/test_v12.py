"""Tests for the v12 engine additions: ladder exits, open-risk limit and sector limit."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc


def _setup(path: np.ndarray, ncols: int = 1, stop_frac: float = 0.95):
    idx = pd.bdate_range("2020-01-01", periods=len(path))
    close = pd.DataFrame(np.tile(path[:, None], (1, ncols)), index=idx, columns=[f"S{i}" for i in range(ncols)])
    panel = {"open": close.copy(), "high": close * 1.001, "low": close * 0.999, "close": close.copy(),
             "volume": close * 0 + 1e6}
    ind = {k: close.rolling(n, min_periods=1).mean() for k, n in (("sma10", 10), ("sma20", 20), ("sma50", 50))}
    ind["adr"] = close * 0 + 0.05
    entries = pd.DataFrame(False, index=idx, columns=close.columns)
    entries.iloc[5, :] = True
    return panel, ind, entries, close * stop_frac, close


def _run(panel, ind, entries, stops, close, rule, trades=None, **kw):
    return sc.simulate(panel, ind, entries, stops, rule, pd.Series(0.0, index=close.index), close * 0 + 1.0,
                       start=close.index[0], trades=trades, **kw)


def test_ladder_sells_thirds_at_one_and_two_r():
    path = np.concatenate([np.full(6, 10.0), 10 * 1.02 ** np.arange(1, 30)])
    panel, ind, entries, stops, close = _setup(path)
    tr: list = []
    _run(panel, ind, entries, stops, close, "XN1_2_20_0", trades=tr)
    assert [round(t["fraction"], 3) for t in tr[:2]] == [0.333, 0.5]
    assert tr[0]["exit"] >= 10.5 - 1e-6 and tr[1]["exit"] >= 11.0 - 1e-6


def test_ladder_time_stop_exits_a_flat_trade():
    path = np.concatenate([np.full(6, 10.0), np.full(20, 9.9)])
    panel, ind, entries, stops, close = _setup(path, stop_frac=0.8)
    ind["sma50"] = close * 0 + 1.0  # keep the trail out of the way
    tr: list = []
    _run(panel, ind, entries, stops, close, "XN1_2_50_5", trades=tr)
    assert tr and tr[0]["exit_date"] == close.index[10]


def test_max_heat_limits_new_entries():
    path = np.concatenate([np.full(5, 10.0), 10 * 1.01 ** np.arange(30)])
    panel, ind, entries, stops, close = _setup(path, ncols=6)
    full = _run(panel, ind, entries, stops, close, "XQC20", risk=0.01, cap=0.5)
    capped = _run(panel, ind, entries, stops, close, "XQC20", risk=0.01, cap=0.5, max_heat=0.03)
    # 1% risk with a 5% stop is a 20% position: three fit under a 3% open-risk limit
    assert full["invested"].iloc[10] > 0.95 and abs(capped["invested"].iloc[10] - 3 * 0.2 * 1.01 ** 5) < 0.03


def test_max_per_group_limits_one_industry():
    path = np.concatenate([np.full(5, 10.0), 10 * 1.01 ** np.arange(30)])
    panel, ind, entries, stops, close = _setup(path, ncols=6)
    groups = np.array([0, 0, 0, 1, 1, -1])
    full = _run(panel, ind, entries, stops, close, "XQC20", risk=0.01, cap=0.1)
    lim = _run(panel, ind, entries, stops, close, "XQC20", risk=0.01, cap=0.1, groups=groups, max_per_group=1)
    assert abs(lim["invested"].iloc[10] / full["invested"].iloc[10] - 3 / 6) < 0.03
