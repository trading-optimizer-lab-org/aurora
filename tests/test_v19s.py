"""v19s checks: the joint book's gross cap, the bootstrap draws and the ruin statistics."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("run_v19s_under_test",
                                              Path(__file__).resolve().parents[1] / "scripts" / "run_v19s.py")
S = importlib.util.module_from_spec(spec)
sys.modules["run_v19s_under_test"] = S
spec.loader.exec_module(S)


def test_joint_book_caps_gross_exposure() -> None:
    dates = pd.bdate_range("2020-01-01", periods=10)
    paths = [(0, np.full(5, 0.01), 1.0, 0.8), (1, np.full(3, 0.02), 0.5, 0.8), (2, np.full(2, -0.01), 0.2, 0.3)]
    s1 = S.joint_book(paths, dates, 1.0)
    s2 = S.joint_book(paths, dates, 2.0)
    assert abs(s1.iloc[1] - 0.008) < 1e-12  # the second trade does not fit in 1x
    assert abs(s2.iloc[1] - (0.008 + 0.016)) < 1e-12 and abs(s2.iloc[2] - (0.008 + 0.016 - 0.003)) < 1e-12


def test_bootstrap_draws_and_ruin() -> None:
    idx = S.draws(500)
    assert idx.shape == (S.PATHS, 252 * S.YEARS) and idx.min() >= 0 and idx.max() < 500
    runs = (np.diff(idx, axis=1) == 1).mean()
    assert 0.9 < runs < 0.99  # blocks of about 20 sessions
    calm = S.bootstrap(np.full(500, 0.001), idx)
    assert calm["p_dd50"] == 0.0 and abs(calm["cagr_med"] - (1.001 ** 252 - 1)) < 1e-6
    r = np.full(500, 0.001)
    r[::50] = -0.6
    bad = S.bootstrap(r, idx)
    assert bad["p_dd50"] > 0.9 and bad["p_dd90"] > 0.5
