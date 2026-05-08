"""Tests for EarningsCallLiveTrader."""
from __future__ import annotations

import pytest

from quantforge.experimental.earnings_call_live import EarningsCallLiveTrader, _mock_score


def test_positive_chunks_trigger_long():
    trader = EarningsCallLiveTrader(long_threshold=0.1, short_threshold=-0.5)
    stream = [
        "Strong growth this quarter",
        "Record revenue and we exceed expectations",
        "Raised guidance materially",
    ]
    out = trader.trade(stream)
    assert out[-1]["signal"] == "long"
    assert len(out) == 3


def test_negative_chunks_trigger_short():
    trader = EarningsCallLiveTrader(long_threshold=0.5, short_threshold=-0.1)
    stream = [
        "Significant decline this quarter",
        "Lowered guidance after a clear miss",
        "Weak demand and challenging environment",
    ]
    out = trader.trade(stream)
    assert out[-1]["signal"] == "short"


def test_empty_chunks_skipped():
    trader = EarningsCallLiveTrader()
    out = trader.trade(["", None, "Strong growth"])  # type: ignore[list-item]
    assert len(out) == 1


def test_threshold_validation():
    with pytest.raises(ValueError):
        EarningsCallLiveTrader(long_threshold=0.0, short_threshold=0.5)


def test_mock_score_neutral_for_no_keywords():
    assert _mock_score("the cat sat on the mat") == 0.0


def test_custom_scorer_used():
    trader = EarningsCallLiveTrader(scorer=lambda c: 1.0, long_threshold=0.5, short_threshold=-0.5)
    out = trader.trade(["abc", "def"])
    assert out[-1]["signal"] == "long"
    assert out[-1]["avg_sentiment"] == pytest.approx(1.0)
