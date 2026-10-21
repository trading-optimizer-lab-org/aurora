"""v22 checks: indicators, candles, signal exits, the top-30 cut, the activity rule and the SPA test."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research import v14_core as core
from aurora.research import v19_grid as v19
from aurora.research import v22_intra as vin
from aurora.research import v22_ta as ta

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R22 = _script("run_v22")


def _daily(n: int = 60, k: int = 3) -> dict:
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


def test_grid_size() -> None:
    n = sum(len(core.grid(d)) for d in {**ta.DAILY_DIMS, **vin.INTRA_DIMS}.values())
    assert n == 88254


def test_rsi_extremes() -> None:
    ta._C.clear()
    D = _daily()
    D["C"][:, 0] = np.r_[np.linspace(10, 20, 30), np.linspace(20, 10, 30)]
    r = ta.rsi(D, 14)
    assert r[29, 0] > 95 and r[59, 0] < 15


def test_candles() -> None:
    D = _daily()
    D["O"][10, 0], D["C"][10, 0] = 10.5, 9.8  # red
    D["O"][11, 0], D["C"][11, 0] = 9.7, 10.8  # green, engulfing
    assert ta.candle(D, "bull_engulf")[11, 0] and not ta.candle(D, "bear_engulf")[11, 0]
    D["O"][20, 1], D["C"][20, 1], D["H"][20, 1], D["L"][20, 1] = 10.0, 10.1, 10.15, 9.0  # long lower shadow
    assert ta.candle(D, "hammer")[20, 1]


def test_specs_keep_thirty_a_day_by_priority() -> None:
    ta._C.clear()
    D = _daily(60, 50)
    D["C"][40] = np.linspace(5.0, 9.0, 50)  # a fall of 10-50%: RSI(2) very low for all
    D["O"][40], D["P"] = D["C"][40], D["C"].copy()
    g = {"n": 2, "lvl": 25, "side": "long", "trend": "none", "entry": "close", "exit": "t3", "stop": "none",
         "band": "3-8"}
    sp, _ = ta.specs(D, {}, "RS_RSI", g)
    day40 = [s for s in sp if s.t == 40]
    assert 0 < len(day40) <= ta.TOP_K


def test_signal_exit_leaves_at_the_first_true_close() -> None:
    D = _daily()
    xm = np.zeros_like(D["C"], bool)
    xm[14, 0] = True
    s = v19.Spec(0, 11, "open", 1, 40, np.nan, np.nan, np.nan, "time", 0.0)
    p = ta.path(D, s, xm)
    assert p is not None and len(p[1]) == 4 and p[6] == (0, 2)


def test_activity_rule_blocks_sparse_configurations() -> None:
    months = pd.date_range("2016-01-01", periods=36, freq="MS")
    Cn = np.zeros((36, 2))
    Cn[:, 0] = 3  # three trades every month
    Cn[::12, 1] = 60  # many trades in a few months
    assert R22.eligible(Cn, np.asarray(months < pd.Timestamp("2018-01-01"))).tolist() == [True, False]


def test_spa_separates_noise_from_signal() -> None:
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.05, (130, 50))
    assert R22.spa(noise, B=300)[0] > 0.10
    strong = noise.copy()
    strong[:, 7] += 0.04
    p, best, t = R22.spa(strong, B=300)
    assert p < 0.05 and best == 7 and t > 3


def test_runner_flags_wait_for_the_rise() -> None:
    # a flag at 13 (a pole of 24% from 10.5, the prior close 10) before the runner's 40% rise to 14, then one at 16
    c = np.array([10.5] * 20 + [11.0, 11.6, 12.2, 12.8, 13.0, 12.7, 12.6, 12.65, 12.9, 13.5, 14.5, 15.5, 16.0,
                                15.6, 15.5, 15.55, 15.9, 16.3] + [16.3] * 9)
    o = np.r_[c[0], c[:-1]]
    b = (np.arange(len(c)), o, np.maximum(c * 1.001, o), np.minimum(c * 0.999, o), c)
    g = {"pole": 0.20, "retrace": 0.50}
    assert vin.entry("IF_FLAG", {**g, "scope": "gapup"}, 1, b, c, {}, pc=10.0)[0] == 29
    assert vin.entry("IF_FLAG", {**g, "scope": "runner"}, 1, b, c, {}, pc=10.0)[0] == 37  # 13.5 broke before 14
