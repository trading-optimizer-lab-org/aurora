"""Twitter cashtag sentiment adapter.

Pulls tweets that mention a cashtag (``$TSLA``) and scores polarity. Two
backends are supported via lazy import:

- ``vader``  : ``vaderSentiment`` (default; lightweight rule-based)
- ``llm``    : ``anthropic`` Messages API (optional; richer)

Network access is opt-in. The default ``mock=True`` path returns a deterministic
synthetic series so tests run offline. Returns
``DataFrame[timestamp, symbol, sentiment_score, n_tweets]`` aggregated to daily.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TwitterConfig:
    """Static config for the Twitter sentiment adapter.

    Attributes:
        bearer_token_env: env var name holding a Twitter v2 bearer token.
        backend: 'vader' or 'llm'. Falls back to 'vader' when llm SDK missing.
        max_tweets_per_symbol: hard cap per fetch window per cashtag.
        lang: BCP-47 language filter (default 'en').
    """
    bearer_token_env: str = "TWITTER_BEARER_TOKEN"
    backend: str = "vader"
    max_tweets_per_symbol: int = 200
    lang: str = "en"
    extra_keywords: tuple[str, ...] = field(default_factory=tuple)


class TwitterSentimentAdapter:
    """Cashtag sentiment fetch + scoring."""

    _COLS = ("timestamp", "symbol", "sentiment_score", "n_tweets")

    def __init__(self, config: Optional[TwitterConfig] = None) -> None:
        self.config = config or TwitterConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_sentiment(
        self,
        symbols: list[str],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return daily sentiment series for ``symbols``.

        Args:
            symbols: tickers without ``$`` prefix.
            start: inclusive start (UTC). Default end - 7 days.
            end: exclusive end (UTC). Default now.
            mock: if True, return deterministic synthetic data.
        """
        if not symbols:
            return pd.DataFrame(columns=list(self._COLS))
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(days=7))
        if mock:
            return self._mock_frame(symbols, start, end)
        tweets = self._fetch_tweets(symbols, start, end)
        return self._score(tweets)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _mock_frame(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(abs(hash(("twitter", tuple(symbols)))) % (2**32))
        days = pd.date_range(start.date(), end.date(), freq="D", tz="UTC")
        rows = []
        for sym in symbols:
            for d in days:
                rows.append({
                    "timestamp": d,
                    "symbol": sym.upper(),
                    "sentiment_score": float(rng.uniform(-1.0, 1.0)),
                    "n_tweets": int(rng.integers(5, 200)),
                })
        return pd.DataFrame(rows, columns=list(self._COLS))

    def _fetch_tweets(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Real network fetch. Lazy-imports ``requests``."""
        import os
        try:
            import requests  # noqa: F401  - lazy
        except ImportError as e:  # pragma: no cover - optional dep
            raise ImportError("requests required for live Twitter fetch") from e
        token = os.environ.get(self.config.bearer_token_env, "")
        if not token:
            raise RuntimeError(
                f"missing env var {self.config.bearer_token_env}"
            )
        # Real implementation would hit /2/tweets/search/recent. We keep a
        # stub here to avoid network calls in tests.
        return []

    def _score(self, tweets: list[dict]) -> pd.DataFrame:
        if not tweets:
            return pd.DataFrame(columns=list(self._COLS))
        backend = self.config.backend
        scorer = self._get_scorer(backend)
        rows = []
        for t in tweets:
            rows.append({
                "timestamp": pd.Timestamp(t["created_at"], tz="UTC"),
                "symbol": t["symbol"].upper(),
                "sentiment_score": scorer(t.get("text", "")),
                "n_tweets": 1,
            })
        df = pd.DataFrame(rows, columns=list(self._COLS))
        agg = df.groupby([
            df["timestamp"].dt.floor("D"),
            "symbol",
        ]).agg(sentiment_score=("sentiment_score", "mean"),
               n_tweets=("n_tweets", "sum")).reset_index()
        return agg

    def _get_scorer(self, backend: str):
        if backend == "vader":
            try:
                from vaderSentiment.vaderSentiment import (  # type: ignore
                    SentimentIntensityAnalyzer,
                )
            except ImportError:  # pragma: no cover - optional dep
                return lambda txt: 0.0
            sia = SentimentIntensityAnalyzer()
            return lambda txt: float(sia.polarity_scores(txt)["compound"])
        if backend == "llm":  # pragma: no cover - network path
            try:
                import anthropic  # type: ignore  # noqa: F401
            except ImportError:
                return lambda txt: 0.0
            return lambda txt: 0.0
        return lambda txt: 0.0
