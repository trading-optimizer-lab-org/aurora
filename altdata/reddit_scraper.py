"""Reddit symbol-mention scraper.

Wraps PRAW (Python Reddit API Wrapper) lazily. Scrapes a configurable list of
subreddits (default: ``wallstreetbets``, ``stocks``, ``options``) for ticker
mentions. Returns a DataFrame with mention counts and aggregate comment scores
per (date, symbol).

Tests use ``mock=True`` to avoid network and credential requirements.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import numpy as np
import pandas as pd

# Cashtag $TSLA OR bare TSLA (3-5 caps). Excludes common English words via the
# caller-supplied stop list.
_TICKER_RE = re.compile(r"\$?\b([A-Z]{2,5})\b")
_DEFAULT_STOPWORDS = frozenset({
    "DD", "WSB", "USD", "EOD", "CEO", "CFO", "ATH", "IPO", "ETF", "FOMC",
    "FED", "GDP", "CPI", "EPS", "FY", "YOY", "QOQ", "AI", "ML",
})


@dataclass
class RedditConfig:
    """Static config for the Reddit adapter.

    Attributes:
        client_id_env: env var with PRAW client_id.
        client_secret_env: env var with PRAW client_secret.
        user_agent: PRAW user agent string.
        subreddits: list of subreddits to scrape.
        post_limit: posts per subreddit per fetch.
        stopwords: tickers to exclude (false-positive English words).
    """
    client_id_env: str = "REDDIT_CLIENT_ID"
    client_secret_env: str = "REDDIT_CLIENT_SECRET"
    user_agent: str = "quantforge-altdata/0.1"
    subreddits: tuple[str, ...] = ("wallstreetbets", "stocks", "options")
    post_limit: int = 100
    stopwords: frozenset[str] = field(default_factory=lambda: _DEFAULT_STOPWORDS)


class RedditAdapter:
    """Aggregate ticker mentions from Reddit posts."""

    _COLS = ("date", "symbol", "subreddit", "n_mentions", "score_sum")

    def __init__(self, config: Optional[RedditConfig] = None) -> None:
        self.config = config or RedditConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def scrape_mentions(
        self,
        symbols: Optional[Iterable[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return aggregated mention counts.

        If ``symbols`` is None, all detected tickers are returned (filtered
        through ``config.stopwords``).
        """
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(days=3))
        wanted = {s.upper() for s in symbols} if symbols else None
        if mock:
            return self._mock_frame(wanted, start, end)
        posts = self._fetch_posts(start, end)
        return self._aggregate(posts, wanted)

    @staticmethod
    def extract_tickers(text: str, stopwords: frozenset[str]) -> list[str]:
        """Return list of distinct ticker tokens found in ``text``."""
        if not text:
            return []
        candidates = {m.group(1) for m in _TICKER_RE.finditer(text)}
        return [c for c in candidates if c not in stopwords]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _mock_frame(
        self,
        wanted: Optional[set[str]],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        symbols = sorted(wanted) if wanted else ["GME", "AMC", "TSLA", "AAPL"]
        rng = np.random.default_rng(abs(hash(("reddit", tuple(symbols)))) % (2**32))
        days = pd.date_range(start.date(), end.date(), freq="D")
        rows = []
        for d in days:
            for sym in symbols:
                for sub in self.config.subreddits:
                    rows.append({
                        "date": d.normalize(),
                        "symbol": sym,
                        "subreddit": sub,
                        "n_mentions": int(rng.integers(0, 50)),
                        "score_sum": int(rng.integers(0, 5000)),
                    })
        return pd.DataFrame(rows, columns=list(self._COLS))

    def _fetch_posts(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict]:  # pragma: no cover - network path
        import os
        try:
            import praw  # type: ignore
        except ImportError as e:
            raise ImportError("praw required for live Reddit fetch") from e
        cid = os.environ.get(self.config.client_id_env, "")
        csec = os.environ.get(self.config.client_secret_env, "")
        if not (cid and csec):
            raise RuntimeError("missing reddit credentials env vars")
        reddit = praw.Reddit(
            client_id=cid,
            client_secret=csec,
            user_agent=self.config.user_agent,
        )
        out: list[dict] = []
        start_ts = start.timestamp()
        end_ts = end.timestamp()
        for sub_name in self.config.subreddits:
            for post in reddit.subreddit(sub_name).new(
                limit=self.config.post_limit
            ):
                if not (start_ts <= post.created_utc < end_ts):
                    continue
                out.append({
                    "subreddit": sub_name,
                    "title": post.title,
                    "selftext": getattr(post, "selftext", "") or "",
                    "score": int(post.score),
                    "created_utc": float(post.created_utc),
                })
        return out

    def _aggregate(
        self,
        posts: list[dict],
        wanted: Optional[set[str]],
    ) -> pd.DataFrame:
        rows: list[dict] = []
        sw = self.config.stopwords
        for p in posts:
            text = f"{p['title']} {p['selftext']}"
            tickers = self.extract_tickers(text, sw)
            day = pd.Timestamp(p["created_utc"], unit="s",
                               tz="UTC").normalize()
            for t in tickers:
                if wanted and t not in wanted:
                    continue
                rows.append({
                    "date": day,
                    "symbol": t,
                    "subreddit": p["subreddit"],
                    "n_mentions": 1,
                    "score_sum": p["score"],
                })
        if not rows:
            return pd.DataFrame(columns=list(self._COLS))
        df = pd.DataFrame(rows, columns=list(self._COLS))
        return df.groupby(["date", "symbol", "subreddit"], as_index=False).agg(
            n_mentions=("n_mentions", "sum"),
            score_sum=("score_sum", "sum"),
        )
