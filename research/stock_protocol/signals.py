"""Causal price features and real cross-sectional stock selection."""

from __future__ import annotations

import math
from typing import Mapping

import numpy as np
import pandas as pd

from .dataset import ResearchPanel


def compute_true_range(frame: pd.DataFrame) -> pd.Series:
    """Return Wilder True Range from consistently scaled OHLC columns."""

    required = {"high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"true range requires columns: {sorted(missing)}")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous_close = close.shift(1)
    components = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return components.max(axis=1, skipna=True)


def _adjust_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    """Scale OHLC to the adjusted-close basis so splits cannot create signals."""

    result = frame.copy()
    close = pd.to_numeric(result["close"], errors="coerce")
    adjusted_close = pd.to_numeric(result["adj_close"], errors="coerce")
    factor = adjusted_close.div(close.where(close > 0))
    factor = factor.where(np.isfinite(factor) & factor.gt(0))
    for column in ("open", "high", "low", "close"):
        result[f"adj_{column}"] = pd.to_numeric(
            result[column], errors="coerce"
        ).mul(factor)
    result["adj_close"] = adjusted_close
    return result


def compute_features(panel: ResearchPanel) -> pd.DataFrame:
    """Build price features using only information known by each row's close."""

    frame = panel.frame.sort_values(["symbol", "date"]).copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    if frame.empty:
        raise ValueError("feature panel is empty")
    if frame["date"].max() >= pd.Timestamp("2021-01-01"):
        raise ValueError("feature panel crosses locked boundary 2021-01-01")
    if panel.audit.locked_opened or panel.audit.locked_rows:
        raise ValueError("feature panel audit reports locked data access")
    frame = _adjust_ohlc(frame)
    grouped = frame.groupby("symbol", group_keys=False, sort=False)

    frame["ret_1d"] = grouped["adj_close"].pct_change(fill_method=None)
    frame["mom_12_1"] = grouped["adj_close"].transform(
        lambda values: values.shift(21).div(values.shift(252)).sub(1.0)
    )
    frame["mom_6_1"] = grouped["adj_close"].transform(
        lambda values: values.shift(21).div(values.shift(126)).sub(1.0)
    )
    frame["vol_12_1"] = grouped["ret_1d"].transform(
        lambda values: values.shift(21).rolling(231, min_periods=126).std()
        * np.sqrt(252.0)
    )

    adjusted_high_group = frame.groupby("symbol", sort=False)["adj_high"]
    for window in (20, 50, 100, 150, 200, 252):
        prior_high = adjusted_high_group.transform(
            lambda values, w=window: values.shift(1).rolling(
                w, min_periods=max(10, w // 2)
            ).max()
        )
        frame[f"breakout_{window}"] = frame["adj_close"].gt(prior_high)
        frame[f"breakout_level_{window}"] = prior_high

    for window in (20, 40, 60):
        prior_range_high = grouped["adj_high"].transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=w).max()
        )
        prior_range_low = grouped["adj_low"].transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=w).min()
        )
        prior_close = grouped["adj_close"].shift(1)
        frame[f"consolidation_{window}"] = prior_range_high.sub(
            prior_range_low
        ).div(prior_close.replace(0, np.nan))

    high_52 = adjusted_high_group.transform(
        lambda values: values.shift(1).rolling(252, min_periods=126).max()
    )
    frame["h52"] = frame["adj_close"].div(high_52)

    for window in (50, 150, 200, 250):
        frame[f"sma_{window}"] = grouped["adj_close"].transform(
            lambda values, w=window: values.shift(1).rolling(
                w, min_periods=max(20, w // 2)
            ).mean()
        )

    volume_history = grouped["volume"].transform(
        lambda values: values.shift(1).rolling(50, min_periods=25).mean()
    )
    frame["rvol50"] = pd.to_numeric(frame["volume"], errors="coerce").div(
        volume_history.replace(0.0, np.nan)
    )

    true_range = pd.Series(index=frame.index, dtype=float)
    for _, positions in frame.groupby("symbol", sort=False).groups.items():
        index = list(positions)
        scaled = frame.loc[index, ["adj_high", "adj_low", "adj_close"]].rename(
            columns={"adj_high": "high", "adj_low": "low", "adj_close": "close"}
        )
        true_range.loc[index] = compute_true_range(scaled).to_numpy()
    frame["true_range"] = true_range
    frame["atr20"] = frame.groupby("symbol", sort=False)["true_range"].transform(
        lambda values: values.rolling(20, min_periods=10).mean()
    )

    formation_negative = grouped["ret_1d"].transform(
        lambda values: values.lt(0).shift(21).rolling(231, min_periods=126).sum()
    )
    formation_positive = grouped["ret_1d"].transform(
        lambda values: values.gt(0).shift(21).rolling(231, min_periods=126).sum()
    )
    denominator = formation_negative.add(formation_positive).replace(0, np.nan)
    frame["information_discreteness"] = np.sign(frame["mom_12_1"]).mul(
        formation_negative.sub(formation_positive).div(denominator)
    )

    by_date = frame.groupby("date", group_keys=False, sort=False)
    frame["price_score"] = (
        by_date["mom_12_1"].rank(pct=True) * 0.5
        + by_date["h52"].rank(pct=True) * 0.3
        - by_date["information_discreteness"].rank(pct=True) * 0.2
    )
    return frame


def rebalance_mask(frame: pd.DataFrame, frequency: str = "monthly") -> pd.Series:
    """Mark explicit last-observation rebalance rows for each calendar period."""

    if "date" not in frame:
        raise ValueError("rebalance frame requires a date column")
    dates = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    normalized = str(frequency).strip().lower()
    if normalized in {"daily", "day"}:
        return pd.Series(True, index=frame.index, dtype=bool)
    period_codes = {
        "weekly": "W-FRI",
        "week": "W-FRI",
        "monthly": "M",
        "month": "M",
        "quarterly": "Q",
        "quarter": "Q",
        "annual": "Y",
        "yearly": "Y",
        "year": "Y",
    }
    if normalized not in period_codes:
        raise ValueError(f"unsupported rebalance frequency: {frequency}")
    periods = dates.dt.to_period(period_codes[normalized])
    last_dates = dates.groupby(periods).transform("max")
    return dates.eq(last_dates)


def _selection_count(size: int, selection: Mapping[str, object]) -> tuple[int, int]:
    kind = str(selection.get("kind", "top_percent")).strip().lower()
    value = selection.get("value", 0.10)
    if kind == "top_n":
        return min(size, max(0, int(value))), 1
    if kind == "top_percent":
        fraction = float(value)
        if fraction > 1.0:
            fraction /= 100.0
        if not 0.0 < fraction <= 1.0:
            raise ValueError("top_percent value must be in (0, 1] or (0, 100]")
        return min(size, max(1, int(math.ceil(size * fraction)))), 1
    if kind in {"quintile", "decile"}:
        buckets = 5 if kind == "quintile" else 10
        bucket = int(value)
        if not 1 <= bucket <= buckets:
            raise ValueError(f"{kind} value must be between 1 and {buckets}")
        return buckets, bucket
    raise ValueError(f"unsupported selection kind: {kind}")


def select_cross_section(
    candidates: pd.DataFrame,
    selection: Mapping[str, object],
) -> pd.DataFrame:
    """Select stocks independently on each signal date.

    Ranked selections are descending by score with symbol as deterministic
    tie-breaker.  Binary selections accept only the literal active value 1.
    """

    required = {"signal_date", "symbol", "score"}
    missing = required - set(candidates.columns)
    if missing:
        raise ValueError(f"cross-sectional selection missing: {sorted(missing)}")
    if candidates.empty:
        return candidates.copy()
    frame = candidates.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="raise").dt.normalize()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    kind = str(selection.get("kind", "top_percent")).strip().lower()
    if kind == "binary":
        selected = frame.loc[frame["score"].eq(1.0)].copy()
        selected["cross_section_rank"] = 1
        selected["cross_section_percentile"] = 1.0
        selected["selection_rule"] = "binary"
        return selected.sort_values(["signal_date", "symbol"]).reset_index(drop=True)

    frame = frame.loc[np.isfinite(frame["score"])].copy()
    ascending = bool(selection.get("ascending", False))
    selected_groups: list[pd.DataFrame] = []
    for _, group in frame.groupby("signal_date", sort=True):
        ordered = group.sort_values(
            ["score", "symbol"],
            ascending=[ascending, True],
            kind="mergesort",
        ).copy()
        ordered["cross_section_rank"] = np.arange(1, len(ordered) + 1)
        ordered["cross_section_percentile"] = 1.0 - (
            ordered["cross_section_rank"] - 1
        ) / max(len(ordered), 1)
        count_or_buckets, bucket = _selection_count(len(ordered), selection)
        if kind in {"quintile", "decile"}:
            buckets = count_or_buckets
            bucket_ids = np.floor(
                (ordered["cross_section_rank"] - 1) * buckets / len(ordered)
            ).astype(int) + 1
            chosen = ordered.loc[bucket_ids.eq(bucket)].copy()
        else:
            chosen = ordered.head(count_or_buckets).copy()
        chosen["selection_rule"] = kind
        selected_groups.append(chosen)
    if not selected_groups:
        return frame.iloc[0:0].copy()
    return pd.concat(selected_groups, ignore_index=True).sort_values(
        ["signal_date", "cross_section_rank", "symbol"]
    ).reset_index(drop=True)


def _selection_for_test(test_id: int, variant: Mapping[str, object]) -> dict[str, object]:
    explicit = variant.get("selection")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    portfolio = str(variant.get("portfolio", ""))
    if portfolio.startswith("top_"):
        return {"kind": "top_percent", "value": float(portfolio.split("_", 1)[1])}
    if test_id in {16, 18, 20}:
        return {"kind": "binary"}
    return {"kind": "top_percent", "value": float(variant.get("top_percent", 10.0))}


def compute_signal(
    panel: ResearchPanel,
    test_id: int,
    variant: dict[str, object],
    *,
    features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute candidates, enforce rebalance dates and select real stocks."""

    frame = compute_features(panel) if features is None else features
    binary = False
    if test_id == 1:
        score = frame["mom_12_1"]
    elif test_id == 2:
        score = frame["mom_6_1"]
    elif test_id == 3:
        score = frame["mom_12_1"].div(frame["vol_12_1"].replace(0, np.nan))
    elif test_id == 8:
        score = frame["h52"]
    elif test_id == 9:
        score = -frame["information_discreteness"]
    elif test_id == 13:
        score = frame["price_score"]
    elif test_id == 16:
        window = int(variant.get("window", 20))
        if window not in {20, 50, 100, 150, 200, 252}:
            raise ValueError(f"unsupported breakout window: {window}")
        score = frame[f"breakout_{window}"].astype(float)
        binary = True
    elif test_id == 17:
        window = int(variant.get("window", 20))
        high = frame.groupby("symbol", sort=False)["adj_high"].transform(
            lambda values: values.shift(1).rolling(
                window, min_periods=max(10, window // 2)
            ).max()
        )
        low = frame.groupby("symbol", sort=False)["adj_low"].transform(
            lambda values: values.shift(1).rolling(
                window, min_periods=max(10, window // 2)
            ).min()
        )
        score = -high.sub(low).div(frame["adj_close"].replace(0, np.nan))
    elif test_id == 18:
        window = int(variant.get("window", 252))
        threshold = float(variant.get("threshold", 1.5))
        if window not in {20, 50, 100, 150, 200, 252}:
            raise ValueError(f"unsupported breakout window: {window}")
        score = (
            frame[f"breakout_{window}"] & frame["rvol50"].ge(threshold)
        ).astype(float)
        binary = True
    elif test_id == 20:
        window = int(variant.get("sma", 200))
        if window not in {150, 200, 250}:
            raise ValueError(f"unsupported SMA window: {window}")
        score = frame["adj_close"].gt(frame[f"sma_{window}"]).astype(float)
        binary = True
    else:
        raise NotImplementedError(f"stock protocol signal test {test_id} is not implemented")

    candidates = frame.copy()
    candidates["score"] = pd.to_numeric(score, errors="coerce")
    candidates["signal_date"] = candidates["date"]
    candidates["available_at"] = candidates["date"]
    frequency = str(variant.get("rebalance", "daily" if binary else "monthly"))
    candidates = candidates.loc[rebalance_mask(candidates, frequency)].copy()
    selected = select_cross_section(candidates, _selection_for_test(test_id, variant))
    selected["signal"] = True
    columns = [
        "signal_date",
        "available_at",
        "symbol",
        "score",
        "cross_section_rank",
        "cross_section_percentile",
        "selection_rule",
        "adj_close",
        "adj_high",
        "adj_low",
        "atr20",
        "vol_12_1",
    ]
    return selected.loc[:, [column for column in columns if column in selected]].reset_index(drop=True)


# Backwards-compatible private name used by no external contract.
_features = compute_features
