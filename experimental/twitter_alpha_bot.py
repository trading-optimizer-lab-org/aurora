"""Twitter alpha bot.

Subscribes to a list of verified accounts and turns matching tweets into
trade signals. The X / Twitter client is fully mocked so tests run
without network access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_BUY_WORDS = ("buy", "bullish", "long", "accumulate", "calls")
_SELL_WORDS = ("sell", "bearish", "short", "dump", "puts")


def _classify(text: str) -> str:
    low = text.lower()
    buy = any(w in low for w in _BUY_WORDS)
    sell = any(w in low for w in _SELL_WORDS)
    if buy and not sell:
        return "buy"
    if sell and not buy:
        return "sell"
    return "neutral"


@dataclass
class TwitterAlphaBot:
    """Auto-trade tweets from a watchlist of accounts.

    Parameters
    ----------
    watchlist : list[str]
        Twitter handles to follow (without ``@``).
    min_confidence : float
        Minimum keyword strength required to emit a trade signal.
    fetcher : Callable[[str], list[dict]], optional
        Returns a list of tweet dicts ``{"text": str, "id": str}`` for
        the given handle. Defaults to an empty mock.
    """

    watchlist: list[str] = field(default_factory=lambda: ["RaoulGMI", "michaelkitces"])
    min_confidence: float = 0.5
    fetcher: Optional[Callable[[str], list[dict]]] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.min_confidence <= 1.0):
            raise ValueError("min_confidence must be in [0, 1]")
        if self.fetcher is None:
            self.fetcher = lambda handle: []

    def _tweet_signals(self, handle: str, tweet: dict) -> list[dict]:
        text = str(tweet.get("text", ""))
        action = _classify(text)
        if action == "neutral":
            return []
        tickers = _TICKER_RE.findall(text)
        if not tickers:
            return []
        confidence = min(1.0, 0.4 + 0.2 * len(tickers))
        if confidence < self.min_confidence:
            return []
        return [
            {
                "handle": handle,
                "tweet_id": tweet.get("id", ""),
                "ticker": t,
                "action": action,
                "confidence": confidence,
            }
            for t in tickers
        ]

    def scan(self) -> list[dict]:
        """Pull tweets and return any actionable signals."""
        out: list[dict] = []
        for handle in self.watchlist:
            tweets = self.fetcher(handle) or []  # type: ignore[misc]
            for tw in tweets:
                out.extend(self._tweet_signals(handle, tw))
        return out
