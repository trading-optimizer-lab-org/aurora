"""Earnings-call live trader.

Streams chunks from an earnings-call transcript, scores sentiment per
chunk via a mock LLM, and emits real-time long/short signals. The audio
or live-transcript stream is fully mocked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Optional


_POS_WORDS = ("strong", "growth", "exceed", "raised", "outperform", "record")
_NEG_WORDS = ("decline", "miss", "lowered", "weak", "headwind", "challenging")


def _mock_score(chunk: str) -> float:
    low = chunk.lower()
    pos = sum(low.count(w) for w in _POS_WORDS)
    neg = sum(low.count(w) for w in _NEG_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


@dataclass
class EarningsCallLiveTrader:
    """Real-time earnings-call sentiment trader.

    Parameters
    ----------
    long_threshold : float
        Cumulative sentiment above this triggers a long signal.
    short_threshold : float
        Cumulative sentiment below this triggers a short signal.
    scorer : Callable[[str], float], optional
        Custom sentiment scorer in [-1, 1]. Defaults to a deterministic
        keyword-based mock.
    """

    long_threshold: float = 0.5
    short_threshold: float = -0.5
    scorer: Callable[[str], float] = field(default=_mock_score)

    def __post_init__(self) -> None:
        if self.short_threshold >= self.long_threshold:
            raise ValueError("short_threshold must be < long_threshold")

    def trade(self, transcript_stream: Iterable[str]) -> list[dict]:
        """Iterate the stream and emit a list of signal events."""
        out: list[dict] = []
        cum = 0.0
        n = 0
        for chunk in transcript_stream:
            if not isinstance(chunk, str) or not chunk.strip():
                continue
            n += 1
            score = float(self.scorer(chunk))
            score = max(-1.0, min(1.0, score))
            cum += score
            avg = cum / n
            if avg > self.long_threshold:
                signal = "long"
            elif avg < self.short_threshold:
                signal = "short"
            else:
                signal = "flat"
            out.append(
                {
                    "chunk_idx": n - 1,
                    "score": score,
                    "avg_sentiment": avg,
                    "signal": signal,
                }
            )
        return out
