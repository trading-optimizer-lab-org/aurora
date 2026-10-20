"""v21 checks on synthetic data: the grid, the new exits, the close-based stop, the regime and the new setups."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v21_grid as v21

TABLE = {}


def _daily(n: int = 40, k: int = 3) -> dict:
    dates = pd.bdate_range("2020-01-01", periods=n)
    C = np.full((n, k), 10.0)
    D = {"dates": dates, "O": C.copy(), "H": C * 1.01, "L": C * 0.99, "C": C.copy(), "P": C.copy(),
         "F": np.ones_like(C), "DV": np.full_like(C, 5e6), "SO": np.full_like(C, 5e7),
         "valid": np.ones_like(C, bool), "new": np.zeros_like(C, bool)}
    D["new"][0] = True
    D["valid1"] = np.vstack([np.zeros((1, k), bool), D["valid"][:-1]]) & ~D["new"]
    D["P1"] = np.vstack([np.full((1, k), np.nan), D["P"][:-1]])
    D["DV1"] = np.vstack([np.full((1, k), np.nan), D["DV"][:-1]])
    return D


def test_grid_is_five_times_v20() -> None:
    n = sum(len(core.grid(d)) for d in {**v21.INTRA_DIMS, **v21.DAILY_DIMS}.values())
    assert n == 192114 and 4.9 < n / 38762 < 5.1
    for d in {**v21.INTRA_DIMS, **v21.DAILY_DIMS}.values():
        for vals in d.values():
            assert all(not (isinstance(x, float) and np.isnan(x)) for x in vals)


def test_green_exit_and_close_stop_on_daily_paths() -> None:
    D = _daily()
    D["C"][13, 0] = 10.2  # the first close above the prior close for a short
    s = v19.Spec(0, 11, "open", -1, 10, np.nan, np.nan, np.nan, "green", 0.0)
    assert len(v19.path19(D, s, TABLE, 1.0, gross=True)[1]) == 3
    D["H"][12, 1], D["C"][12, 1] = 16.0, 14.0  # the high passes 15 but the close does not: a close stop holds
    D["C"][14, 1] = 16.0
    s = v19.Spec(1, 11, "open", -1, 10, np.nan, np.nan, np.nan, "time", 0.0, 0.5)
    _, r, _, _ = v19.path19(D, s, TABLE, 1.0, gross=True)
    assert len(r) == 4 and r.sum() == pytest.approx(-(16.0 - 10.0) / 10.0)


def test_carry_close_level_and_g5() -> None:
    D = _daily()
    D["C"][11, 0], D["C"][12, 0] = 9.5, 9.8  # down, then up: a short leaves at the first green close
    assert len(v19.carry(D, 10, 0, -1, 10.0, 10.0, np.inf, "g5")) == 2
    D["C"][11, 1] = 13.5  # above a 30% close-based level of 13
    assert len(v19.carry(D, 10, 1, -1, 10.0, 10.0, np.inf, "d5", 13.0)) == 1


def test_regime_uses_the_prior_20_sessions() -> None:
    dates = pd.bdate_range("2020-01-01", periods=60)
    close = pd.Series(np.r_[np.linspace(100, 120, 30), np.linspace(120, 90, 30)], index=dates)
    v21.set_regime({"etf_close": pd.DataFrame({"IWM": close})}, dates)
    up, down = v21.regime("iwm_up"), v21.regime("iwm_down")
    assert not up[:21].any() and up[25] and down[59] and not (up & down).any()


def test_new_daily_setups() -> None:
    D = _daily()
    D["C"][10, 0] = D["P"][10, 0] = 15.0  # +50%
    D["O"][11, 0] = 17.0  # opens 13% above it the next day
    v21.set_regime({"etf_close": pd.DataFrame({"IWM": pd.Series(100.0, index=D["dates"])})}, D["dates"])
    g = {"day1": 0.5, "gap2": 0.10, "hold": 2, "stop": "c50", "exit": "time", "band": "10-20", "regime": "any"}
    sp = v21.daily_specs(D, {}, "RX_DAY2GAP", g)
    assert [(s.t, s.kind, s.side) for s in sp] == [(11, "open", -1)] and sp[0].cstop == 0.5
    assert not v21.daily_specs(D, {}, "RX_DAY2GAP", {**g, "gap2": 0.20})
