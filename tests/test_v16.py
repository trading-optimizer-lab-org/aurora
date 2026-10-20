"""v16 checks on small synthetic bars."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_intraday as vi
from aurora.research import v16_small as v16


def _bars(prices: list[float]) -> tuple:
    p = np.array(prices, dtype=np.float32)
    m = np.arange(len(p), dtype=np.int16)
    return (m, p, p * 1.001, p * 0.999, p, np.full(len(p), 1000, np.float32), p)


def test_vwap_touch_cover() -> None:
    b = _bars([10.0] * 5 + [12.0, 11.0, 10.5, 9.9, 9.8])
    line = np.full(10, 10.2, dtype=np.float32)
    ex = v16.exit16(-1, 5, 12.0, 13.0, "vwaptouch", b, line)
    assert ex == pytest.approx(10.2)


def test_red_to_green_entry() -> None:
    b = _bars([9.0, 9.2, 9.6, 10.2, 10.4])
    cd = pd.Series({"pc": 10.0})
    side, j, entry, stop, mode = v16._entry("L3_R2G", {"within": 30, "exit": "close"}, b, vi.vwap(b[4], b[5], b[6]),
                                           cd)
    assert side == 1 and j == 3 and entry == pytest.approx(10.2) and stop == pytest.approx(9.0 * 0.999, rel=1e-5)
