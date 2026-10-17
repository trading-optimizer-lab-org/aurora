"""Quality checks for daily stock price series (Yahoo style columns).

Each series is a DataFrame indexed by date with ``open``, ``high``, ``low``,
``close`` (split adjusted), ``adj_close`` (split and dividend adjusted),
``volume`` and ``stock_splits``. ``check_series`` returns issue counts;
``is_severe`` turns them into the exclusion rule used by the stock catalog.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SPIKE = 0.5          # one-day adjusted move treated as a spike
REVERSAL = 0.33      # a spike followed by this opposite move is a bad tick
OHLC_TOL = 0.005     # tolerance on high/low containment
DIV_JUMP = 0.25      # one-day change in adj/close factor (implied dividend)
STALE_DAYS = 10


def check_series(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, int | float]:
    out: dict[str, int | float] = {"rows": int(len(df))}
    idx = df.index
    out["duplicate_dates"] = int(idx.duplicated().sum())
    out["unsorted"] = int(not idx.is_monotonic_increasing)
    df = df[~idx.duplicated()].sort_index()
    price_cols = ["open", "high", "low", "close", "adj_close"]
    out["missing_prices"] = int(df[price_cols].isna().any(axis=1).sum())
    out["non_positive_prices"] = int((df[price_cols] <= 0).any(axis=1).sum())
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    top = pd.concat([o, c, l], axis=1).max(axis=1)
    bottom = pd.concat([o, c, h], axis=1).min(axis=1)
    out["ohlc_inconsistent"] = int(((h < top * (1 - OHLC_TOL)) | (l > bottom * (1 + OHLC_TOL))).sum())
    out["negative_volume"] = int((df["volume"] < 0).sum())
    out["zero_volume_days"] = int((df["volume"] == 0).sum())

    r = df["adj_close"].pct_change(fill_method=None)
    spikes = r.abs() > SPIKE
    out["spike_days"] = int(spikes.sum())
    out["reversing_spikes"] = int((spikes & (np.sign(r.shift(-1)) == -np.sign(r))
                                   & (r.shift(-1).abs() > REVERSAL)).sum())
    split_day = df["stock_splits"].fillna(0) > 0
    out["split_days"] = int(split_day.sum())
    out["split_day_spikes"] = int((split_day & spikes).sum())

    factor = (df["adj_close"] / df["close"]).replace([np.inf, -np.inf], np.nan)
    out["adj_factor_jumps"] = int((factor.pct_change(fill_method=None).abs() > DIV_JUMP).sum())
    out["adj_factor_above_1"] = int((factor > 1.0001).sum())

    same = (c.diff() == 0) & (df["volume"] == 0)
    run = same.groupby((~same).cumsum()).cumsum()
    out["stale_runs"] = int(((run == STALE_DAYS)).sum())

    span = calendar[(calendar >= df.index.min()) & (calendar <= df.index.max())]
    out["off_calendar_dates"] = int((~df.index.isin(calendar)).sum())
    out["missing_calendar_days"] = int((~span.isin(df.index)).sum())
    out["missing_share"] = float(out["missing_calendar_days"] / max(len(span), 1))
    return out


def is_severe(issues: dict) -> list[str]:
    """Reasons a series is excluded from the catalog (empty = keep)."""
    reasons = []
    rows = max(int(issues["rows"]), 1)
    if issues["non_positive_prices"] > 0:
        reasons.append("non-positive prices")
    if issues["ohlc_inconsistent"] / rows > 0.01:
        reasons.append("OHLC inconsistent on >1% of days")
    if issues["reversing_spikes"] >= 2:
        reasons.append(">=2 reversing one-day spikes (bad ticks)")
    if issues["split_day_spikes"] > 0:
        reasons.append("price jump on a split day (mis-adjusted split)")
    if issues["adj_factor_above_1"] > 0:
        reasons.append("adjusted close above close")
    if issues["missing_share"] > 0.05:
        reasons.append(">5% of trading days missing")
    return reasons
