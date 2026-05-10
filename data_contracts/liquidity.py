"""R163 - Liquidity, cost and capacity dataset.

Joins per-symbol liquidity, cost and capacity primitives into a single
record suitable for routing decisions and operator review.

The math primitives live elsewhere:

* ``aurora.core.slippage`` - size-vs-ADV slippage models. We use
  :class:`~aurora.core.slippage.SquareRootSlippage` (Almgren-Chriss
  square-root impact) to estimate per-symbol slippage in bps for a
  reference notional.
* ``aurora.validation.capacity_estimator`` - AUM-grid capacity stress
  test. We use the same ``slippage_coef`` notion to derive a symbol
  capacity band: the AUM at which size-driven slippage erodes a
  reference Sharpe. The full grid sweep lives in the validator; the
  per-symbol record only carries a single number ("capacity_usd"),
  derived from ADV times a participation cap.

This module owns the **dataset assembly**, the **labelling rule** that
every estimated quantity must declare itself estimated, and the
**gating logic** that refuses orders against thin symbols.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, List, Literal, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from aurora.core.slippage import SquareRootSlippage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_BPS = 1e4
_TRADING_DAYS = 252

# Default participation cap for capacity. A strategy is allowed to
# absorb up to this fraction of ADV per day before we treat it as
# capacity-saturating. 5% is the conventional desk default; tighter
# desks use 3% or lower.
_DEFAULT_PARTICIPATION_CAP = 0.05

# Default fall-back spread (bps) when we have no observed quote depth
# and the proxy collapses (e.g. zero variance window). 5 bps is a
# liquid US single-stock baseline; the value is labelled "estimated"
# and never silently fed back as observed.
_DEFAULT_FALLBACK_SPREAD_BPS = 5.0

# Reference order size used when estimating slippage for the record.
# Expressed as a fraction of dollar volume so it does not depend on
# the absolute scale of the symbol.
_REFERENCE_ORDER_PARTICIPATION = 0.01

# Threshold below which we still flag the symbol as thin even if the
# user did not pass a floor (tests rely on this default not being zero).
_LOW_VOLUME_DEFAULT_FLOOR = 1.0e6  # $1m / day


ObservedOrEstimated = Literal["observed", "estimated"]


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiquidityRecord:
    """Per-symbol, per-asof liquidity profile.

    All cost and capacity numbers are estimated unless the caller
    supplies observed market data; the ``observed_or_estimated`` field
    advertises which mode produced the values.
    """

    symbol: str
    asof_date: pd.Timestamp
    rolling_adv: float
    dollar_volume: float
    volatility_annualised: float
    turnover: float
    estimated_spread_bps: float
    estimated_slippage_bps: float
    capacity_usd: float
    low_volume_flag: bool
    observed_or_estimated: ObservedOrEstimated
    source: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["asof_date"] = pd.Timestamp(self.asof_date).isoformat()
        return d


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _ensure_window_columns(prices: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """Pull ``close`` and ``volume`` out of ``prices`` defensively."""
    if "close" not in prices.columns:
        raise ValueError("prices must include a 'close' column")
    if "volume" not in prices.columns:
        raise ValueError("prices must include a 'volume' column")
    close = pd.to_numeric(prices["close"], errors="raise").astype(float)
    volume = pd.to_numeric(prices["volume"], errors="raise").astype(float)
    return close, volume


def _slice_window(
    close: pd.Series,
    volume: pd.Series,
    asof: pd.Timestamp,
    window: int,
) -> Tuple[pd.Series, pd.Series]:
    """Return the trailing-``window`` slice ending at ``asof`` (inclusive)."""
    if window <= 1:
        raise ValueError(f"window must be > 1, got {window}")
    asof = pd.Timestamp(asof)
    cmask = close.index <= asof
    vmask = volume.index <= asof
    c = close.loc[cmask].tail(window)
    v = volume.loc[vmask].tail(window)
    if len(c) < 2 or len(v) < 2:
        raise ValueError(
            f"need at least 2 rows in trailing window ending {asof}, "
            f"got {len(c)} close / {len(v)} volume"
        )
    # Reindex volume to share the same index as close (in case providers
    # have small calendar mismatches); inner-join keeps determinism.
    aligned = pd.concat([c.rename("close"), v.rename("volume")], axis=1, join="inner")
    return aligned["close"], aligned["volume"]


def _rolling_adv(close: pd.Series, volume: pd.Series) -> float:
    """Mean dollar volume across the window."""
    dv = (close * volume).astype(float)
    return float(dv.mean())


def _dollar_volume_sum(close: pd.Series, volume: pd.Series) -> float:
    """Total dollar volume traded across the window (close * volume, summed)."""
    return float((close * volume).sum())


def _annualised_vol(close: pd.Series) -> float:
    """Annualised volatility from log returns. Returns 0.0 for flat series."""
    if len(close) < 2:
        return 0.0
    rets = np.log(close / close.shift(1)).dropna()
    if len(rets) == 0:
        return 0.0
    sd = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    return float(sd * np.sqrt(_TRADING_DAYS))


def _turnover_ratio(close: pd.Series, volume: pd.Series) -> float:
    """Coefficient of variation of dollar volume across the window.

    For constant ADV this is 0. For erratic volume it grows; the
    operator uses it as a "is this symbol's liquidity stable?" proxy.
    """
    dv = (close * volume).astype(float)
    mean = float(dv.mean())
    if mean <= 0.0:
        return 0.0
    sd = float(dv.std(ddof=1)) if len(dv) > 1 else 0.0
    return sd / mean


def _estimate_spread_bps(close: pd.Series, vol_annualised: float) -> float:
    """Corwin-Schultz-flavoured spread proxy from realised vol.

    We do not have intraday high/low here so we use a conservative
    Roll-style proxy: spread_bps ~= 2 * sigma_daily * 1e4 capped at 50
    bps. When vol is zero we fall back to the desk default.

    This is **estimated** by definition; callers must propagate the
    label.
    """
    if vol_annualised <= 0.0:
        return _DEFAULT_FALLBACK_SPREAD_BPS
    sigma_daily = vol_annualised / np.sqrt(_TRADING_DAYS)
    proxy = 2.0 * sigma_daily * _BPS
    return float(min(proxy, 50.0))


def _estimate_slippage_bps(
    rolling_adv: float, vol_annualised: float
) -> float:
    """Almgren-Chriss square-root slippage at a reference participation."""
    if rolling_adv <= 0.0:
        return float("nan")
    sigma_daily = (
        vol_annualised / np.sqrt(_TRADING_DAYS)
        if vol_annualised > 0.0
        else 0.0
    )
    model = SquareRootSlippage(coefficient_bps=100.0, sigma_daily=sigma_daily)
    order_size = rolling_adv * _REFERENCE_ORDER_PARTICIPATION
    return float(
        model.impact_bps(order_size_dollars=order_size, daily_volume_dollars=rolling_adv)
    )


def _capacity_band(
    rolling_adv: float, participation_cap: float = _DEFAULT_PARTICIPATION_CAP
) -> float:
    """Per-day capacity in USD, capped at ``participation_cap`` of ADV."""
    if rolling_adv <= 0.0:
        return 0.0
    return float(rolling_adv * participation_cap)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_liquidity_features(
    prices: pd.DataFrame,
    *,
    symbol: str,
    asof: pd.Timestamp,
    window: int = 20,
    participation_cap: float = _DEFAULT_PARTICIPATION_CAP,
    low_volume_floor: float = _LOW_VOLUME_DEFAULT_FLOOR,
    source: str = "",
) -> LiquidityRecord:
    """Build a :class:`LiquidityRecord` from a price+volume DataFrame.

    Args:
        prices: DataFrame indexed by date with at least ``close`` and
            ``volume`` columns. Index must be sortable and ``asof`` must
            be present (or earlier rows must exist).
        symbol: instrument identifier the record represents.
        asof: trailing window anchor; record describes liquidity as of
            this date.
        window: trailing window length in rows (typically business days).
        participation_cap: max fraction of ADV the desk is willing to
            consume per day. Drives ``capacity_usd``.
        low_volume_floor: ADV (USD) below which the symbol is flagged
            as low volume.
        source: free-form provider hint propagated into the record.

    Returns:
        A frozen :class:`LiquidityRecord`. Spread and slippage carry
        ``observed_or_estimated="estimated"`` because they are derived
        from price-only proxies.
    """
    if not isinstance(prices, pd.DataFrame):
        raise TypeError("prices must be a pandas DataFrame")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be a non-empty string")
    asof = pd.Timestamp(asof)

    close, volume = _ensure_window_columns(prices)
    c_win, v_win = _slice_window(close, volume, asof, window)

    rolling_adv = _rolling_adv(c_win, v_win)
    dv_sum = _dollar_volume_sum(c_win, v_win)
    vol_ann = _annualised_vol(c_win)
    turnover = _turnover_ratio(c_win, v_win)
    spread_bps = _estimate_spread_bps(c_win, vol_ann)
    slip_bps = _estimate_slippage_bps(rolling_adv, vol_ann)
    cap_usd = _capacity_band(rolling_adv, participation_cap)
    low_vol = bool(rolling_adv < low_volume_floor)

    return LiquidityRecord(
        symbol=symbol,
        asof_date=asof,
        rolling_adv=float(rolling_adv),
        dollar_volume=float(dv_sum),
        volatility_annualised=float(vol_ann),
        turnover=float(turnover),
        estimated_spread_bps=float(spread_bps),
        estimated_slippage_bps=float(slip_bps),
        capacity_usd=float(cap_usd),
        low_volume_flag=low_vol,
        observed_or_estimated="estimated",
        source=source,
    )


def flag_thin_symbols(
    records: Sequence[LiquidityRecord],
    *,
    min_dollar_volume: float,
    min_adv: float,
) -> List[str]:
    """Return symbols whose ADV or window dollar volume is below the floor.

    The result is sorted alphabetically so operator output is
    deterministic.
    """
    if min_dollar_volume < 0.0:
        raise ValueError("min_dollar_volume must be >= 0")
    if min_adv < 0.0:
        raise ValueError("min_adv must be >= 0")
    thin: List[str] = []
    for r in records:
        if r.rolling_adv < min_adv or r.dollar_volume < min_dollar_volume:
            thin.append(r.symbol)
    return sorted(thin)


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiquidityValidationGate:
    """Capacity-aware order gate.

    Refuses an order when:

    1. The order's notional exceeds the symbol's ``capacity_usd`` band.
    2. The capacity-adjusted Sharpe drops below ``sharpe_floor_pct`` of
       a clean comparison Sharpe (caller supplies both).
    3. The record is flagged as a low-volume symbol.

    The gate is a frozen dataclass so it can be pickled and shipped as
    a guard in deployment code.
    """

    sharpe_floor_pct: float = 0.5

    def __call__(
        self,
        record: LiquidityRecord,
        *,
        avg_order_size_usd: float,
        clean_sharpe: Optional[float] = None,
        capacity_adjusted_sharpe: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Evaluate the order against the record.

        Args:
            record: per-symbol liquidity profile.
            avg_order_size_usd: average notional the strategy is sending
                per execution.
            clean_sharpe: comparison Sharpe with no liquidity drag.
            capacity_adjusted_sharpe: same Sharpe but after slippage and
                capacity-driven impact has been applied.

        Returns:
            ``(allowed, reason)``. ``reason`` is a plain-English string
            the operator can display verbatim.
        """
        if avg_order_size_usd < 0.0:
            raise ValueError("avg_order_size_usd must be >= 0")
        if not (0.0 < self.sharpe_floor_pct <= 1.0):
            raise ValueError("sharpe_floor_pct must be in (0, 1]")

        if record.low_volume_flag:
            return (
                False,
                f"refused: symbol {record.symbol} flagged as low-volume "
                f"(rolling ADV ${record.rolling_adv:,.0f}).",
            )

        if avg_order_size_usd > record.capacity_usd:
            return (
                False,
                f"refused: average order size ${avg_order_size_usd:,.0f} "
                f"exceeds {record.symbol} capacity band "
                f"${record.capacity_usd:,.0f}.",
            )

        if (
            clean_sharpe is not None
            and capacity_adjusted_sharpe is not None
            and clean_sharpe > 0.0
            and capacity_adjusted_sharpe < clean_sharpe * self.sharpe_floor_pct
        ):
            return (
                False,
                f"refused: capacity-adjusted Sharpe {capacity_adjusted_sharpe:.3f} "
                f"collapsed below {self.sharpe_floor_pct * 100:.0f}% of clean "
                f"Sharpe {clean_sharpe:.3f} for {record.symbol}.",
            )

        return (True, f"allowed: {record.symbol} within capacity band.")


__all__ = [
    "LiquidityRecord",
    "LiquidityValidationGate",
    "compute_liquidity_features",
    "flag_thin_symbols",
]
