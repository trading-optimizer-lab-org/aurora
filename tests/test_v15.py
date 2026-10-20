"""v15 checks on small synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v15_ah as v15


def test_calibration_cells_and_pooling() -> None:
    ev = pd.DataFrame({"price": [1.5] * 40 + [3.0] * 10, "so": [5e6] * 40 + [np.nan] * 10,
                       "borrowable": [True] * 30 + [False] * 10 + [True] * 10,
                       "fee": [20.0] * 30 + [np.nan] * 10 + [50.0] * 10})
    t = v15.calibrate(ev)
    assert t[("<2", "<10M")][0] == pytest.approx(0.75) and t[("<2", "<10M")][1] == pytest.approx(20.0)
    assert t[("2-5", "unknown")][0] == pytest.approx(1.0)  # 10 events < 30: the pooled $2-5 band
    p, fee = v15.lookup(t, np.array([1.5]), np.array([5e6]))
    assert p[0] == pytest.approx(0.75) and fee[0] == pytest.approx(20.0)


def test_book_scales_shorts_by_availability_and_charges_nights() -> None:
    d = pd.Timestamp("2020-01-02")
    tr = pd.DataFrame([{"date": d, "symbol": "X", "pnl_date": d, "minute": 0, "side": -1, "entry": 10.0,
                        "exit": 9.0, "stop": np.nan, "price": 10.0, "liq": np.inf, "prio": 1.0, "nights": 1,
                        "so": 5e6, "ah_in": False, "ah_out": False}])
    table = {("10-20", "<10M"): (0.5, 36.0, 50)}
    r = v15.book(tr, pd.DatetimeIndex([d]), table, 1.0, fixed=True)
    cost = 2 * 0.001 + 2 * 0.005 / 10 + 0.36 / 360
    assert r.iloc[0] == pytest.approx(0.05 * 0.5 * (0.1 - cost))


def _ah_store() -> v15.AHStore:
    m = np.arange(0, 30, dtype=np.int16)
    c = np.r_[np.full(5, 10.0), np.full(25, 9.4)].astype(np.float32)
    arrays = {"m": m, "o": c, "h": c * 1.001, "l": c * 0.999, "c": c, "v": np.full(30, 100, np.float32), "vw": c}
    cands = pd.DataFrame([{"date": pd.Timestamp("2020-01-02"), "symbol": "X", "off": 0, "n": 30, "c16": 10.0,
                           "hi": 12.0, "day_ret": 0.6, "nxt_date": pd.Timestamp("2020-01-03"), "nxt_open": 8.0,
                           "nxt_close": 7.5, "pm08": 8.5, "pm925": 8.2, "so": 5e6}])
    return v15.AHStore(cands, arrays)


def test_after_hours_fade_and_night_short() -> None:
    ah = _ah_store()
    t = v15.ah1_trade(ah, 0, 0.05, None)
    assert t is not None and t["entry"] == pytest.approx(9.4) and t["exit"] == pytest.approx(8.0)
    assert t["nights"] == 1 and t["pnl_date"] == pd.Timestamp("2020-01-03")
    n = v15.ah4_trade(ah, 0, "pm925")
    assert n["entry"] == pytest.approx(10.0) and n["exit"] == pytest.approx(8.2) and n["ah_out"]
