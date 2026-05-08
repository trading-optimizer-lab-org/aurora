"""Tests for quantforge.altdata.earnings_transcripts."""
from __future__ import annotations

import pytest

from quantforge.altdata.earnings_transcripts import (
    EarningsConfig,
    EarningsTranscriptAdapter,
)


@pytest.fixture
def adapter() -> EarningsTranscriptAdapter:
    return EarningsTranscriptAdapter()


def test_mock_columns(adapter: EarningsTranscriptAdapter):
    df = adapter.get_transcripts("AAPL", n_periods=4, mock=True)
    assert list(df.columns) == [
        "symbol", "fiscal_period", "call_date",
        "sentiment_score", "transcript_excerpt",
    ]
    assert len(df) == 4
    assert (df["symbol"] == "AAPL").all()


def test_score_range(adapter: EarningsTranscriptAdapter):
    df = adapter.get_transcripts("MSFT", n_periods=8, mock=True)
    assert (df["sentiment_score"].between(-1.0, 1.0)).all()


def test_score_text_lexicon_bullish(adapter: EarningsTranscriptAdapter):
    bullish = "record growth growth beat outperform exceed"
    s = adapter.score_text(bullish)
    assert s > 0.5


def test_score_text_lexicon_bearish(adapter: EarningsTranscriptAdapter):
    bearish = "decline miss headwind weak weak softness"
    s = adapter.score_text(bearish)
    assert s < -0.5


def test_n_periods_must_be_positive(adapter: EarningsTranscriptAdapter):
    with pytest.raises(ValueError, match="n_periods must be positive"):
        adapter.get_transcripts("TSLA", n_periods=0, mock=True)


def test_score_text_neutral_returns_zero(adapter: EarningsTranscriptAdapter):
    assert adapter.score_text("Hello world how are you today") == 0.0
