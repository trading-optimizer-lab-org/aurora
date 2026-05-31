"""Tests for aurora.altdata.twitter_sentiment.

All tests run offline using ``mock=True``. The live network path is exercised
indirectly via missing-credential guard tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from aurora.altdata.twitter_sentiment import (
    TwitterConfig,
    TwitterSentimentAdapter,
)


@pytest.fixture
def adapter() -> TwitterSentimentAdapter:
    return TwitterSentimentAdapter(TwitterConfig(backend="vader"))


def test_mock_returns_expected_columns(adapter: TwitterSentimentAdapter):
    df = adapter.fetch_sentiment(["TSLA"], mock=True)
    assert list(df.columns) == [
        "timestamp", "symbol", "sentiment_score", "n_tweets",
    ]
    assert not df.empty


def test_mock_score_range(adapter: TwitterSentimentAdapter):
    df = adapter.fetch_sentiment(["AAPL", "MSFT"], mock=True)
    assert (df["sentiment_score"].between(-1.0, 1.0)).all()
    assert (df["n_tweets"] > 0).all()


def test_mock_deterministic_per_symbol_set(adapter: TwitterSentimentAdapter):
    end = datetime(2025, 1, 8, tzinfo=timezone.utc)
    start = end - timedelta(days=3)
    a = adapter.fetch_sentiment(["NVDA"], start=start, end=end, mock=True)
    b = adapter.fetch_sentiment(["NVDA"], start=start, end=end, mock=True)
    pd.testing.assert_frame_equal(a, b)


def test_empty_symbols_returns_empty(adapter: TwitterSentimentAdapter):
    df = adapter.fetch_sentiment([], mock=True)
    assert df.empty
    assert list(df.columns) == [
        "timestamp", "symbol", "sentiment_score", "n_tweets",
    ]


def test_live_fetch_requires_token(monkeypatch, adapter):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TWITTER_BEARER_TOKEN"):
        adapter.fetch_sentiment(["TSLA"], mock=False)
