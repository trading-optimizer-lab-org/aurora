"""Causal engine contract tests executed by GitHub Actions."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.execution import execute_next_open
from aurora.research.stock_protocol.metrics import compute_metrics


def _panel() -> ResearchPanel:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]),
            "symbol": ["TEST"] * 4,
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 103.0, 104.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 102.0, 103.0, 103.5],
            "adj_close": [100.5, 102.0, 103.0, 103.5],
            "volume": [1000, 1200, 1300, 1100],
            "dividends": [0.0] * 4,
            "stock_splits": [0.0] * 4,
        }
    )
    audit = PackAudit("source", "pack", "2020-01-02", "2020-12-31", 4, 1, 0, False, False, "hash")
    return ResearchPanel(frame, audit)


def test_close_signal_enters_next_open():
    signal = pd.DataFrame({"signal_date": [pd.Timestamp("2020-01-02")], "available_at": [pd.Timestamp("2020-01-02")], "symbol": ["TEST"], "score": [1.0], "atr20": [1.0]})
    result = execute_next_open(signal, _panel(), {"kind": "none", "holding_sessions": 1})
    assert result.iloc[0].entry_date == "2020-01-03"
    assert result.iloc[0].entry_price == 101.0


def test_metrics_returns_required_keys():
    result = compute_metrics(pd.Series([0.01, -0.005, 0.02]), pd.DataFrame({"gross_return": [0.01, -0.005, 0.02]}), costs_bps=5)
    assert {"cagr", "sharpe", "sortino", "max_drawdown", "calmar", "return_per_capital_day"} <= set(result)

