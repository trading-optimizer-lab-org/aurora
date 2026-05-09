"""Earnings call transcript adapter.

Pulls quarterly earnings call transcripts from a configurable provider
(placeholder: ``tikr`` or ``seekingalpha``). Sentiment is scored either with a
local lexicon or a lazily-imported Anthropic LLM. Tests use ``mock=True`` to
return deterministic synthetic transcripts and scores.

Returned columns:
    symbol, fiscal_period, call_date, sentiment_score, transcript_excerpt
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# Naive but deterministic lexicon used as a fallback when no LLM is available.
# Not authoritative; primarily makes the offline path produce a non-zero signal
# proportional to bullish/bearish word counts.
_BULLISH_WORDS = ("growth", "beat", "record", "expansion", "exceed",
                  "outperform", "guidance raised")
_BEARISH_WORDS = ("decline", "miss", "headwind", "weak", "downgrade",
                  "guidance lowered", "softness")


@dataclass
class EarningsConfig:
    """Static config.

    Attributes:
        provider: source name (informational; vendor SDKs left as a stub).
        api_key_env: env var with provider API key.
        scorer: 'lexicon' or 'llm'. LLM falls back to lexicon when SDK missing.
        anthropic_model: Claude model id used when scorer == 'llm'.
    """
    provider: str = "tikr"
    api_key_env: str = "TRANSCRIPTS_API_KEY"
    scorer: str = "lexicon"
    anthropic_model: str = "claude-haiku-4-5"


class EarningsTranscriptAdapter:
    """Quarterly transcript fetch + sentiment scoring."""

    _COLS = ("symbol", "fiscal_period", "call_date", "sentiment_score",
             "transcript_excerpt")

    def __init__(self, config: Optional[EarningsConfig] = None) -> None:
        self.config = config or EarningsConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_transcripts(
        self,
        symbol: str,
        n_periods: int = 4,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return the most recent ``n_periods`` earnings call rows."""
        if n_periods <= 0:
            raise ValueError("n_periods must be positive")
        raws = (self._mock_transcripts(symbol, n_periods)
                if mock else self._fetch_transcripts(symbol, n_periods))
        rows = []
        for r in raws:
            rows.append({
                "symbol": symbol.upper(),
                "fiscal_period": r["fiscal_period"],
                "call_date": pd.Timestamp(r["call_date"]),
                "sentiment_score": self.score_text(r["text"]),
                "transcript_excerpt": r["text"][:500],
            })
        return pd.DataFrame(rows, columns=list(self._COLS))

    def score_text(self, text: str) -> float:
        """Score a transcript snippet in [-1, 1].

        Tries the configured backend in order; both have a deterministic
        fallback so tests do not need network or credentials.
        """
        if not text:
            return 0.0
        if self.config.scorer == "llm":
            llm_score = self._score_llm(text)
            if llm_score is not None:
                return llm_score
        return self._score_lexicon(text)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _score_lexicon(self, text: str) -> float:
        low = text.lower()
        bull = sum(low.count(w) for w in _BULLISH_WORDS)
        bear = sum(low.count(w) for w in _BEARISH_WORDS)
        denom = bull + bear
        if denom == 0:
            return 0.0
        return (bull - bear) / denom

    def _score_llm(self, text: str) -> Optional[float]:  # pragma: no cover - network
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return None
        # Real implementation: call anthropic.Messages with a JSON-only
        # sentiment prompt. Stubbed to keep the package free of network calls.
        return None

    def _fetch_transcripts(
        self,
        symbol: str,
        n_periods: int,
    ) -> list[dict]:  # pragma: no cover - network
        import os
        if not os.environ.get(self.config.api_key_env, ""):
            raise RuntimeError(
                f"missing env var {self.config.api_key_env}"
            )
        return []

    def _mock_transcripts(
        self,
        symbol: str,
        n_periods: int,
    ) -> list[dict]:
        rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
        out = []
        base = pd.Timestamp("2025-01-01")
        for i in range(n_periods):
            # Mix bullish/bearish keywords so the lexicon scorer is exercised.
            bull_count = int(rng.integers(0, 5))
            bear_count = int(rng.integers(0, 5))
            text = " ".join(["growth"] * bull_count
                            + ["decline"] * bear_count
                            + [f"Quarter Q{(i % 4) + 1} commentary."])
            out.append({
                "fiscal_period": f"Q{(i % 4) + 1} 202{4 + (i // 4)}",
                "call_date": (base + pd.Timedelta(days=90 * i)).isoformat(),
                "text": text,
            })
        return out
