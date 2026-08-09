"""Causal feature execution kernels for the SP500 F001-F240 catalog."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


class FeatureEngineError(ValueError):
    """Raised when a feature would use unavailable or non-train data."""


_TRAIN_END = pd.Timestamp("2010-12-31")


def _validated_spy(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume", "available_at"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise FeatureEngineError(f"MISSING_SPY_COLUMNS:{','.join(missing)}")
    spy = frame.loc[:, sorted(required)].copy()
    spy["date"] = pd.to_datetime(spy["date"], errors="coerce").dt.normalize()
    spy["available_at"] = pd.to_datetime(
        spy["available_at"], errors="coerce"
    ).dt.normalize()
    if spy[["date", "available_at"]].isna().any().any():
        raise FeatureEngineError("INVALID_SPY_TIMESTAMPS")
    if spy["date"].gt(_TRAIN_END).any() or spy["available_at"].gt(_TRAIN_END).any():
        raise FeatureEngineError("NON_TRAIN_PRICE_ROW")
    if spy["available_at"].lt(spy["date"]).any():
        raise FeatureEngineError("SPY_AVAILABLE_AT_PRECEDES_OBSERVATION")
    if spy["date"].duplicated().any() or not spy["date"].is_monotonic_increasing:
        raise FeatureEngineError("SPY_DATES_NOT_STRICTLY_ORDERED")
    if (
        spy["available_at"].duplicated().any()
        or not spy["available_at"].is_monotonic_increasing
    ):
        raise FeatureEngineError("SPY_AVAILABILITY_NOT_STRICTLY_ORDERED")
    for column in ("open", "high", "low", "close", "volume"):
        spy[column] = pd.to_numeric(spy[column], errors="coerce")
    if spy[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise FeatureEngineError("NON_NUMERIC_SPY_VALUE")
    return spy.reset_index(drop=True)


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    deviation = values.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    return (values - mean) / deviation


def _moving_average(values: pd.Series, kind: str, window: int) -> pd.Series:
    if kind == "sma":
        return values.rolling(window, min_periods=window).mean()
    if kind == "ema":
        return values.ewm(span=window, adjust=False, min_periods=window).mean()
    if kind == "wma":
        weights = np.arange(1.0, window + 1.0)
        denominator = float(weights.sum())
        return values.rolling(window, min_periods=window).apply(
            lambda row: float(np.dot(row, weights) / denominator),
            raw=True,
        )
    raise FeatureEngineError(f"UNKNOWN_MOVING_AVERAGE:{kind}")


def _true_range(spy: pd.DataFrame) -> pd.Series:
    prior_close = spy["close"].shift(1)
    return pd.concat(
        [
            spy["high"] - spy["low"],
            (spy["high"] - prior_close).abs(),
            (spy["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _output(spy: pd.DataFrame, value: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": spy["available_at"],
            "observed_at": spy["date"],
            "available_at": spy["available_at"],
            "value": pd.to_numeric(value, errors="coerce"),
        }
    )


def _rolling_slope(values: pd.Series, window: int) -> pd.Series:
    x = np.arange(float(window))
    x_centered = x - x.mean()
    denominator = float(np.dot(x_centered, x_centered))
    return values.rolling(window, min_periods=window).apply(
        lambda row: float(np.dot(row - row.mean(), x_centered) / denominator),
        raw=True,
    )


def _signed_streak(returns: pd.Series) -> pd.Series:
    signs = np.sign(returns.fillna(0.0)).astype(int)
    groups = signs.ne(signs.shift()).cumsum()
    lengths = signs.groupby(groups).cumcount() + 1
    return lengths.astype(float) * signs


def evaluate_price_lane(
    lane_id: str,
    spy_frame: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one exact price-only family using observations available by close t."""

    spy = _validated_spy(spy_frame)
    close = spy["close"]
    returns = close.pct_change(fill_method=None)
    lane_number = int(lane_id[1:]) if lane_id.startswith("F") else -1
    if not 1 <= lane_number <= 20:
        raise FeatureEngineError(f"PRICE_LANE_NOT_IMPLEMENTED:{lane_id}")

    if lane_id == "F001":
        window = int(parameters["window"])
        average = _moving_average(close, str(parameters["kind"]), window)
        normalization = str(parameters.get("normalization", "price_ratio"))
        if normalization == "price_ratio":
            value = close / average - 1.0
        elif normalization == "atr":
            value = (close - average) / _true_range(spy).rolling(window).mean().replace(0.0, np.nan)
        elif normalization == "rolling_z":
            value = _rolling_z(close - average, window)
        else:
            raise FeatureEngineError(f"F001_UNKNOWN_NORMALIZATION:{normalization}")
    elif lane_id == "F002":
        kind = str(parameters.get("kind", "ema"))
        fast = int(parameters.get("fast", 20))
        slow = int(parameters.get("slow", 126))
        if fast >= slow:
            raise FeatureEngineError("F002_FAST_NOT_BELOW_SLOW")
        value = _moving_average(close, kind, fast) / _moving_average(close, kind, slow) - 1.0
    elif lane_id == "F003":
        window = int(parameters["window"])
        skip = int(parameters.get("skip", 0))
        endpoint = close.shift(skip)
        if str(parameters.get("return_kind", "simple")) == "log":
            value = np.log(endpoint) - np.log(endpoint.shift(window))
        else:
            value = endpoint / endpoint.shift(window) - 1.0
    elif lane_id == "F004":
        horizons = tuple(parameters.get("horizons", (5, 20, 63, 126)))
        components = [close / close.shift(int(window)) - 1.0 for window in horizons]
        value = pd.concat(components, axis=1).mean(axis=1, skipna=False)
    elif lane_id == "F005":
        window = int(parameters.get("window", 63))
        value = _rolling_slope(np.log(close), window)
    elif lane_id == "F006":
        window = int(parameters.get("window", 20))
        prior_high = spy["high"].shift(1).rolling(window, min_periods=window).max()
        prior_low = spy["low"].shift(1).rolling(window, min_periods=window).min()
        midpoint = (prior_high + prior_low) / 2.0
        value = (close - midpoint) / (prior_high - prior_low).replace(0.0, np.nan)
    elif lane_id == "F007":
        window = int(parameters.get("window", 20))
        center = close.rolling(window, min_periods=window).mean()
        width = close.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
        value = (close - center) / width
    elif lane_id == "F008":
        window = int(parameters.get("window", 63))
        lag = int(parameters.get("lag", 1))
        value = returns.rolling(window, min_periods=window).corr(returns.shift(lag))
    elif lane_id == "F009":
        window = int(parameters.get("window", 2))
        value = -(close / close.shift(window) - 1.0)
    elif lane_id == "F010":
        window = int(parameters.get("window", 14))
        change = close.diff()
        gain = change.clip(lower=0.0).rolling(window, min_periods=window).mean()
        loss = (-change.clip(upper=0.0)).rolling(window, min_periods=window).mean()
        rs = gain / loss.replace(0.0, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        rsi = rsi.mask((loss == 0.0) & (gain > 0.0), 100.0)
        rsi = rsi.mask((loss == 0.0) & (gain == 0.0), 50.0)
        value = rsi - 50.0
    elif lane_id == "F011":
        window = int(parameters.get("window", 63))
        value = _rolling_z(close, window)
    elif lane_id == "F012":
        value = _signed_streak(returns)
    elif lane_id == "F013":
        overnight = spy["open"] / close.shift(1) - 1.0
        intraday = close / spy["open"] - 1.0
        value = overnight - intraday
    elif lane_id == "F014":
        bar_range = (spy["high"] - spy["low"]).replace(0.0, np.nan)
        value = (2.0 * close - spy["high"] - spy["low"]) / bar_range
    elif lane_id == "F015":
        window = int(parameters.get("window", 20))
        realized = returns.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(252.0)
        value = realized.pct_change(fill_method=None)
    elif lane_id == "F016":
        window = int(parameters.get("window", 63))
        value = returns.rolling(window, min_periods=window).skew()
    elif lane_id == "F017":
        window = int(parameters.get("window", 126))
        half = max(20, window // 2)
        long_vol = returns.rolling(window, min_periods=window).std(ddof=0)
        short_vol = returns.rolling(half, min_periods=half).std(ddof=0)
        value = 0.5 + np.log(long_vol / short_vol.replace(0.0, np.nan)) / np.log(2.0)
    elif lane_id == "F018":
        window = int(parameters.get("window", 20))
        atr = _true_range(spy).rolling(window, min_periods=window).mean() / close
        value = atr.pct_change(fill_method=None)
    elif lane_id == "F019":
        direction = np.sign(close.diff()).fillna(0.0)
        obv = (direction * spy["volume"]).cumsum()
        window = int(parameters.get("window", 20))
        value = obv.diff(window) / spy["volume"].rolling(window, min_periods=window).sum()
    else:  # F020
        window = int(parameters.get("window", 20))
        dollar_volume = (close * spy["volume"]).replace(0.0, np.nan)
        amihud = returns.abs() / dollar_volume
        value = -_rolling_z(amihud, window)
    return _output(spy, value)


_PRICE_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F001": {"kind": "sma", "window": 63, "normalization": "price_ratio", "threshold": 0.0},
    "F002": {"kind": "ema", "fast": 20, "slow": 126, "confirmation": 1},
    "F003": {"window": 63, "skip": 0, "return_kind": "simple", "threshold": 0.0},
    "F004": {"horizons": (5, 20, 63, 126)},
    "F005": {"window": 63},
    "F006": {"window": 20},
    "F007": {"window": 20},
    "F008": {"window": 63, "lag": 1},
    "F009": {"window": 2},
    "F010": {"window": 14},
    "F011": {"window": 63},
    "F012": {"length": 3},
    "F013": {"window": 1},
    "F014": {"window": 1},
    "F015": {"window": 20},
    "F016": {"window": 63},
    "F017": {"window": 126},
    "F018": {"window": 20},
    "F019": {"window": 20},
    "F020": {"window": 20},
}


def evaluate_price_family_batch(spy_frame: pd.DataFrame) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for each F001-F020 family."""

    spy = _validated_spy(spy_frame)
    return {
        lane_id: evaluate_price_lane(lane_id, spy, parameters)
        for lane_id, parameters in _PRICE_BATCH_PARAMETERS.items()
    }
