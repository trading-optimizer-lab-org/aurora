"""Audited corporate-action-aware SPY open-to-open return ledger."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.infra.sp500_long_short_daily.contracts import (
    LockedBoundaryError,
    assert_frame_before_locked,
)


REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class LedgerAudit:
    row_count: int
    distribution_count: int
    split_count: int
    first_date: str
    last_date: str
    long_short_max_abs_error: float


def _normalize_events(
    events: pd.DataFrame | None,
    value_column: str,
) -> pd.Series:
    if events is None or events.empty:
        return pd.Series(dtype=float)
    frame = events.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame[value_column] = pd.to_numeric(frame[value_column], errors="raise")
    return frame.groupby("date", sort=True)[value_column].sum()


def build_total_return_ledger(
    prices: pd.DataFrame,
    distributions: pd.DataFrame | None = None,
    splits: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, LedgerAudit]:
    """Build one return ledger shared by candidates and benchmarks.

    A distribution with ex-date ``t+1`` belongs to the open(t)-to-open(t+1)
    interval. Raw prices are transformed for splits before distributions are
    added. The short series is exactly the arithmetic negative of long.
    """

    frame = prices.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame = frame.set_index("date")
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    frame = frame.sort_index(kind="mergesort")
    assert_frame_before_locked(frame, label="spy_price_ledger")
    if frame.index.has_duplicates:
        raise ValueError("DUPLICATE_SPY_SESSION")
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"MISSING_SPY_COLUMNS:{missing}")
    for column in REQUIRED_PRICE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("NON_POSITIVE_SPY_PRICE")
    if (frame["volume"] < 0).any():
        raise ValueError("NEGATIVE_SPY_VOLUME")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("INVALID_SPY_HIGH")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("INVALID_SPY_LOW")

    distribution_series = _normalize_events(distributions, "distribution")
    split_series = _normalize_events(splits, "split_ratio")
    if len(distribution_series):
        if distribution_series.index.max() >= pd.Timestamp("2021-01-01"):
            raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:distribution")
        if not distribution_series.index.isin(frame.index).all():
            raise ValueError("DISTRIBUTION_ON_NON_SESSION")
    if len(split_series):
        if split_series.index.max() >= pd.Timestamp("2021-01-01"):
            raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:split")
        if (split_series <= 0).any():
            raise ValueError("INVALID_SPLIT_RATIO")
        if not split_series.index.isin(frame.index).all():
            raise ValueError("SPLIT_ON_NON_SESSION")

    frame["distribution"] = distribution_series.reindex(frame.index, fill_value=0.0)
    frame["split_ratio"] = split_series.reindex(frame.index, fill_value=1.0)
    cumulative_future_split = (
        frame["split_ratio"].iloc[::-1].cumprod().iloc[::-1]
        / frame["split_ratio"]
    )
    for column in ("open", "high", "low", "close"):
        frame[f"split_adjusted_{column}"] = frame[column] / cumulative_future_split
    frame["split_adjusted_distribution"] = (
        frame["distribution"] / cumulative_future_split
    )

    next_open = frame["split_adjusted_open"].shift(-1)
    next_distribution = frame["split_adjusted_distribution"].shift(-1).fillna(0.0)
    long_return = (
        next_open + next_distribution - frame["split_adjusted_open"]
    ) / frame["split_adjusted_open"]
    frame["long_return"] = long_return
    frame["short_return"] = -frame["long_return"]
    # The return stored on row t belongs to open(t)->open(t+1), so the
    # total-return level at open(t) contains only intervals ending before t.
    frame["tr_open"] = (
        (1.0 + frame["long_return"].fillna(0.0)).cumprod().shift(1).fillna(1.0)
    )
    close_factor = frame["split_adjusted_close"] / frame["split_adjusted_open"]
    frame["tr_close"] = frame["tr_open"] * close_factor
    finite = frame[["long_return", "short_return"]].dropna()
    error = float((finite["long_return"] + finite["short_return"]).abs().max())
    if error > 1e-15:
        raise ValueError("LONG_SHORT_RECONCILIATION_FAILED")
    audit = LedgerAudit(
        row_count=len(frame),
        distribution_count=int((frame["distribution"] != 0).sum()),
        split_count=int((frame["split_ratio"] != 1).sum()),
        first_date=frame.index.min().date().isoformat(),
        last_date=frame.index.max().date().isoformat(),
        long_short_max_abs_error=error,
    )
    return frame, audit


def apply_positions(ledger: pd.DataFrame, decisions: pd.Series) -> pd.DataFrame:
    """Apply close-t decisions at next open while preserving prior state."""

    aligned = decisions.reindex(ledger.index)
    positions = aligned.shift(1).ffill().fillna(1).astype(np.int8)
    if not positions.isin((-1, 1)).all():
        raise ValueError("INVALID_POSITION_STATE")
    result = pd.DataFrame(index=ledger.index)
    result["decision"] = aligned
    result["position"] = positions
    result["long_return"] = ledger["long_return"]
    result["strategy_return"] = positions.astype(float) * ledger["long_return"]
    return result
