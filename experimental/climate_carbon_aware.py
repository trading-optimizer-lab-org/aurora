"""Carbon-aware portfolio allocator.

Penalizes a base set of weights by each asset's carbon-intensity score
(scope 1+2 emissions per unit revenue, in kgCO2e/$ revenue, by default).
The score source is pluggable; the default is a hard-coded mock dictionary
keyed by ticker so the allocator runs without any external data feed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

import numpy as np


# Mock ESG scores (kgCO2e per $ revenue). Real systems would hit MSCI,
# Sustainalytics, ISS, or CDP. Kept tiny here and clearly marked as mock.
DEFAULT_CARBON_SCORES: dict[str, float] = {
    "AAPL": 0.05,
    "MSFT": 0.04,
    "TSLA": 0.10,
    "XOM": 1.20,
    "CVX": 1.10,
    "NEE": 0.30,
    "META": 0.06,
    "GOOG": 0.05,
    "AMZN": 0.20,
    "JPM": 0.08,
}


ScoreSource = Callable[[str], float]


@dataclass
class CarbonAwareAllocator:
    """Penalize portfolio weights by per-asset carbon intensity.

    Parameters
    ----------
    score_source : callable, optional
        ``score_source(ticker) -> float``. Defaults to looking up the mock
        ``DEFAULT_CARBON_SCORES`` dictionary; missing tickers fall back to
        ``default_score``.
    penalty : float
        Strength of the carbon penalty. ``adjusted = base * exp(-penalty *
        score)``. Larger means more aggressive de-weighting of high-carbon
        names.
    default_score : float
        Fallback carbon intensity for tickers absent from the source.
    """

    score_source: Optional[ScoreSource] = None
    penalty: float = 1.0
    default_score: float = 0.5

    def _score(self, ticker: str) -> float:
        if self.score_source is not None:
            try:
                return float(self.score_source(ticker))
            except KeyError:
                return self.default_score
        return float(DEFAULT_CARBON_SCORES.get(ticker, self.default_score))

    def adjust(self, weights: Mapping[str, float]) -> dict[str, float]:
        """Return new weights penalized by carbon score and renormalized.

        Long-only is assumed; negative weights are clipped before adjustment.
        """
        if self.penalty < 0:
            raise ValueError("penalty must be >= 0")
        if not weights:
            return {}

        adjusted: dict[str, float] = {}
        for tk, w in weights.items():
            base = max(float(w), 0.0)
            score = self._score(tk)
            adjusted[tk] = base * float(np.exp(-self.penalty * score))

        s = sum(adjusted.values())
        if s == 0:
            # Degenerate input (all-zero or fully penalized to 0). Return
            # equal weights so the portfolio is still investable.
            n = len(adjusted)
            return {k: 1.0 / n for k in adjusted}
        return {k: v / s for k, v in adjusted.items()}

    def portfolio_carbon(self, weights: Mapping[str, float]) -> float:
        """Weighted-average carbon intensity of the portfolio."""
        s = sum(max(float(w), 0.0) for w in weights.values())
        if s == 0:
            return 0.0
        return sum(self._score(tk) * max(float(w), 0.0) for tk, w in weights.items()) / s
