"""Tests for SelfModifyingStrategy online tuner."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.experimental.self_modifying_strategy import SelfModifyingStrategy


def _ma_signal(window: np.ndarray, params: dict) -> float:
    """Threshold momentum signal parameterised by ``thr``."""
    if window.size < 2:
        return 0.0
    ret = (window[-1] - window[0]) / max(window[0], 1e-9)
    thr = float(params.get("thr", 0.0))
    if ret > thr:
        return 1.0
    if ret < -thr:
        return -1.0
    return 0.0


def test_step_returns_position_in_unit_range():
    rng = np.random.default_rng(0)
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 200)))
    sms = SelfModifyingStrategy(
        signal_fn=_ma_signal,
        init_params={"thr": 0.005},
        window_size=32,
        eval_window=16,
        n_arms=3,
    )
    pos = sms.step(px)
    assert -1.0 <= pos <= 1.0


def test_step_records_history_when_window_sufficient():
    rng = np.random.default_rng(1)
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 200)))
    sms = SelfModifyingStrategy(
        signal_fn=_ma_signal,
        init_params={"thr": 0.005},
        window_size=32,
        eval_window=16,
        n_arms=3,
    )
    sms.step(px)
    assert len(sms.history) == 1
    assert "params" in sms.history[0]
    assert "sharpe" in sms.history[0]


def test_step_skips_search_with_short_window():
    sms = SelfModifyingStrategy(
        signal_fn=_ma_signal,
        init_params={"thr": 0.0},
        window_size=32,
        eval_window=16,
        n_arms=3,
    )
    # Only 5 prices: not enough for the eval window.
    pos = sms.step(np.array([100.0, 101.0, 99.0, 100.5, 101.2]))
    assert -1.0 <= pos <= 1.0
    assert len(sms.history) == 0


def test_constructor_validates_epsilon():
    with pytest.raises(ValueError):
        SelfModifyingStrategy(
            signal_fn=_ma_signal,
            init_params={"thr": 0.0},
            epsilon=2.0,
        )


def test_seed_makes_step_reproducible():
    rng = np.random.default_rng(2)
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 200)))
    a = SelfModifyingStrategy(
        signal_fn=_ma_signal, init_params={"thr": 0.005}, seed=7
    )
    b = SelfModifyingStrategy(
        signal_fn=_ma_signal, init_params={"thr": 0.005}, seed=7
    )
    assert a.step(px) == b.step(px)
