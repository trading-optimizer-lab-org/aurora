"""Tests for quantforge.markets.futures."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.markets.futures import FuturesConfig, FuturesContinuous


@pytest.fixture
def fut() -> FuturesContinuous:
    return FuturesContinuous(FuturesConfig(roll_method="ratio",
                                           mock_contracts=3, seed=1))


def test_continuous_has_expected_columns(fut: FuturesContinuous) -> None:
    df = fut.analyze(symbol="CL", mock=True)
    assert {"date", "symbol", "contract", "close", "continuous"}.issubset(
        df.columns)
    assert not df.empty


def test_continuous_back_adjusted_method() -> None:
    fut = FuturesContinuous(FuturesConfig(roll_method="back_adjusted",
                                          mock_contracts=3, seed=1))
    df = fut.analyze(symbol="CL", mock=True)
    assert not df.empty
    assert df["continuous"].notna().all()


def test_signals_returns_signed_value(fut: FuturesContinuous) -> None:
    df = fut.analyze(symbol="CL", mock=True)
    sigs = fut.signals(df)
    if not sigs.empty:
        assert sigs["signal"].isin([-1, 0, 1]).all()


def test_build_continuous_validates_columns() -> None:
    fut = FuturesContinuous()
    with pytest.raises(ValueError):
        fut.build_continuous(pd.DataFrame({"date": [], "close": []}))
