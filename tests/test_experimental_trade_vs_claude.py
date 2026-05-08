"""Tests for TradeVsClaude head-to-head runner."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantforge.experimental.trade_vs_claude import (
    TradeVsClaude,
    mock_llm_signal,
)


def _gbm_prices(n: int = 200, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, n)
    px = 100.0 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(px, index=idx, name="close")


def _flat_signal(p: pd.Series) -> pd.Series:
    return pd.Series(0.0, index=p.index)


def test_run_returns_expected_keys():
    px = _gbm_prices()
    res = TradeVsClaude(user_signal=_flat_signal).run(px)
    for k in ("user_equity", "llm_equity", "user_sharpe", "llm_sharpe", "winner"):
        assert k in res
    assert res["winner"] in ("user", "llm")


def test_flat_user_signal_has_equity_one():
    px = _gbm_prices()
    res = TradeVsClaude(user_signal=_flat_signal).run(px)
    assert res["user_equity"].iloc[-1] == pytest.approx(1.0, abs=1e-9)


def test_run_rejects_short_series():
    px = _gbm_prices(n=10)
    with pytest.raises(ValueError):
        TradeVsClaude(user_signal=_flat_signal).run(px)


def test_run_rejects_non_series():
    with pytest.raises(TypeError):
        TradeVsClaude(user_signal=_flat_signal).run([1.0, 2.0, 3.0])


def test_mock_llm_signal_is_in_position_set():
    px = _gbm_prices()
    sig = mock_llm_signal(px)
    assert set(sig.dropna().unique()).issubset({-1.0, 0.0, 1.0})
