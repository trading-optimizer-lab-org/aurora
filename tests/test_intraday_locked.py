"""Tests for the 2021+ splice of the one-shot locked test (scripts/run_intraday_locked.py)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_intraday_locked.py"
_spec = importlib.util.spec_from_file_location("run_intraday_locked", _PATH)
assert _spec is not None and _spec.loader is not None
lk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lk)


def _raw(index: pd.DatetimeIndex, close: np.ndarray, volume: float, factor: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "adj_close": close * factor, "volume": volume, "stock_splits": 0.0}, index=index)


def test_splice_factor_needs_agreement():
    idx = pd.bdate_range("2020-09-01", "2020-12-31")
    old = pd.Series(100.0, index=idx)
    assert lk.splice_factor(old, old / 4) == 4.0
    noisy = old / 4 * (1 + 0.03 * (np.arange(len(idx)) % 2))
    assert lk.splice_factor(old, noisy) is None
    assert lk.splice_factor(old.iloc[-10:], old.iloc[-10:]) is None


def test_extend_panel_scales_new_rows_and_counts_coverage():
    old_idx = pd.bdate_range("2020-01-01", "2020-12-31")
    new_idx = pd.bdate_range("2020-09-01", "2021-03-31")
    cal = old_idx.union(new_idx)
    cols = ["A", "B", "C", "D"]
    base = pd.DataFrame(100.0, index=old_idx, columns=cols)
    base.loc["2020-06-01":, "C"] = np.nan  # not trading at the end of 2020
    panel = {f: base.astype(np.float32) for f in ("open", "high", "low", "close")}
    panel["volume"] = pd.DataFrame(1000.0, index=old_idx, columns=cols).astype(np.float32)
    raw = {"A": _raw(new_idx, np.full(len(new_idx), 25.0), 4000.0),  # a 4:1 split after 2020
           "B": _raw(new_idx, np.full(len(new_idx), 100.0), 1000.0),
           "D": _raw(new_idx, np.where(new_idx > "2021-01-15", -1.0, 100.0), 1000.0)}  # bad prices in 2021
    ext, cov = lk.extend_panel(panel, raw, cal)
    new_rows = ext["close"].loc["2021-01-01":]
    assert np.allclose(new_rows["A"], 100.0) and np.allclose(ext["volume"].loc["2021-01-01":, "A"], 1000.0)
    assert np.allclose(new_rows["B"], 100.0)
    assert new_rows["C"].isna().all() and new_rows["D"].isna().all()
    assert cov == {"inactive_end_2020": 1, "no_yahoo_data": 0, "splice_mismatch": 0, "failed_checks": 1, "spliced": 2}
    assert (ext["close"].loc[:"2020-12-31"].fillna(-1) == panel["close"].fillna(-1)).all().all()
