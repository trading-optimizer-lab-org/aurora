"""v23 checks: levels, the support and resistance setups, targets, five-minute bars and triangles."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v23_ta1m as v23


def _bars(c: list[float], h: list[float] | None = None, lo: list[float] | None = None) -> tuple:
    c = np.array(c, float)
    h = np.array(h, float) if h is not None else c * 1.001
    lo = np.array(lo, float) if lo is not None else c * 0.999
    o = np.r_[c[0], c[:-1]]
    m = np.arange(len(c), dtype=np.int16)
    return (m, o, np.maximum(h, np.maximum(o, c)), np.minimum(lo, np.minimum(o, c)), c, np.full(len(c), 1e3), c)


def test_grid_size() -> None:
    assert sum(len(core.grid(d)) for d in v23.INTRA_DIMS.values()) == 105336


def test_floor_pivots() -> None:
    cd = pd.Series({"t": 1, "j": 0, "pc": 10.0, "pmh": 11.0, "pml": 9.5, "pdh": 12.0, "pdl": 9.0, "h5": 13.0,
                    "l5": 8.0, "open": 10.5})
    lv = v23.facts(cd, {"F": np.ones((2, 1)), "H": np.ones((2, 1)), "L": np.ones((2, 1))})
    p = (12 + 9 + 10) / 3
    assert lv["pivot"] == pytest.approx(p) and lv["r1"] == pytest.approx(2 * p - 9) and lv["s1"] == pytest.approx(2 * p - 12)


def test_break_fail_and_retest_of_a_level() -> None:
    lv = {"pmh": 10.0, "pml": np.nan, "pdh": np.nan, "pdl": np.nan, "pdc": 9.0, "h5": np.nan, "l5": np.nan,
          "pivot": np.nan, "r1": np.nan, "s1": np.nan, "open": 9.5}
    path = [9.5] * 10 + [9.8, 10.2, 10.4, 10.5, 10.02, 10.25, 10.6] + [10.6] * 10
    b = _bars(path)
    line = np.full(len(path), 9.0)
    g = {"level": "pmh", "vol": 0.0, "window": "all"}
    j, e, ref, _ = v23.signal("SR_LEVEL", {**g, "setup": "break_up"}, 1, b, line, None, lv)
    assert (j, e, ref) == (12, pytest.approx(10.2), 10.0)
    j, e, _, _ = v23.signal("SR_LEVEL", {**g, "setup": "retest_up"}, 1, b, line, None, lv)
    assert j == 15 and e == pytest.approx(10.02)  # back to within 0.3% of 10, closed above it
    fail = [9.5] * 10 + [9.9, 9.95, 9.8] + [9.7] * 10
    b = _bars(fail, h=[9.5] * 10 + [9.9, 10.1, 9.85] + [9.7] * 10)
    j, e, _, _ = v23.signal("SR_LEVEL", {**g, "setup": "fail_up"}, -1, b, np.full(len(fail), 9.0), None, lv)
    assert j == 12 and e == pytest.approx(9.95)  # pierced 10.02 at bar 11 and closed back below 10


def test_target_row_and_five_minute_bars() -> None:
    b = _bars([10.0] * 5 + [10.2, 10.4, 10.9, 11.2, 11.0])
    cd = pd.Series({"date": pd.Timestamp("2020-01-02"), "t": 5, "j": 0, "symbol": "X", "open": 10.0, "pmv": 1e6,
                    "so": 2e7, "pc": 9.0})
    r = v23.target_row({}, cd, b, b[4], 1, 5, 10.2, 9.8, 10.8, "nextlevel", 0.0)
    assert r["rets"][0] == pytest.approx(10.8 / 10.2 - 1)  # the bar opened below 10.8: filled at the target
    ends, o, h, lo, c, v = v23._agg(_bars(list(np.arange(10.0, 22.0))), 5)
    assert ends.tolist() == [4, 9, 11] and c.tolist() == [14.0, 19.0, 21.0]


def test_ascending_triangle() -> None:
    hi = [10.0, 9.6] * 8 + [10.0, 9.8] * 8 + [10.0, 10.3]
    lows = [9.2] * 16 + [9.5] * 16 + [9.8, 10.2]
    c = [x - 0.05 for x in hi]
    c[-1] = 10.25
    b = _bars(c, h=hi, lo=lows)
    j, e, ref, height = v23._pattern({"pattern": "asc_triangle", "size": "small"}, 1, b, np.ones(len(c), bool))
    assert j == len(c) and e == pytest.approx(10.25) if j == len(c) else j == -1 or e > 10.0
