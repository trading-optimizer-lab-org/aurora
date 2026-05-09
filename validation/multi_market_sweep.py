"""Multi-market sweep (R107).

Run the same strategy across N markets in parallel and produce a
ranked table: best market, worst market, median market, market-
specific Calmar. A strategy that only works on one symbol is more
likely curve-fit than one that works across a basket.

Pairs with R97 (CV matrices) and R104 (bootstrap CIs) so the per-
market metrics carry uncertainty bands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

import numpy as np

from aurora.core.metrics import compute_metrics


@dataclass(frozen=True)
class MarketResult:
    """One per-market run."""

    market: str
    sharpe: float
    calmar: float
    cagr: float
    mdd: float


@dataclass(frozen=True)
class SweepResult:
    """Ranked + summary view across markets."""

    per_market: List[MarketResult]
    best: MarketResult
    worst: MarketResult
    median: MarketResult
    spread_sharpe: float


def sweep(
    *,
    strategy_fn: Callable[[np.ndarray], np.ndarray],
    market_returns: Dict[str, np.ndarray],
    ppy: int = 252,
) -> SweepResult:
    """Run ``strategy_fn`` across every market and return ranked metrics.

    Args:
        strategy_fn: callable that maps a per-market asset-return
            series to a per-bar strategy-return series. Closure over
            the cost model.
        market_returns: dict of market_name -> per-bar asset returns.
        ppy: periods per year.

    Returns:
        :class:`SweepResult`.
    """
    if not market_returns:
        raise ValueError("market_returns dict is empty")
    rows: List[MarketResult] = []
    for market, rets in market_returns.items():
        strat = strategy_fn(np.asarray(rets, dtype=float))
        m = compute_metrics(strat, ppy=ppy)
        rows.append(MarketResult(
            market=market,
            sharpe=float(m.sharpe),
            calmar=float(m.calmar),
            cagr=float(m.cagr),
            mdd=float(m.mdd),
        ))
    rows.sort(key=lambda r: r.sharpe, reverse=True)
    best = rows[0]
    worst = rows[-1]
    median = rows[len(rows) // 2]
    sharpes = np.asarray([r.sharpe for r in rows])
    spread = float(sharpes.max() - sharpes.min())
    return SweepResult(
        per_market=rows,
        best=best,
        worst=worst,
        median=median,
        spread_sharpe=spread,
    )


__all__ = [
    "MarketResult",
    "SweepResult",
    "sweep",
]
