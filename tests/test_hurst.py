"""Tests for aurora.regime.hurst (Task J.5).

Run: uv run pytest aurora/tests/test_hurst.py -v
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from aurora.regime.hurst import (
    HurstResult,
    hurst_dfa,
    hurst_regime_filter,
    hurst_rs,
    rolling_hurst,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _random_walk(n: int = 4096, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, n)


def _ar1(n: int = 4096, rho: float = 0.5, seed: int = 11) -> np.ndarray:
    """AR(1): x_t = rho * x_{t-1} + e_t. rho > 0 -> persistent."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0.0, 1.0, n)
    x = np.zeros(n, dtype=float)
    for t in range(1, n):
        x[t] = rho * x[t - 1] + e[t]
    return x


def _anti_persistent(n: int = 4096, seed: int = 13) -> np.ndarray:
    """First-difference of white noise -> anti-persistent (H < 0.5)."""
    rng = np.random.default_rng(seed)
    w = rng.normal(0.0, 1.0, n + 1)
    return np.diff(w)


# ---------------------------------------------------------------------------
# basic shape / API
# ---------------------------------------------------------------------------


def test_hurst_rs_returns_result_object():
    arr = _random_walk(n=2048)
    res = hurst_rs(arr)
    assert isinstance(res, HurstResult)
    assert res.method == "rs"
    assert 0.0 <= res.hurst <= 1.0
    assert res.log_lags.shape == res.log_rs.shape
    assert res.log_lags.size >= 2
    # 'unknown' is emitted when the fit produced NaN (unstable slope);
    # finite hurst values map to the three regime labels via _classify.
    assert res.interpretation in {
        "trending", "random_walk", "mean_reverting", "unknown",
    }


def test_hurst_dfa_returns_result_object():
    arr = _random_walk(n=2048)
    res = hurst_dfa(arr)
    assert isinstance(res, HurstResult)
    assert res.method == "dfa"
    assert 0.0 <= res.hurst <= 1.0
    assert res.log_lags.size == res.log_rs.size >= 2
    assert res.interpretation in {
        "trending", "random_walk", "mean_reverting", "unknown",
    }


def test_hurst_rs_rejects_short_series():
    with pytest.raises(ValueError):
        hurst_rs(np.zeros(10))


def test_hurst_dfa_rejects_short_series():
    with pytest.raises(ValueError):
        hurst_dfa(np.zeros(10))


# ---------------------------------------------------------------------------
# theoretical regimes
# ---------------------------------------------------------------------------


def test_random_walk_h_05():
    """Random walk -> H approx 0.5 (R/S on returns)."""
    arr = _random_walk(n=8192, seed=42)
    res = hurst_rs(arr, lags=(10, 20, 40, 80, 160, 320))
    assert abs(res.hurst - 0.5) < 0.1


def test_persistent_h_above_05():
    """AR(1) rho=0.5 -> persistent -> H > 0.5."""
    arr = _ar1(n=8192, rho=0.5, seed=21)
    res = hurst_rs(arr, lags=(10, 20, 40, 80, 160, 320))
    assert res.hurst > 0.5


def test_mean_reverting_h_below_05():
    """Anti-persistent (diff of white noise) -> H < 0.5."""
    arr = _anti_persistent(n=8192, seed=33)
    res = hurst_rs(arr, lags=(10, 20, 40, 80, 160, 320))
    assert res.hurst < 0.5


def test_dfa_random_walk_close_to_05():
    """DFA on i.i.d. returns -> H approx 0.5."""
    arr = _random_walk(n=8192, seed=44)
    res = hurst_dfa(arr)
    assert abs(res.hurst - 0.5) < 0.1


def test_dfa_matches_rs_within_tolerance():
    """Same series via both methods produces similar H."""
    arr = _random_walk(n=8192, seed=55)
    rs = hurst_rs(arr, lags=(10, 20, 40, 80, 160, 320))
    dfa = hurst_dfa(arr)
    assert abs(rs.hurst - dfa.hurst) < 0.15


def test_dfa_order2_runs():
    """Quadratic detrending must execute and stay in [0,1]."""
    arr = _random_walk(n=4096, seed=77)
    res = hurst_dfa(arr, order=2)
    assert 0.0 <= res.hurst <= 1.0


# ---------------------------------------------------------------------------
# rolling
# ---------------------------------------------------------------------------


def test_rolling_hurst_returns_series():
    idx = pd.date_range("2010-01-01", periods=512, freq="B")
    s = pd.Series(_random_walk(n=512, seed=3), index=idx)
    h = rolling_hurst(s, window=128, method="rs")
    assert isinstance(h, pd.Series)
    assert len(h) == 512
    # first window-1 entries are NaN
    assert h.iloc[:127].isna().all()
    # later entries should be mostly finite
    tail = h.iloc[127:]
    assert tail.notna().sum() > 0
    finite = tail.dropna()
    assert ((finite >= 0.0) & (finite <= 1.0)).all()


@pytest.mark.slow
def test_rolling_hurst_dfa():
    idx = pd.date_range("2010-01-01", periods=600, freq="B")
    s = pd.Series(_random_walk(n=600, seed=5), index=idx)
    h = rolling_hurst(s, window=200, method="dfa")
    assert h.iloc[:199].isna().all()
    finite = h.dropna()
    assert finite.size > 0
    assert ((finite >= 0.0) & (finite <= 1.0)).all()


def test_rolling_hurst_window_too_small():
    with pytest.raises(ValueError):
        rolling_hurst(_random_walk(n=200), window=10)


def test_rolling_hurst_unknown_method():
    with pytest.raises(ValueError):
        rolling_hurst(_random_walk(n=512), window=128, method="bogus")


# ---------------------------------------------------------------------------
# regime filter
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_regime_filter_classifies_correctly():
    """Persistent AR(1) segment should be predominantly labelled 'trending'."""
    n = 2048
    arr = _ar1(n=n, rho=0.7, seed=99)
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    s = pd.Series(arr, index=idx)
    labels = hurst_regime_filter(
        s, window=512, trend_threshold=0.55, mr_threshold=0.45,
    )
    valid = labels.dropna()
    assert valid.size > 0
    counts = valid.value_counts()
    # Strongly persistent series: 'trending' must be the dominant non-random
    # label and outnumber 'mean_reverting'.
    n_trend = int(counts.get("trending", 0))
    n_mr = int(counts.get("mean_reverting", 0))
    assert n_trend > n_mr


def test_regime_filter_label_values():
    s = pd.Series(_random_walk(n=512, seed=2))
    labels = hurst_regime_filter(s, window=128)
    valid = labels.dropna().unique().tolist()
    for v in valid:
        # 'unknown' is the new sentinel for an unstable per-window fit
        # within the populated region (distinct from the NaN warm-up).
        assert v in {"trending", "random", "mean_reverting", "unknown"}


def test_regime_filter_threshold_validation():
    s = pd.Series(_random_walk(n=512, seed=2))
    with pytest.raises(ValueError):
        hurst_regime_filter(s, window=128, trend_threshold=0.4,
                            mr_threshold=0.5)


# ---------------------------------------------------------------------------
# clip_warn / nan_on_unstable
# ---------------------------------------------------------------------------


def _force_unstable_loglog(monkeypatch, slope: float):
    """Patch the internal loglog fit to return a slope outside [0, 1]."""
    import aurora.regime.hurst as hurst_mod

    def _fake(log_x, log_y):
        return float(slope), 0.0, 0.99

    monkeypatch.setattr(hurst_mod, "_loglog_fit", _fake)


def test_hurst_clip_warns_on_unstable(monkeypatch):
    """When the raw slope is outside [0, 1], a RuntimeWarning is emitted."""
    _force_unstable_loglog(monkeypatch, slope=1.4)
    arr = _random_walk(n=2048)
    with pytest.warns(RuntimeWarning, match=r"outside \[0, 1\]"):
        res = hurst_rs(arr, nan_on_unstable=False)
    # explicit clip behavior keeps the value in range
    assert 0.0 <= res.hurst <= 1.0


def test_hurst_clip_warn_disabled(monkeypatch):
    """clip_warn=False suppresses the warning while still clipping."""
    _force_unstable_loglog(monkeypatch, slope=-0.3)
    arr = _random_walk(n=2048)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # raise on any warning
        res = hurst_rs(arr, clip_warn=False, nan_on_unstable=False)
    assert res.hurst == 0.0  # clipped from -0.3


def test_hurst_nan_on_unstable_returns_nan(monkeypatch):
    """nan_on_unstable=True (the default) returns NaN instead of clipping."""
    _force_unstable_loglog(monkeypatch, slope=1.7)
    arr = _random_walk(n=2048)
    with pytest.warns(RuntimeWarning):
        res = hurst_rs(arr, nan_on_unstable=True)
    assert np.isnan(res.hurst)


def test_hurst_dfa_clip_warns_on_unstable(monkeypatch):
    _force_unstable_loglog(monkeypatch, slope=1.2)
    arr = _random_walk(n=2048)
    with pytest.warns(RuntimeWarning, match=r"DFA slope"):
        res = hurst_dfa(arr, nan_on_unstable=False)
    assert 0.0 <= res.hurst <= 1.0


def test_hurst_default_nan_on_unstable(monkeypatch):
    """The default nan_on_unstable is now True (was False); a clipped slope
    must surface as NaN unless the caller opts back into clipping.
    """
    _force_unstable_loglog(monkeypatch, slope=1.7)
    arr = _random_walk(n=2048)
    with pytest.warns(RuntimeWarning):
        res_rs = hurst_rs(arr)
    with pytest.warns(RuntimeWarning):
        res_dfa = hurst_dfa(arr)
    assert np.isnan(res_rs.hurst)
    assert np.isnan(res_dfa.hurst)
