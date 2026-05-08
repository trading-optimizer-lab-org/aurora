"""Tests for quantforge.markets.credit."""
from __future__ import annotations

import pytest

from quantforge.markets.credit import CreditConfig, CreditMarket


@pytest.fixture
def cm() -> CreditMarket:
    return CreditMarket(CreditConfig(days=120, z_window=30, seed=1))


def test_analyze_returns_indices(cm: CreditMarket) -> None:
    df = cm.analyze(mock=True)
    assert not df.empty
    assert {"date", "index", "spread_bps", "total_return"}.issubset(df.columns)
    indices = set(df["index"].unique())
    assert {"CDX_IG", "CDX_HY", "ITRAXX_MAIN", "ITRAXX_XOVER"}.issubset(indices)


def test_signals_emit_z_score(cm: CreditMarket) -> None:
    df = cm.analyze(mock=True)
    sigs = cm.signals(df)
    assert {"index", "spread_bps", "z_score", "signal"}.issubset(sigs.columns)
    assert sigs["signal"].isin([-1, 0, 1]).all()


def test_signals_empty_for_empty_input(cm: CreditMarket) -> None:
    import pandas as pd
    sigs = cm.signals(pd.DataFrame())
    assert sigs.empty
