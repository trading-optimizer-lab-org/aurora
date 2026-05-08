"""News-entropy regime detector.

Vectorizes a corpus of recent news headlines (TF-IDF) and computes the
Shannon entropy of the average term distribution. Calm regimes show a
narrow vocabulary (low entropy); volatile or crisis regimes show a wider
one (high entropy). Thresholds are configurable.

sklearn is a lazy import; if unavailable we fall back to a hash-based
bag-of-words so the module still works headless.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when sklearn is missing
    TfidfVectorizer = None  # type: ignore[assignment]
    SKLEARN_AVAILABLE = False


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _shannon_entropy(p: np.ndarray) -> float:
    p = np.asarray(p, dtype=float)
    p = p[p > 0]
    if p.size == 0:
        return 0.0
    p = p / p.sum()
    return float(-(p * np.log(p)).sum())


@dataclass
class NewsEntropyRegime:
    """Classify a news corpus into calm / volatile / crisis regimes.

    Parameters
    ----------
    calm_max : float
        Entropy threshold below which the regime is ``calm``.
    volatile_max : float
        Entropy threshold below which the regime is ``volatile`` (and
        above ``calm_max``). Anything above this is ``crisis``.
    max_features : int
        Vocabulary cap for the TF-IDF backend (sklearn path).
    """

    calm_max: float = 4.0
    volatile_max: float = 6.0
    max_features: int = 1000
    backend: str = field(init=False)

    def __post_init__(self) -> None:
        if self.calm_max >= self.volatile_max:
            raise ValueError("calm_max must be < volatile_max")
        self.backend = "tfidf" if SKLEARN_AVAILABLE else "bow"

    def _avg_distribution(self, headlines: list[str]) -> np.ndarray:
        if self.backend == "tfidf":
            vec = TfidfVectorizer(max_features=self.max_features, lowercase=True)
            try:
                X = vec.fit_transform(headlines)
            except ValueError:
                # Empty vocabulary (e.g. all stop words); fall back to BoW.
                return self._bow_distribution(headlines)
            mean = np.asarray(X.mean(axis=0)).ravel()
            return mean
        return self._bow_distribution(headlines)

    def _bow_distribution(self, headlines: list[str]) -> np.ndarray:
        counter: Counter = Counter()
        for h in headlines:
            counter.update(_tokenize(h))
        if not counter:
            return np.array([])
        return np.array(list(counter.values()), dtype=float)

    def detect(self, headlines: Iterable[str]) -> dict:
        """Return regime label and entropy for the given headline corpus."""
        items = [h for h in headlines if h and isinstance(h, str)]
        if len(items) == 0:
            return {"regime": "calm", "entropy": 0.0, "n_headlines": 0}

        dist = self._avg_distribution(items)
        H = _shannon_entropy(dist)
        if H < self.calm_max:
            regime = "calm"
        elif H < self.volatile_max:
            regime = "volatile"
        else:
            regime = "crisis"
        return {
            "regime": regime,
            "entropy": H,
            "n_headlines": len(items),
            "backend": self.backend,
        }
