"""Tests for quantforge.research.shadow_mode."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.research.shadow_mode import ShadowModeRunner, ShadowReport


def _flat(prices: pd.Series) -> np.ndarray:
    return np.zeros(len(prices))


def _long(prices: pd.Series) -> np.ndarray:
    return np.ones(len(prices))


def test_basic_run(synthetic_prices_daily):
    r = ShadowModeRunner(live_signal_fn=_flat, shadow_signal_fn=_long)
    rep = r.run(synthetic_prices_daily)
    assert isinstance(rep, ShadowReport)
    assert rep.n_steps == len(synthetic_prices_daily) - 1
    assert len(rep.live_pnl) == rep.n_steps
    assert len(rep.shadow_pnl) == rep.n_steps
    assert rep.live_total == 0.0  # flat signal


def test_summary_keys(synthetic_prices_daily):
    r = ShadowModeRunner(live_signal_fn=_long, shadow_signal_fn=_flat)
    rep = r.run(synthetic_prices_daily)
    s = r.summary(rep)
    for k in ("live_total", "shadow_total", "edge",
              "correlation", "tracking_error", "n_steps"):
        assert k in s


def test_signal_length_mismatch():
    def bad(prices: pd.Series) -> np.ndarray:
        return np.zeros(5)

    r = ShadowModeRunner(live_signal_fn=bad, shadow_signal_fn=_long)
    px = pd.Series(np.linspace(100, 110, 50))
    with pytest.raises(ValueError):
        r.run(px)


def test_invalid_prices_type():
    r = ShadowModeRunner(live_signal_fn=_long, shadow_signal_fn=_long)
    with pytest.raises(TypeError):
        r.run(np.linspace(1, 2, 10))


def test_too_few_observations():
    r = ShadowModeRunner(live_signal_fn=_long, shadow_signal_fn=_long)
    with pytest.raises(ValueError):
        r.run(pd.Series([1.0, 2.0]))


def test_non_callable_signal():
    with pytest.raises(TypeError):
        ShadowModeRunner(live_signal_fn=None, shadow_signal_fn=_long)
    with pytest.raises(TypeError):
        ShadowModeRunner(live_signal_fn=_long, shadow_signal_fn=42)


def test_correlation_finite(synthetic_prices_daily):
    r = ShadowModeRunner(live_signal_fn=_long, shadow_signal_fn=_long)
    rep = r.run(synthetic_prices_daily)
    assert -1.0 <= rep.correlation <= 1.0
