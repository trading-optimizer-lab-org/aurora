"""Tests for TwitterAlphaBot."""
from __future__ import annotations

import pytest

from aurora.experimental.twitter_alpha_bot import TwitterAlphaBot


def test_default_watchlist_present():
    bot = TwitterAlphaBot()
    assert "RaoulGMI" in bot.watchlist


def test_no_signals_when_fetcher_empty():
    bot = TwitterAlphaBot(fetcher=lambda h: [])
    assert bot.scan() == []


def test_buy_signal_extracted():
    tweets = {"RaoulGMI": [{"id": "1", "text": "Bullish on $AAPL"}]}
    bot = TwitterAlphaBot(
        watchlist=["RaoulGMI"],
        fetcher=lambda h: tweets.get(h, []),
    )
    out = bot.scan()
    assert len(out) == 1
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["action"] == "buy"


def test_sell_signal_extracted():
    tweets = [{"id": "2", "text": "Time to short $TSLA, looks bearish"}]
    bot = TwitterAlphaBot(watchlist=["x"], fetcher=lambda h: tweets)
    out = bot.scan()
    assert any(s["action"] == "sell" for s in out)


def test_no_ticker_means_no_signal():
    tweets = [{"id": "3", "text": "I am bullish on the market"}]
    bot = TwitterAlphaBot(watchlist=["x"], fetcher=lambda h: tweets)
    assert bot.scan() == []


def test_min_confidence_validation():
    with pytest.raises(ValueError):
        TwitterAlphaBot(min_confidence=2.0)


def test_neutral_tweets_ignored():
    tweets = [{"id": "4", "text": "$AAPL announced new chip today"}]
    bot = TwitterAlphaBot(watchlist=["x"], fetcher=lambda h: tweets)
    assert bot.scan() == []
