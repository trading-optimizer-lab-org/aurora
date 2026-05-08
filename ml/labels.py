"""Triple-barrier labeling, meta-labeling and bet sizing.

Reference: Lopez de Prado, "Advances in Financial Machine Learning" Ch.3-4.
Adapted from mlfinlab/labeling.py and mlfinlab/bet_sizing.py.

Public API:
- daily_volatility:   EWMA std of log returns, used as base for adaptive barriers.
- triple_barrier_labels: profit-taking / stop-loss / vertical-time barriers.
- meta_labels:        binary labels for a meta-model (was the primary signal right?).
- bet_size_from_proba: classifier probabilities -> position size in [-1, 1].
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
import pandas as pd
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class TripleBarrierResult:
    """Output of triple-barrier labeling.

    labels:           Series of {-1, 0, +1}, indexed by event start.
    touch_times:      DataFrame with cols
                      ['pt_touch','sl_touch','t1_touch','first_touch','valid_vol'].
                      NaT means barrier never reached within the holding window.
                      ``valid_vol`` is True only when the per-event vol estimate
                      was finite and positive (barriers actually sized).
    returns:          price-move return at first_touch (P_touch/P_entry - 1).
                      The realized PnL on the trade is ``side * returns``;
                      slippage (when configured) is applied to ``returns`` so
                      that ``side * returns`` already nets out slippage.
    target_volatility: vol estimate used to size the barriers (NaN when the
                      vertical-timeout fallback path was taken).
    """
    labels: pd.Series
    touch_times: pd.DataFrame
    returns: pd.Series
    target_volatility: pd.Series


# ---------------------------------------------------------------------------
# Daily volatility (EWMA std of log returns)
# ---------------------------------------------------------------------------

def daily_volatility(prices: pd.Series, lookback: int = 100) -> pd.Series:
    """EWMA std of log returns. Used as base for adaptive triple barriers.

    Args:
        prices:   Series of prices (indexed by datetime, monotonic increasing).
        lookback: span of the EWMA.

    Returns:
        Series of vol estimates aligned to `prices` (NaN for the first obs).
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pd.Series")
    if lookback < 2:
        raise ValueError("lookback must be >= 2")

    log_ret = np.log(prices).diff()
    vol = log_ret.ewm(span=lookback, min_periods=max(2, lookback // 4)).std()
    vol.name = "daily_vol"
    return vol


# ---------------------------------------------------------------------------
# Triple-barrier labeling
# ---------------------------------------------------------------------------

def triple_barrier_labels(
    prices: pd.Series,
    events: pd.DatetimeIndex,
    pt_sl_factors: Tuple[float, float] = (1.0, 1.0),
    holding_period_days: int = 5,
    vol: Optional[pd.Series] = None,
    min_return: float = 0.0,
    events_max_index: Optional[pd.Timestamp] = None,
    slippage_bps: float = 0.0,
    side: int = 1,
    bars_per_window: Optional[int] = None,
    nan_policy: str = "warn",
    nan_threshold: float = 0.05,
    tie_break: str = "sl",
) -> TripleBarrierResult:
    """Apply the triple-barrier method to a set of event timestamps.

    For each event timestamp t0 with price P0 and vol sigma:
      - profit barrier:  P0 * (1 + pt_sl_factors[0] * sigma)
      - stop   barrier:  P0 * (1 - pt_sl_factors[1] * sigma)
      - vertical barrier: t0 + holding_period_days (in calendar days)

    Barrier search is strictly forward-looking: the bar at t0 is excluded
    from the PT/SL touch search (the event entry itself cannot be the touch).

    Label = sign of return at first touch:
        +1 if PT hit first
        -1 if SL hit first
         0 if vertical barrier reached first (or |ret| < min_return)

    Args:
        prices:             price Series (indexed by datetime).
        events:             DatetimeIndex of event start times (must be in prices.index).
        pt_sl_factors:      (pt_mult, sl_mult). Set a side to 0 to disable that barrier.
        holding_period_days: vertical barrier in calendar days from each event.
        vol:                optional pre-computed vol Series. If None, computed via
                            daily_volatility(prices, 100).
        min_return:         if |return at first touch| < min_return, label = 0.
        events_max_index:   optional cutoff timestamp. If provided, raises
                            ValueError when any event in `events` has
                            timestamp > events_max_index. Use this to enforce
                            that the event-defining feature (e.g. the
                            volatility estimator) was computed using only data
                            through `events_max_index`, with no lookahead.
        slippage_bps:       round-trip slippage in basis points applied at
                            barrier touches. For longs (side=+1) PT realized
                            return is reduced and SL realized return is
                            increased (more negative for stops). For shorts
                            (side=-1) the signs flip. Vertical-barrier exits
                            are not adjusted (mark-to-market, no execution).
        side:               +1 for long entries (default), -1 for shorts.
                            Only affects the slippage adjustment direction;
                            label semantics still reflect price moves.
        bars_per_window:    optional integer to bound the holding window in
                            number of bars (positional) instead of (or in
                            addition to) ``holding_period_days``. When set,
                            barrier search uses a positional slice of length
                            ``bars_per_window`` starting at the event bar.
                            Robust to duplicate-indexed timestamps.
        nan_policy:         how to handle events whose vol estimate is
                            non-finite or non-positive: ``'warn'`` (default,
                            silent fallback to vertical exit + warning if
                            > ``nan_threshold`` fraction affected),
                            ``'raise'`` (ValueError), or ``'drop'``
                            (silently exclude offending events from result).
        nan_threshold:      fraction of events whose vol is non-finite that
                            triggers a warning under ``nan_policy='warn'``.
        tie_break:          how to resolve a tie when PT and SL touch on the
                            SAME timestamp. ``'sl'`` (default, conservative)
                            picks the stop-loss so long-side PnL is the
                            pessimistic estimate; ``'pt'`` picks the profit-
                            target. Vertical-barrier ties with PT or SL are
                            always resolved in favor of the corresponding
                            barrier (PT or SL beats t1 on equality).

    Returns:
        TripleBarrierResult.
    """
    if tie_break not in ("sl", "pt"):
        raise ValueError("tie_break must be 'sl' or 'pt'")
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pd.Series")
    if not prices.index.is_unique:
        raise ValueError(
            "prices.index must be unique; duplicated timestamps break "
            "barrier label-based slicing. Drop duplicates upstream."
        )
    if len(prices) == 0:
        raise ValueError("prices is empty")
    if pt_sl_factors[0] < 0 or pt_sl_factors[1] < 0:
        raise ValueError("pt_sl_factors must be non-negative")
    if holding_period_days <= 0:
        raise ValueError("holding_period_days must be > 0")
    if slippage_bps < 0:
        raise ValueError("slippage_bps must be >= 0")
    if side not in (-1, 1):
        raise ValueError("side must be +1 (long) or -1 (short)")
    if bars_per_window is not None and bars_per_window < 2:
        raise ValueError("bars_per_window must be >= 2 when provided")
    if nan_policy not in ("warn", "raise", "drop"):
        raise ValueError("nan_policy must be one of {'warn','raise','drop'}")
    if not (0.0 <= nan_threshold <= 1.0):
        raise ValueError("nan_threshold must be in [0, 1]")

    events = pd.DatetimeIndex(events)
    # Lookahead guard: refuse events past the cutoff to ensure the features
    # that produced these events did not see future data.
    if events_max_index is not None and len(events) > 0:
        cutoff = pd.Timestamp(events_max_index)
        offending = events[events > cutoff]
        if len(offending) > 0:
            raise ValueError(
                f"triple_barrier_labels: {len(offending)} event(s) have "
                f"timestamp > events_max_index ({cutoff}); "
                f"first offending: {offending[0]}. This indicates the "
                "event-defining feature may have used data after the event "
                "timestamp (lookahead bias)."
            )
    # keep only events present in the price index
    events = events[events.isin(prices.index)]
    # Defensive dedupe: downstream label assignment assumes unique event indices.
    events = events[~events.duplicated(keep="first")]
    if len(events) == 0:
        empty_idx = pd.DatetimeIndex([])
        # Build the empty touch_times frame with proper per-column dtypes so
        # downstream consumers (e.g. ``df['valid_vol'].astype(bool)``) don't
        # blow up on a default ``object`` dtype that pandas falls back to when
        # only column names are passed.
        empty_touch = pd.DataFrame({
            "pt_touch": pd.Series(dtype="datetime64[ns]"),
            "sl_touch": pd.Series(dtype="datetime64[ns]"),
            "t1_touch": pd.Series(dtype="datetime64[ns]"),
            "first_touch": pd.Series(dtype="datetime64[ns]"),
            "valid_vol": pd.Series(dtype=bool),
        })
        empty_touch.index = empty_idx
        return TripleBarrierResult(
            labels=pd.Series(dtype=np.int8, index=empty_idx, name="label"),
            touch_times=empty_touch,
            returns=pd.Series(dtype=float, index=empty_idx, name="ret"),
            target_volatility=pd.Series(dtype=float, index=empty_idx, name="daily_vol"),
        )

    if vol is None:
        vol = daily_volatility(prices, lookback=100)
    else:
        vol = vol.reindex(prices.index)

    # Account for vol availability on event timestamps
    vol_at_events = vol.reindex(events)
    n_bad_vol = int((~np.isfinite(vol_at_events.to_numpy(dtype=float))).sum())
    n_events = len(events)
    bad_frac = n_bad_vol / max(1, n_events)
    if n_bad_vol > 0:
        if nan_policy == "raise":
            raise ValueError(
                f"triple_barrier_labels: {n_bad_vol}/{n_events} events have "
                "non-finite vol estimates; refusing to proceed (nan_policy='raise')."
            )
        if nan_policy == "drop":
            keep = np.isfinite(vol_at_events.to_numpy(dtype=float))
            events = events[keep]
        elif nan_policy == "warn" and bad_frac > nan_threshold:
            warnings.warn(
                f"triple_barrier_labels: {n_bad_vol}/{n_events} events "
                f"({bad_frac:.1%}) have non-finite vol; using vertical-timeout fallback. "
                f"This exceeds nan_threshold={nan_threshold:.1%}.",
                UserWarning,
                stacklevel=2,
            )

    if len(events) == 0:
        empty_idx = pd.DatetimeIndex([])
        empty_touch = pd.DataFrame({
            "pt_touch": pd.Series(dtype="datetime64[ns]"),
            "sl_touch": pd.Series(dtype="datetime64[ns]"),
            "t1_touch": pd.Series(dtype="datetime64[ns]"),
            "first_touch": pd.Series(dtype="datetime64[ns]"),
            "valid_vol": pd.Series(dtype=bool),
        })
        empty_touch.index = empty_idx
        return TripleBarrierResult(
            labels=pd.Series(dtype=np.int8, index=empty_idx, name="label"),
            touch_times=empty_touch,
            returns=pd.Series(dtype=float, index=empty_idx, name="ret"),
            target_volatility=pd.Series(dtype=float, index=empty_idx, name="daily_vol"),
        )

    pt_mult, sl_mult = pt_sl_factors
    holding = pd.Timedelta(days=holding_period_days)

    pt_touch = pd.Series(pd.NaT, index=events, name="pt_touch")
    sl_touch = pd.Series(pd.NaT, index=events, name="sl_touch")
    t1_touch = pd.Series(pd.NaT, index=events, name="t1_touch")
    first_touch = pd.Series(pd.NaT, index=events, name="first_touch")
    rets = pd.Series(np.nan, index=events, name="ret")
    target_vol = pd.Series(np.nan, index=events, name="daily_vol")
    valid_vol = pd.Series(False, index=events, dtype=bool, name="valid_vol")
    labels = pd.Series(0, index=events, dtype=np.int8, name="label")

    prices_idx = prices.index
    prices_values = prices.to_numpy(dtype=float)

    for t0 in events:
        sigma = float(vol.loc[t0]) if t0 in vol.index else np.nan
        # Positional anchor for t0 in the price index (unique, as enforced above).
        i0 = prices_idx.get_loc(t0)
        if isinstance(i0, slice):  # defensive: shouldn't happen with unique index
            i0 = i0.start

        if not np.isfinite(sigma) or sigma <= 0:
            # cannot size barriers; vertical timeout fallback
            t1 = t0 + holding
            t1_mask = prices_idx <= t1
            if not t1_mask.any():
                continue
            t1_eff_pos = int(np.flatnonzero(t1_mask)[-1])
            t1_eff = prices_idx[t1_eff_pos]
            t1_touch.loc[t0] = t1_eff
            first_touch.loc[t0] = t1_eff
            rets.loc[t0] = float(prices_values[t1_eff_pos] / prices_values[i0] - 1.0)
            target_vol.loc[t0] = sigma
            labels.loc[t0] = 0
            continue

        target_vol.loc[t0] = sigma
        valid_vol.loc[t0] = True
        p0 = float(prices_values[i0])
        upper = p0 * (1.0 + pt_mult * sigma) if pt_mult > 0 else np.inf
        lower = p0 * (1.0 - sl_mult * sigma) if sl_mult > 0 else -np.inf

        # Positional slicing: avoids the ambiguity of pd.Series.loc[t0:t1] on
        # duplicated timestamps (which would otherwise return overlapping
        # ranges). When ``bars_per_window`` is provided, we cap the window
        # at that many bars; otherwise we walk the index forward up to the
        # vertical-time barrier using a calendar-time mask, then take the
        # positional slice.
        if bars_per_window is not None:
            i1_excl = min(len(prices_idx), i0 + bars_per_window)
        else:
            t1_target = t0 + holding
            # positions strictly within the holding window (inclusive of t0)
            t1_mask = prices_idx <= t1_target
            t1_mask &= prices_idx >= t0
            valid_pos = np.flatnonzero(t1_mask)
            if valid_pos.size == 0:
                continue
            i1_excl = int(valid_pos[-1]) + 1
            # Defensive: ensure window starts at i0
            i1_excl = max(i1_excl, i0 + 1)

        path = prices.iloc[i0:i1_excl]
        if len(path) <= 1:
            # not enough data after event; skip but record vertical = last avail
            t1_eff = path.index[-1] if len(path) else t0
            t1_touch.loc[t0] = t1_eff
            first_touch.loc[t0] = t1_eff
            rets.loc[t0] = 0.0 if len(path) == 0 else float(path.iloc[-1] / p0 - 1.0)
            labels.loc[t0] = 0
            continue

        # Strictly forward-looking: drop t0 itself so the entry bar cannot
        # be the touch bar. Equivalent to half-open interval (t0, t1_target].
        future = path.iloc[1:]
        pt_hits = future.index[future.values >= upper] if pt_mult > 0 else pd.DatetimeIndex([])
        sl_hits = future.index[future.values <= lower] if sl_mult > 0 else pd.DatetimeIndex([])

        pt_t = pt_hits[0] if len(pt_hits) > 0 else pd.NaT
        sl_t = sl_hits[0] if len(sl_hits) > 0 else pd.NaT
        t1_t = future.index[-1]

        pt_touch.loc[t0] = pt_t
        sl_touch.loc[t0] = sl_t
        t1_touch.loc[t0] = t1_t

        candidates = {"pt": pt_t, "sl": sl_t, "t1": t1_t}
        valid = {k: v for k, v in candidates.items() if not pd.isna(v)}
        # Resolve PT/SL/t1 ties explicitly:
        # - PT and SL on the SAME timestamp: ``tie_break`` decides ('sl' is the
        #   conservative default for long-side P&L; 'pt' is the optimistic
        #   choice). Without this, the result depends on the dict insertion
        #   order, which is brittle.
        # - PT or SL ties with t1: barrier wins (vertical exit reflects no
        #   touch, but if a touch did occur on the t1 bar we count it).
        sort_key = {"pt": 1, "sl": 0 if tie_break == "sl" else 2, "t1": 3}
        if tie_break == "pt":
            sort_key = {"pt": 0, "sl": 1, "t1": 2}
        first_kind = min(valid, key=lambda k: (valid[k], sort_key[k]))
        first_t = valid[first_kind]
        first_touch.loc[t0] = first_t

        ret = float(prices.loc[first_t] / p0 - 1.0)
        # ``ret`` stays a "price-move" (P_touch / P_entry - 1.0). The realized
        # signed PnL on the trade is ``side * ret`` minus slippage at execution
        # barriers. We back-convert to a price-move adjusted by ``side * slip``
        # so the returned ``ret`` continues to represent a price-move that, when
        # multiplied by ``side``, yields the realized PnL net of slippage.
        # Vertical exits are mark-to-market and not adjusted.
        if slippage_bps > 0 and first_kind in ("pt", "sl"):
            slip = slippage_bps / 10_000.0
            # signed_pnl = side * ret - slip  =>  ret_adj = ret - side * slip.
            ret = ret - side * slip
        rets.loc[t0] = ret

        if abs(ret) < min_return:
            labels.loc[t0] = 0
        elif first_kind == "pt":
            labels.loc[t0] = 1
        elif first_kind == "sl":
            labels.loc[t0] = -1
        else:  # t1 vertical
            labels.loc[t0] = 0

    touch_times = pd.concat(
        [pt_touch, sl_touch, t1_touch, first_touch, valid_vol], axis=1
    )
    return TripleBarrierResult(
        labels=labels,
        touch_times=touch_times,
        returns=rets,
        target_volatility=target_vol,
    )


# ---------------------------------------------------------------------------
# Meta-labeling
# ---------------------------------------------------------------------------

def meta_labels(
    primary_signals: pd.Series,
    returns: pd.Series,
    threshold: float = 0.0,
    nan_warn_threshold: float = 0.05,
) -> pd.Series:
    """Binary meta-labels: was the primary signal correct?

    For each event, label = 1 iff sign(primary) == sign(return) AND |return| > threshold.
    The meta-model learns to filter false positives of the primary strategy.

    Args:
        primary_signals:    Series of {-1, +1} (0 events are treated as 'no bet' -> 0).
        returns:            realized forward returns aligned to primary_signals.
        threshold:          minimum |return| to count as 'correct' (filters noise).
        nan_warn_threshold: if more than this fraction of events have non-finite
                            returns, emit a UserWarning. Default 5%.

    Returns:
        Series of {0, 1}, same index as primary_signals.
    """
    if not isinstance(primary_signals, pd.Series):
        raise TypeError("primary_signals must be a pd.Series")
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be a pd.Series")
    if threshold < 0:
        raise ValueError("threshold must be >= 0")
    if not (0.0 <= nan_warn_threshold <= 1.0):
        raise ValueError("nan_warn_threshold must be in [0, 1]")

    rets = returns.reindex(primary_signals.index)
    sig = primary_signals.fillna(0).astype(int)
    out = pd.Series(0, index=primary_signals.index, dtype=np.int8, name="meta")

    n_events = len(primary_signals)
    n_nan_ret = int((~np.isfinite(rets.to_numpy(dtype=float))).sum())
    if n_events > 0 and (n_nan_ret / n_events) > nan_warn_threshold:
        warnings.warn(
            f"meta_labels: {n_nan_ret}/{n_events} events "
            f"({n_nan_ret/n_events:.1%}) have non-finite returns and will be "
            f"silently classified 0. Exceeds nan_warn_threshold="
            f"{nan_warn_threshold:.1%}.",
            UserWarning,
            stacklevel=2,
        )

    correct = (np.sign(sig) == np.sign(rets)) & (rets.abs() > threshold) & (sig != 0)
    out.loc[correct.fillna(False)] = 1
    return out


# ---------------------------------------------------------------------------
# Bet sizing from probabilities
# ---------------------------------------------------------------------------

def bet_size_from_proba(
    probabilities: pd.Series,
    threshold: float = 0.5,
    num_classes: int = 2,
    method: str = "sigmoid",
    power: float = 1.0,
) -> pd.Series:
    """Convert classifier probabilities into position sizes in [-1, 1].

    Sign convention: proba > threshold -> long (positive size),
                     proba < threshold -> short (negative size).

    Methods:
      - 'sigmoid' (Lopez de Prado, AFML eq. 10.4):
            z = (p - threshold) / sqrt(p * (1 - p))
            size = 2 * Phi(z) - 1                           where Phi is the std normal cdf.
            For binary (num_classes=2) this maps to [-1, 1].
      - 'linear':
            size = 2 * (p - 0.5)                            (ignores threshold; binary only).
      - 'power':
            size = sign(p - threshold) * |p - threshold|^power * scale
            scale = 1 / max(threshold, 1 - threshold)^power so that p in {0,1} => |size|=1.

    Args:
        probabilities: Series of probabilities (0..1) of the positive class.
        threshold:     cutoff probability (default 0.5).
        num_classes:   used only for the sigmoid variance correction.
        method:        'sigmoid' | 'linear' | 'power'.
        power:         exponent for the 'power' method.

    Returns:
        Series of bet sizes in [-1, 1], same index as `probabilities`.
    """
    if not isinstance(probabilities, pd.Series):
        raise TypeError("probabilities must be a pd.Series")
    if not (0.0 < threshold < 1.0):
        raise ValueError("threshold must be in (0, 1)")
    if num_classes < 2:
        raise ValueError("num_classes must be >= 2")
    if method not in {"sigmoid", "linear", "power"}:
        raise ValueError(f"unknown method: {method}")

    p = probabilities.astype(float).clip(lower=1e-9, upper=1.0 - 1e-9)

    if method == "sigmoid":
        # AFML eq. 10.4 generalized
        denom = np.sqrt(p * (1.0 - p))
        z = (p - threshold) / denom
        # 2 * Phi(z) - 1 maps R -> [-1, 1] with sign matching z
        sizes = 2.0 * pd.Series(norm.cdf(z.values), index=p.index) - 1.0
    elif method == "linear":
        sizes = 2.0 * (p - 0.5)
    else:  # power
        delta = p - threshold
        scale = max(threshold, 1.0 - threshold) ** power
        sizes = np.sign(delta) * (delta.abs() ** power) / scale

    sizes = sizes.clip(lower=-1.0, upper=1.0)
    sizes.name = "bet_size"
    return sizes
