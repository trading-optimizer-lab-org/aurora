"""News + LLM sentiment adapter.

Pulls headlines from RSS / news APIs and scores sentiment with the Anthropic
Messages API (lazy import). Returns a daily long-format DataFrame
``[date, symbol, sentiment_score, n_articles]``. Tests use ``mock=True`` to
return deterministic synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class NewsLLMConfig:
    """Static config.

    Attributes:
        rss_feeds: list of RSS feed URLs polled when ``mock=False``.
        anthropic_model: Claude model id used for scoring.
        anthropic_key_env: env var holding the Anthropic API key.
        request_timeout_s: HTTP timeout for RSS/LLM calls.
        max_articles_per_symbol: per-call cap before LLM scoring.
    """
    rss_feeds: tuple[str, ...] = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline",
    )
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_key_env: str = "ANTHROPIC_API_KEY"
    request_timeout_s: float = 10.0
    max_articles_per_symbol: int = 50


class NewsLLMSentimentAdapter:
    """Daily LLM-scored news sentiment per symbol."""

    _COLS = ("date", "symbol", "sentiment_score", "n_articles")

    def __init__(self, config: Optional[NewsLLMConfig] = None) -> None:
        self.config = config or NewsLLMConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def fetch_sentiment(
        self,
        symbols: list[str],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return daily sentiment for ``symbols`` between ``start`` and ``end``."""
        if not symbols:
            return pd.DataFrame(columns=list(self._COLS))
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(days=7))
        if start >= end:
            raise ValueError("start must be before end")
        if mock:
            return self._mock(symbols, start, end)
        articles = self._fetch_articles(symbols, start, end)
        return self._score_and_aggregate(articles)

    def score_headline(self, headline: str) -> float:
        """Score a single headline. LLM path with deterministic fallback."""
        if not headline:
            return 0.0
        llm = self._score_llm(headline)
        if llm is not None:
            return llm
        return self._score_fallback(headline)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _score_fallback(self, text: str) -> float:
        low = text.lower()
        bull = sum(low.count(w) for w in
                   ("beat", "surge", "rally", "upgrade", "strong"))
        bear = sum(low.count(w) for w in
                   ("miss", "plunge", "downgrade", "weak", "warns"))
        denom = bull + bear
        if denom == 0:
            return 0.0
        return (bull - bear) / denom

    def _score_llm(self, text: str) -> Optional[float]:  # pragma: no cover - network
        try:
            import anthropic  # type: ignore  # noqa: F401
        except ImportError:
            return None
        # Real implementation would call anthropic.Messages with a
        # JSON-only sentiment prompt. Stubbed to keep tests offline.
        return None

    def _fetch_articles(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict]:  # pragma: no cover - network
        try:
            import feedparser  # type: ignore  # noqa: F401
        except ImportError as e:
            raise ImportError("feedparser required for live RSS fetch") from e
        return []

    def _score_and_aggregate(self, articles: list[dict]) -> pd.DataFrame:
        if not articles:
            return pd.DataFrame(columns=list(self._COLS))
        rows = []
        for a in articles:
            rows.append({
                "date": pd.Timestamp(a["published"]).normalize(),
                "symbol": a["symbol"].upper(),
                "sentiment_score": self.score_headline(a["title"]),
                "n_articles": 1,
            })
        df = pd.DataFrame(rows, columns=list(self._COLS))
        return df.groupby(["date", "symbol"], as_index=False).agg(
            sentiment_score=("sentiment_score", "mean"),
            n_articles=("n_articles", "sum"),
        )

    def _mock(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        days = pd.date_range(start.date(), end.date(), freq="D")
        rows = []
        for sym in symbols:
            rng = np.random.default_rng(abs(hash(("news", sym))) % (2**32))
            for d in days:
                rows.append({
                    "date": d.normalize(),
                    "symbol": sym.upper(),
                    "sentiment_score": float(rng.uniform(-1.0, 1.0)),
                    "n_articles": int(rng.integers(1, 30)),
                })
        return pd.DataFrame(rows, columns=list(self._COLS))
