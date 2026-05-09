"""Intraday / multi-frequency cost model (Batch M.3).

Composes on top of :mod:`aurora.core.costs` and :mod:`aurora.core.slippage`
to add bar-level realism for intraday backtests:

- per-bar bid-ask spread lookup (overrides ``base_bps`` when wider)
- time-of-day participation curve (U-shape for US equities, flat for crypto)
- square-root market impact ``impact_coef * sqrt(qty / adv) * 100``
- Corwin-Schultz proxy to estimate spread from OHLC when bid-ask is missing

This module is read-only with respect to the daily ``CostModel``: it does
not modify or subclass it. Callers can sum the bps returned here with
their existing ``CostModel.per_trade_bps()`` if they want both layers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

# US equity regular session bounds in minutes-from-midnight ET.
_US_OPEN_MIN = 9 * 60 + 30   # 09:30 -> 570
_US_CLOSE_MIN = 16 * 60      # 16:00 -> 960
_US_SESSION_LEN = _US_CLOSE_MIN - _US_OPEN_MIN  # 390 minutes


def _time_of_day_fraction(timestamp) -> float:
    """Convert a timestamp to a 0-1 fraction across the US regular session.

    0.0 = 09:30 ET, 1.0 = 16:00 ET. Values outside the session are clipped.
    """
    ts = pd.Timestamp(timestamp)
    minutes = ts.hour * 60 + ts.minute + ts.second / 60.0
    frac = (minutes - _US_OPEN_MIN) / _US_SESSION_LEN
    if frac < 0.0:
        return 0.0
    if frac > 1.0:
        return 1.0
    return float(frac)


def default_us_equity_curve() -> Callable[[float], float]:
    """U-shaped intraday participation multiplier for US cash equities.

    Returns a callable mapping time-of-day fraction in [0, 1] to a multiplier
    in roughly [0.8, 2.5]. Open and close are 2.5x; mid-session is 0.8x.
    """
    open_mult = 2.5
    mid_mult = 0.8

    def curve(frac: float) -> float:
        x = max(0.0, min(1.0, float(frac)))
        # symmetric quadratic: 1 at endpoints, 0 at midpoint.
        bowl = (2.0 * x - 1.0) ** 2
        return mid_mult + (open_mult - mid_mult) * bowl

    return curve


def default_crypto_curve() -> Callable[[float], float]:
    """Flat 1.0 multiplier (24/7 markets, no preferred trading window)."""

    def curve(frac: float) -> float:  # noqa: ARG001 - intentional flat
        return 1.0

    return curve


def estimate_spread_from_high_low(prices: pd.DataFrame) -> pd.Series:
    """Corwin-Schultz two-day high-low bid-ask spread proxy, in bps.

    Args:
        prices: DataFrame with columns ``high`` and ``low`` indexed by bar.

    Returns:
        Series of estimated half-spread in bps, aligned to ``prices.index``.
        First value is NaN (needs a previous bar). Negative raw estimates
        are clipped to 0 per the original Corwin-Schultz convention.

    Reference:
        Corwin, S. and Schultz, P. (2012) "A Simple Way to Estimate Bid-Ask
        Spreads from Daily High and Low Prices", Journal of Finance.
    """
    if "high" not in prices.columns or "low" not in prices.columns:
        raise ValueError("prices must have 'high' and 'low' columns")

    high = prices["high"].astype(float).to_numpy()
    low = prices["low"].astype(float).to_numpy()
    n = len(high)
    out: np.ndarray = np.full(n, np.nan, dtype=float)

    if n < 2:
        return pd.Series(out, index=prices.index, name="spread_bps")

    # beta_t = ln(H_t/L_t)^2 + ln(H_{t-1}/L_{t-1})^2
    log_hl_sq = np.log(np.where(low > 0, high / low, 1.0)) ** 2
    beta = log_hl_sq[1:] + log_hl_sq[:-1]

    # gamma_t = ln(max(H_t,H_{t-1}) / min(L_t,L_{t-1}))^2
    h2 = np.maximum(high[1:], high[:-1])
    l2 = np.minimum(low[1:], low[:-1])
    gamma = np.log(np.where(l2 > 0, h2 / l2, 1.0)) ** 2

    denom = 3.0 - 2.0 * math.sqrt(2.0)
    # alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2)) - sqrt(gamma / (3 - 2*sqrt(2)))
    alpha = (
        (np.sqrt(2.0 * np.maximum(beta, 0.0)) - np.sqrt(np.maximum(beta, 0.0)))
        / denom
        - np.sqrt(np.maximum(gamma, 0.0) / denom)
    )
    # spread S = 2*(e^alpha - 1) / (1 + e^alpha)  -> proportional spread
    exp_alpha = np.exp(alpha)
    spread_prop = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)
    spread_prop = np.where(spread_prop < 0.0, 0.0, spread_prop)
    # half-spread in bps = spread_prop / 2 * 1e4
    out[1:] = spread_prop * 1e4 / 2.0
    return pd.Series(out, index=prices.index, name="spread_bps")


@dataclass
class IntradayCostModel:
    """Bar-level cost model for intraday backtests.

    Attributes:
        base_bps: Floor commission/spread in bps per fill.
        bid_ask_bps: Optional Series of per-bar bid-ask in bps. If supplied,
            the realized spread is ``max(base_bps, lookup(timestamp))``. The
            index must be monotonic-increasing and contain unique values
            (validated at construction).
        participation_curve: Optional callable mapping time-of-day fraction
            in [0, 1] to a multiplier. Default = no scaling (returns 1.0).
        impact_coef: Square-root impact coefficient. ``impact_bps =
            impact_coef * sqrt(qty / adv) * 100``.
        adv: Average daily volume in shares. Required for impact, else 0.
    """

    base_bps: float = 1.0
    bid_ask_bps: Optional[pd.Series] = None
    participation_curve: Optional[Callable[[float], float]] = None
    impact_coef: float = 0.1
    adv: Optional[float] = None

    def __post_init__(self) -> None:
        # bid_ask_bps lookup uses ``searchsorted(side='right') - 1`` which
        # silently returns wrong values when the index is unsorted or has
        # duplicates. Reject those at construction so failures are loud.
        if self.bid_ask_bps is not None:
            idx = self.bid_ask_bps.index
            if not idx.is_monotonic_increasing:
                raise ValueError(
                    "bid_ask_bps.index must be monotonic increasing; got an "
                    "unsorted index. Sort with .sort_index() before passing."
                )
            if not idx.is_unique:
                raise ValueError(
                    "bid_ask_bps.index must be unique; duplicate timestamps "
                    "would make searchsorted-based lookup ambiguous."
                )

    def _spread_at(self, timestamp) -> float:
        """Realized spread bps for a bar timestamp (max of base and lookup)."""
        if self.bid_ask_bps is None:
            return float(self.base_bps)
        ts = pd.Timestamp(timestamp)
        idx = self.bid_ask_bps.index
        if ts in idx:
            value = float(self.bid_ask_bps.loc[ts])
        else:
            # nearest-prior lookup; fall back to base_bps if before first bar
            try:
                pos = idx.searchsorted(ts, side="right") - 1
            except TypeError:
                return float(self.base_bps)
            if pos < 0:
                return float(self.base_bps)
            value = float(self.bid_ask_bps.iloc[pos])
        if math.isnan(value):
            return float(self.base_bps)
        return max(float(self.base_bps), value)

    def _participation_mult(self, timestamp) -> float:
        if self.participation_curve is None:
            return 1.0
        return float(self.participation_curve(_time_of_day_fraction(timestamp)))

    def _impact_bps(self, qty: float) -> float:
        if self.adv is None or self.adv <= 0.0 or qty == 0.0:
            return 0.0
        return float(self.impact_coef * math.sqrt(abs(qty) / self.adv) * 100.0)

    def cost_bps(
        self,
        price: float,
        qty: float,
        timestamp,
        bar_volume: Optional[float] = None,  # noqa: ARG002 - reserved for future use
    ) -> float:
        """Total cost in bps for one fill.

        Args:
            price: Mid/decision price (kept for API symmetry; not used yet).
            qty: Order size in shares (sign ignored, ``abs(qty)`` used).
            timestamp: Bar timestamp (anything ``pd.Timestamp`` accepts).
            bar_volume: Reserved (per-bar volume) for future participation
                calibration. Currently unused; impact uses ``adv``.

        Returns:
            Total cost in bps. Zero when ``qty == 0``.
        """
        _ = price  # not used in the bps calculation today
        if qty == 0.0:
            return 0.0
        spread = self._spread_at(timestamp)
        mult = self._participation_mult(timestamp)
        impact = self._impact_bps(qty)
        return spread * mult + impact


__all__ = [
    "IntradayCostModel",
    "default_us_equity_curve",
    "default_crypto_curve",
    "estimate_spread_from_high_low",
]
