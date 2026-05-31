"""Tests for aurora.altdata.news_llm_sentiment."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aurora.altdata.news_llm_sentiment import (
    NewsLLMConfig,
    NewsLLMSentimentAdapter,
)


@pytest.fixture
def adapter() -> NewsLLMSentimentAdapter:
    return NewsLLMSentimentAdapter()


def test_mock_columns_and_score_range(adapter: NewsLLMSentimentAdapter):
    df = adapter.fetch_sentiment(["AAPL", "MSFT"], mock=True)
    assert list(df.columns) == [
        "date", "symbol", "sentiment_score", "n_articles",
    ]
    assert (df["sentiment_score"].between(-1.0, 1.0)).all()
    assert (df["n_articles"] >= 1).all()
    assert set(df["symbol"]) == {"AAPL", "MSFT"}


def test_score_headline_bullish(adapter: NewsLLMSentimentAdapter):
    s = adapter.score_headline("Tesla stock surges on strong earnings beat")
    assert s > 0.0


def test_score_headline_bearish(adapter: NewsLLMSentimentAdapter):
    s = adapter.score_headline("Stock plunges on miss and downgrade")
    assert s < 0.0


def test_score_headline_neutral_returns_zero(adapter: NewsLLMSentimentAdapter):
    assert adapter.score_headline("Company announces new headquarters") == 0.0


def test_empty_symbols_returns_empty(adapter: NewsLLMSentimentAdapter):
    df = adapter.fetch_sentiment([], mock=True)
    assert df.empty
    assert list(df.columns) == [
        "date", "symbol", "sentiment_score", "n_articles",
    ]


def test_start_must_precede_end(adapter: NewsLLMSentimentAdapter):
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="start must be before end"):
        adapter.fetch_sentiment(
            ["AAPL"], start=end, end=end - timedelta(days=1), mock=True,
        )
