"""Microstructure features.

Reference: Lopez de Prado, "Advances in Financial Machine Learning" Ch.19.

Implements bid-ask spread estimators (Corwin-Schultz, Roll), trade-direction
sign rule (Lee-Ready tick rule), order-flow imbalance, VPIN
(volume-synchronized PIN), Kyle's lambda and Amihud illiquidity.

Public API:
- corwin_schultz_spread:  bid-ask spread from OHLC high/low.
- roll_spread_estimator:  Roll's serial-covariance spread.
- signed_volume:          Lee-Ready signed volume (tick rule).
- order_flow_imbalance:   rolling sum of signed volume.
- vpin:                   Volume-Synchronized PIN.
- kyle_lambda:            rolling regression of dP on signed_V.
- amihud_illiquidity:     rolling mean of |return| / dollar_volume.

All functions return a pd.Series indexed identically to the primary input.
The first ``window-1`` rows of every rolling statistic are NaN.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# numba optional — fall back to pure numpy when missing
try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def deco(fn):
            return fn

        return deco


# ---------------------------------------------------------------------------
# Corwin-Schultz spread
# ---------------------------------------------------------------------------

def corwin_schultz_spread(
    high: pd.Series,
    low: pd.Series,
    window: int = 2,
) -> pd.Series:
    """Corwin-Schultz bid-ask spread estimator from OHLC high/low.

    Reference: Corwin & Schultz (2012), "A Simple Way to Estimate Bid-Ask
    Spreads from Daily High and Low Prices", Journal of Finance.

    For two consecutive bars i, i+1:
        beta  = log(H_i  / L_i )^2  + log(H_{i+1} / L_{i+1})^2
        gamma = log(max(H_i, H_{i+1}) / min(L_i, L_{i+1}))^2
        alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2))
                - sqrt(gamma / (3 - 2*sqrt(2)))
        spread = 2 * (exp(alpha) - 1) / (1 + exp(alpha))

    The estimator can be negative for very tight spreads; we floor at zero
    bar-by-bar before averaging, as in the original paper.

    Args:
        high:   Series of bar highs.
        low:    Series of bar lows.
        window: rolling window over which to average the per-pair estimates.
                ``window=2`` (default) gives the raw 2-bar estimator on the
                rolling pair and produces NaN for the first bar only.

    Returns:
        Series of estimated spreads as a fraction of price (not bps),
        indexed identically to ``high``.
    """
    if not isinstance(high, pd.Series):
        raise TypeError("high must be a pd.Series")
    if not isinstance(low, pd.Series):
        raise TypeError("low must be a pd.Series")
    if len(high) != len(low):
        raise ValueError("high and low must have the same length")
    if window < 2:
        raise ValueError("window must be >= 2")

    h = high.astype(float).to_numpy()
    l = low.astype(float).to_numpy()
    n = len(h)

    # Per-pair (i, i+1) raw estimate; result aligned to bar i+1.
    pair = np.full(n, np.nan)
    if n >= 2:
        log_hl_sq = np.log(h / l) ** 2  # bar-level

        h_pair_max = np.maximum(h[:-1], h[1:])
        l_pair_min = np.minimum(l[:-1], l[1:])
        beta = log_hl_sq[:-1] + log_hl_sq[1:]
        gamma = np.log(h_pair_max / l_pair_min) ** 2

        denom = 3.0 - 2.0 * np.sqrt(2.0)
        with np.errstate(invalid="ignore"):
            alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denom \
                    - np.sqrt(gamma / denom)
            spread_pair = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))

        # Per Corwin-Schultz: floor negative two-bar estimates at zero.
        spread_pair = np.where(np.isfinite(spread_pair) & (spread_pair > 0),
                               spread_pair, 0.0)
        pair[1:] = spread_pair

    s = pd.Series(pair, index=high.index, name="cs_spread")
    if window == 2:
        return s
    # Smooth with a rolling mean of width (window - 1) over the per-pair
    # estimates so total warm-up = window - 1 bars (first bar NaN from pair,
    # plus the rolling mean min_periods).
    return s.rolling(window=window - 1, min_periods=window - 1).mean()


# ---------------------------------------------------------------------------
# Roll spread estimator
# ---------------------------------------------------------------------------

def roll_spread_estimator(
    prices: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Roll's serial-covariance bid-ask spread estimator.

    Reference: Roll (1984), "A Simple Implicit Measure of the Effective
    Bid-Ask Spread in an Efficient Market".

    For a window of consecutive price changes dP_t = P_t - P_{t-1}:
        c = cov(dP_t, dP_{t-1})
        spread = 2 * sqrt(-c)   if c < 0
        spread = 0              otherwise (positive autocovariance is not
                                consistent with the bid-ask bounce model).

    The resulting spread is in price units (the same units as ``prices``).

    Args:
        prices: Series of trade prices.
        window: rolling window in bars over which the autocovariance is
                computed. Must be >= 3.

    Returns:
        Series of spread estimates aligned to ``prices``. The first
        ``window - 1`` values are NaN.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pd.Series")
    if window < 3:
        raise ValueError("window must be >= 3")

    dp = prices.astype(float).diff()
    # cov(dp_t, dp_{t-1}) over rolling window of dP.
    # We use the formula cov = E[X*Y] - E[X]*E[Y] over the rolling window
    # of (dp_t, dp_{t-1}) pairs.
    dp_lag = dp.shift(1)
    prod = dp * dp_lag
    mean_prod = prod.rolling(window=window, min_periods=window).mean()
    mean_dp = dp.rolling(window=window, min_periods=window).mean()
    mean_dp_lag = dp_lag.rolling(window=window, min_periods=window).mean()
    cov = mean_prod - mean_dp * mean_dp_lag

    spread = np.where(cov < 0, 2.0 * np.sqrt(-cov.clip(upper=0.0)), 0.0)
    out = pd.Series(spread, index=prices.index, name="roll_spread")
    # Where cov is NaN (warm-up), out should be NaN too.
    out[cov.isna()] = np.nan
    return out


# ---------------------------------------------------------------------------
# Signed volume (Lee-Ready tick rule)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _tick_rule_signs(prices: np.ndarray) -> np.ndarray:
    """Tick-rule signs: +1 on uptick, -1 on downtick, prev sign on flat.

    By convention the very first bar carries sign 0 (no previous sign).
    Non-finite price diffs (NaN, +/-inf) propagate to NaN sign at that bar
    so callers can spot bad data instead of silently inheriting the last sign.
    """
    n = prices.shape[0]
    signs = np.zeros(n, dtype=np.float64)
    if n == 0:
        return signs
    last = 0.0
    for i in range(1, n):
        diff = prices[i] - prices[i - 1]
        if not np.isfinite(diff):
            signs[i] = np.nan
            continue
        if diff > 0.0:
            last = 1.0
        elif diff < 0.0:
            last = -1.0
        # else: keep last
        signs[i] = last
    return signs


def signed_volume(
    close: pd.Series,
    volume: pd.Series,
    method: str = "tick_rule",
) -> pd.Series:
    """Lee-Ready signed volume.

    Tick rule: classify each trade as buyer-initiated (+1) on an uptick,
    seller-initiated (-1) on a downtick, and carry the previous sign on a
    flat tick.

    Args:
        close:  Series of trade prices.
        volume: Series of trade volumes (same index as ``close``).
        method: only ``"tick_rule"`` is implemented.

    Returns:
        Series of signed volume (sign * |volume|) aligned to ``close``.
        The first observation is 0 (no previous sign defined).
    """
    if not isinstance(close, pd.Series):
        raise TypeError("close must be a pd.Series")
    if not isinstance(volume, pd.Series):
        raise TypeError("volume must be a pd.Series")
    if len(close) != len(volume):
        raise ValueError("close and volume must have the same length")
    if method != "tick_rule":
        raise ValueError(f"unknown method: {method}")

    p = close.astype(float).to_numpy()
    v = volume.astype(float).to_numpy()
    signs = _tick_rule_signs(p)
    out = pd.Series(signs * v, index=close.index, name="signed_volume")
    return out


# ---------------------------------------------------------------------------
# Order-flow imbalance
# ---------------------------------------------------------------------------

def order_flow_imbalance(
    signed_vol: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Rolling sum of signed volume.

    Args:
        signed_vol: output of ``signed_volume``.
        window:     rolling window in bars. Must be >= 1.

    Returns:
        Series of rolling sums aligned to ``signed_vol``. The first
        ``window - 1`` values are NaN.
    """
    if not isinstance(signed_vol, pd.Series):
        raise TypeError("signed_vol must be a pd.Series")
    if window < 1:
        raise ValueError("window must be >= 1")
    out = signed_vol.rolling(window=window, min_periods=window).sum()
    out.name = "ofi"
    return out


# ---------------------------------------------------------------------------
# VPIN
# ---------------------------------------------------------------------------

def vpin(
    close: pd.Series,
    volume: pd.Series,
    n_buckets: int = 50,
    window: int = 50,
) -> pd.Series:
    """Volume-Synchronized Probability of Informed Trading.

    Reference: Easley, Lopez de Prado & O'Hara (2012).

    Procedure:
      1. Sign each bar's volume via the tick rule.
      2. Bucket trades into equal-volume buckets of size
         ``bucket_size = total_volume / n_buckets``.
      3. For each bucket compute ``|buy_vol - sell_vol| / bucket_vol``.
      4. VPIN_t = rolling mean over ``window`` buckets, mapped back to bar
         time at the bar that closed the trailing bucket.

    Args:
        close:     Series of close prices.
        volume:    Series of bar volumes (same index as ``close``).
        n_buckets: number of equal-volume buckets to slice the *total* sample
                   into. Sets the bucket size.
        window:    number of buckets to average for the VPIN value.

    Returns:
        Series of VPIN values in [0, 1] aligned to ``close``. Bars whose
        cumulative volume has not yet completed the ``window``-th bucket are
        NaN.
    """
    if not isinstance(close, pd.Series):
        raise TypeError("close must be a pd.Series")
    if not isinstance(volume, pd.Series):
        raise TypeError("volume must be a pd.Series")
    if len(close) != len(volume):
        raise ValueError("close and volume must have the same length")
    if n_buckets < 1:
        raise ValueError("n_buckets must be >= 1")
    if window < 1:
        raise ValueError("window must be >= 1")

    sv = signed_volume(close, volume).to_numpy()
    av = volume.astype(float).to_numpy()
    total = float(av[av > 0].sum()) if (av > 0).any() else 0.0
    out = pd.Series(np.nan, index=close.index, name="vpin")
    if total <= 0:
        return out
    bucket_size = total / float(n_buckets)
    if bucket_size <= 0:
        return out

    # Walk bar-by-bar tracking when each bucket closes; record the closing
    # bar index for each completed bucket and that bucket's |imbalance|/vol.
    n = len(close)
    bucket_imb = []
    bucket_close_bar = []
    cur_buy = 0.0
    cur_sell = 0.0
    cur_vol = 0.0
    for i in range(n):
        v_i = av[i]
        s_i = sv[i]
        if v_i <= 0.0:
            continue
        # Skip bars whose signed-volume is non-finite (NaN/inf) so they don't
        # silently fall into the unsigned `else` branch and corrupt buy/sell
        # accumulation downstream.
        if not np.isfinite(s_i):
            continue
        remaining = v_i
        if s_i > 0.0:
            sign_i = 1.0
        elif s_i < 0.0:
            sign_i = -1.0
        else:
            sign_i = 0.0
        while remaining > 0.0:
            need = bucket_size - cur_vol
            take = remaining if remaining < need else need
            if sign_i > 0.0:
                cur_buy += take
            elif sign_i < 0.0:
                cur_sell += take
            cur_vol += take
            remaining -= take
            if cur_vol >= bucket_size - 1e-12:
                imb = abs(cur_buy - cur_sell)
                bucket_imb.append(imb / bucket_size)
                bucket_close_bar.append(i)
                cur_buy = 0.0
                cur_sell = 0.0
                cur_vol = 0.0

    if len(bucket_imb) < window:
        return out

    arr = np.asarray(bucket_imb, dtype=float)
    # Rolling mean over the last `window` buckets (right-aligned, AFML eq.
    # 19.2). roll[k] = mean(arr[k : k + window]) covers buckets k..k+window-1;
    # the LAST (right-edge) bucket in that window is index ``k + window - 1``.
    # That is the bucket whose closing bar should carry the VPIN value.
    csum = np.concatenate(([0.0], np.cumsum(arr)))
    roll = (csum[window:] - csum[:-window]) / float(window)
    for k, val in enumerate(roll):
        right_edge_bucket = k + window - 1
        bar_idx = bucket_close_bar[right_edge_bucket]
        # Multiple buckets can close on the same bar (high-volume bars). To
        # keep the assignment deterministic and conservative, retain the
        # MAXIMUM VPIN observed at that bar rather than letting a later
        # bucket silently overwrite an earlier (possibly larger) imbalance.
        prior = out.iloc[bar_idx]
        if not np.isfinite(prior) or val > prior:
            out.iloc[bar_idx] = val
    # Forward-fill within bars that share a bucket boundary not yet replaced
    # (bars between two consecutive bucket closes inherit the most recent
    # VPIN), but bars before the first completed window stay NaN. Bound the
    # ffill to ``window`` bars so that a long tail of bars without any new
    # bucket closing does not silently propagate a stale VPIN value forever.
    out = out.ffill(limit=int(window))
    return out


# ---------------------------------------------------------------------------
# Kyle's lambda
# ---------------------------------------------------------------------------

def kyle_lambda(
    prices: pd.Series,
    volumes: pd.Series,
    window: int = 50,
) -> pd.Series:
    """Kyle's lambda: price-impact coefficient.

    Reference: Kyle (1985), "Continuous Auctions and Insider Trading".

    For a rolling window of ``window`` bars:
        dP_t        = P_t - P_{t-1}
        signed_V_t  = sign(dP_t) * V_t   (tick-rule signed volume)
        lambda_t    = cov(dP, signed_V) / var(signed_V)

    A higher lambda => less liquidity (each unit of signed volume moves the
    price more).

    Args:
        prices:  Series of prices.
        volumes: Series of bar volumes.
        window:  rolling window. Must be >= 3.

    Returns:
        Series of lambda values aligned to ``prices``. The first
        ``window - 1`` values are NaN.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pd.Series")
    if not isinstance(volumes, pd.Series):
        raise TypeError("volumes must be a pd.Series")
    if len(prices) != len(volumes):
        raise ValueError("prices and volumes must have the same length")
    if window < 3:
        raise ValueError("window must be >= 3")

    dp = prices.astype(float).diff()
    sv = signed_volume(prices, volumes)

    # Vectorized rolling cov / var:
    #   cov(X,Y) = E[XY] - E[X]E[Y]
    #   var(Y)   = E[Y^2] - E[Y]^2
    xy = (dp * sv)
    yy = (sv * sv)
    mean_x = dp.rolling(window=window, min_periods=window).mean()
    mean_y = sv.rolling(window=window, min_periods=window).mean()
    mean_xy = xy.rolling(window=window, min_periods=window).mean()
    mean_yy = yy.rolling(window=window, min_periods=window).mean()

    cov = mean_xy - mean_x * mean_y
    var = mean_yy - mean_y * mean_y
    lam = cov / var.where(var > 0)
    lam.name = "kyle_lambda"
    return lam


# ---------------------------------------------------------------------------
# Amihud illiquidity
# ---------------------------------------------------------------------------

def amihud_illiquidity(
    returns: pd.Series,
    dollar_volume: pd.Series,
    window: int = 21,
) -> pd.Series:
    """Amihud (2002) illiquidity measure.

    illiq_t = rolling_mean( |return_t| / dollar_volume_t , window )

    Higher values indicate that a unit of trading dollar volume corresponds
    to larger absolute returns, i.e. lower liquidity.

    Args:
        returns:       Series of bar returns (e.g. simple returns).
        dollar_volume: Series of dollar volume per bar (price * volume).
        window:        rolling window. Must be >= 1.

    Returns:
        Series of Amihud illiquidity values aligned to ``returns``. Bars
        with non-positive dollar volume produce NaN before averaging; the
        first ``window - 1`` rolling outputs are NaN.
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be a pd.Series")
    if not isinstance(dollar_volume, pd.Series):
        raise TypeError("dollar_volume must be a pd.Series")
    if len(returns) != len(dollar_volume):
        raise ValueError("returns and dollar_volume must have the same length")
    if window < 1:
        raise ValueError("window must be >= 1")

    r = returns.astype(float).abs()
    dv = dollar_volume.astype(float)
    ratio = r / dv.where(dv > 0)
    out = ratio.rolling(window=window, min_periods=window).mean()
    out.name = "amihud_illiq"
    return out


__all__ = [
    "corwin_schultz_spread",
    "roll_spread_estimator",
    "signed_volume",
    "order_flow_imbalance",
    "vpin",
    "kyle_lambda",
    "amihud_illiquidity",
]
