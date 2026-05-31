"""Tests for aurora.altdata.reddit_scraper."""
from __future__ import annotations

import pytest

from aurora.altdata.reddit_scraper import RedditAdapter, RedditConfig


@pytest.fixture
def adapter() -> RedditAdapter:
    return RedditAdapter()


def test_mock_columns(adapter: RedditAdapter):
    df = adapter.scrape_mentions(symbols=["GME"], mock=True)
    assert list(df.columns) == [
        "date", "symbol", "subreddit", "n_mentions", "score_sum",
    ]
    assert not df.empty


def test_extract_tickers_filters_stopwords():
    cfg = RedditConfig()
    text = "Buy $TSLA before EPS, also AAPL is the GOAT but FOMC scared"
    out = RedditAdapter.extract_tickers(text, cfg.stopwords)
    assert "TSLA" in out
    assert "AAPL" in out
    assert "FOMC" not in out  # stopword
    assert "EPS" not in out   # stopword


def test_extract_tickers_handles_empty():
    cfg = RedditConfig()
    assert RedditAdapter.extract_tickers("", cfg.stopwords) == []


def test_mock_filters_to_requested_symbols(adapter: RedditAdapter):
    df = adapter.scrape_mentions(symbols=["AMC", "GME"], mock=True)
    assert set(df["symbol"].unique()) == {"AMC", "GME"}


def test_mock_default_symbols_when_none(adapter: RedditAdapter):
    df = adapter.scrape_mentions(symbols=None, mock=True)
    assert not df.empty
    # default sample includes WSB-style favorites
    assert {"GME", "AMC", "TSLA", "AAPL"}.issubset(set(df["symbol"].unique()))
