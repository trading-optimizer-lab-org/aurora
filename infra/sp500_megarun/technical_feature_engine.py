"""Causal technical-analysis kernels for executable SP500 lanes F121-F130."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


class TechnicalFeatureEngineError(ValueError):
    """Raised when a technical input or parameter violates the train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")


def _validated_spy(frame: pd.DataFrame) -> pd.DataFrame:
    required = (
        "date",
        "observed_at",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise TechnicalFeatureEngineError(
            f"MISSING_SPY_COLUMNS:{','.join(missing)}"
        )
    spy = frame.loc[:, required].copy()
    for column in ("date", "observed_at", "available_at"):
        spy[column] = pd.to_datetime(spy[column], errors="coerce").dt.normalize()
    if spy[["date", "observed_at", "available_at"]].isna().any().any():
        raise TechnicalFeatureEngineError("INVALID_SPY_TIMESTAMPS")
    if spy["date"].gt(_TRAIN_END).any() or spy["available_at"].gt(_TRAIN_END).any():
        raise TechnicalFeatureEngineError("NON_TRAIN_PRICE_ROW")
    if spy["observed_at"].gt(spy["available_at"]).any():
        raise TechnicalFeatureEngineError("SPY_OBSERVED_AFTER_AVAILABILITY")
    if spy["available_at"].gt(spy["date"]).any():
        raise TechnicalFeatureEngineError("SPY_AVAILABLE_AFTER_DECISION_DATE")
    if spy["date"].duplicated().any() or not spy["date"].is_monotonic_increasing:
        raise TechnicalFeatureEngineError("SPY_DATES_NOT_STRICTLY_ORDERED")
    for column in ("open", "high", "low", "close", "volume"):
        spy[column] = pd.to_numeric(spy[column], errors="coerce")
    numeric = spy[["open", "high", "low", "close", "volume"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise TechnicalFeatureEngineError("NON_FINITE_SPY_VALUE")
    if spy[["open", "high", "low", "close"]].le(0.0).any().any():
        raise TechnicalFeatureEngineError("NON_POSITIVE_SPY_PRICE")
    if spy["volume"].lt(0.0).any():
        raise TechnicalFeatureEngineError("NEGATIVE_SPY_VOLUME")
    if (
        spy["high"].lt(spy[["open", "close", "low"]].max(axis=1)).any()
        or spy["low"].gt(spy[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise TechnicalFeatureEngineError("INCONSISTENT_SPY_OHLC")
    return spy.reset_index(drop=True)


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise TechnicalFeatureEngineError(f"INVALID_POSITIVE_PARAMETER:{name}:{value}")
    return value


def _non_negative_float(
    parameters: Mapping[str, Any], name: str, default: float
) -> float:
    value = float(parameters.get(name, default))
    if not np.isfinite(value) or value < 0.0:
        raise TechnicalFeatureEngineError(
            f"INVALID_NON_NEGATIVE_PARAMETER:{name}:{value}"
        )
    return value


def _pick(
    parameters: Mapping[str, Any],
    lane: str,
    choices: Mapping[str, pd.Series],
    default: str,
) -> pd.Series:
    statistic = str(parameters.get("statistic", default))
    if statistic not in choices:
        raise TechnicalFeatureEngineError(f"{lane}_UNKNOWN_STATISTIC:{statistic}")
    return choices[statistic]


def _output(spy: pd.DataFrame, value: pd.Series | np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": spy["date"],
            "observed_at": spy["observed_at"],
            "available_at": spy["available_at"],
            "value": pd.to_numeric(
                pd.Series(value, index=spy.index), errors="coerce"
            ).replace([np.inf, -np.inf], np.nan),
        }
    )


def _true_range(spy: pd.DataFrame) -> pd.Series:
    prior_close = spy["close"].shift(1)
    return pd.concat(
        (
            spy["high"] - spy["low"],
            (spy["high"] - prior_close).abs(),
            (spy["low"] - prior_close).abs(),
        ),
        axis=1,
    ).max(axis=1)


def _wilder(values: pd.Series, window: int) -> pd.Series:
    return values.ewm(
        alpha=1.0 / float(window), adjust=False, min_periods=window
    ).mean()


def _atr(spy: pd.DataFrame, window: int) -> pd.Series:
    return _wilder(_true_range(spy), window)


def _ema(values: pd.Series, span: int) -> pd.Series:
    return values.ewm(span=span, adjust=False, min_periods=span).mean()


def _rolling_slope(values: pd.Series, window: int) -> pd.Series:
    x = np.arange(float(window))
    centered = x - x.mean()
    denominator = float(np.dot(centered, centered))
    return values.rolling(window, min_periods=window).apply(
        lambda row: float(np.dot(row - row.mean(), centered) / denominator),
        raw=True,
    )


def _f121(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 252)
    confirmation = _positive_int(parameters, "confirmation", 2)
    buffer = _non_negative_float(parameters, "buffer_fraction", 0.0)
    prior_high = spy["high"].shift(1).rolling(window, min_periods=window).max()
    prior_low = spy["low"].shift(1).rolling(window, min_periods=window).min()
    width = (prior_high - prior_low).replace(0.0, np.nan)
    high_distance = spy["close"] / prior_high - 1.0
    low_distance = spy["close"] / prior_low - 1.0
    range_position = 2.0 * (spy["close"] - prior_low) / width - 1.0
    raw = pd.Series(
        np.select(
            (
                spy["close"].gt(prior_high * (1.0 + buffer)),
                spy["close"].lt(prior_low * (1.0 - buffer)),
            ),
            (1.0, -1.0),
            default=0.0,
        ),
        index=spy.index,
    ).where(prior_high.notna() & prior_low.notna())
    positive = raw.eq(1.0).rolling(confirmation, min_periods=confirmation).sum().eq(
        confirmation
    )
    negative = raw.eq(-1.0).rolling(confirmation, min_periods=confirmation).sum().eq(
        confirmation
    )
    confirmed = pd.Series(
        np.select((positive, negative), (1.0, -1.0), default=0.0),
        index=spy.index,
    ).where(raw.notna())
    return _pick(
        parameters,
        "F121",
        {
            "high_distance": high_distance,
            "low_distance": low_distance,
            "range_position": range_position,
            "confirmed_breakout": confirmed,
        },
        "range_position",
    )


def _f122(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 14)
    if window < 2:
        raise TechnicalFeatureEngineError("F122_WINDOW_BELOW_TWO")
    up_move = spy["high"].diff()
    down_move = -spy["low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0)
    atr = _atr(spy, window).replace(0.0, np.nan)
    plus_di = 100.0 * _wilder(plus_dm, window) / atr
    minus_di = 100.0 * _wilder(minus_dm, window) / atr
    denominator = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denominator
    adx = _wilder(dx, window)
    dmi_spread = plus_di - minus_di
    aroon_up = spy["high"].rolling(window, min_periods=window).apply(
        lambda row: 100.0 * float(np.argmax(row)) / float(window - 1), raw=True
    )
    aroon_down = spy["low"].rolling(window, min_periods=window).apply(
        lambda row: 100.0 * float(np.argmin(row)) / float(window - 1), raw=True
    )
    aroon = aroon_up - aroon_down
    directional = np.sign(dmi_spread) * adx / 100.0
    return _pick(
        parameters,
        "F122",
        {
            "adx": adx / 100.0,
            "dmi_spread": dmi_spread / 100.0,
            "aroon_oscillator": aroon / 100.0,
            "directional_strength": directional,
        },
        "directional_strength",
    )


def _f123(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    fast = _positive_int(parameters, "fast", 12)
    slow = _positive_int(parameters, "slow", 26)
    signal = _positive_int(parameters, "signal", 9)
    if fast >= slow:
        raise TechnicalFeatureEngineError("F123_FAST_NOT_BELOW_SLOW")
    close = spy["close"]
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    macd_line = fast_ema - slow_ema
    macd = macd_line - _ema(macd_line, signal)
    ppo_line = 100.0 * (fast_ema / slow_ema.replace(0.0, np.nan) - 1.0)
    ppo = ppo_line - _ema(ppo_line, signal)
    trix_level = _ema(_ema(_ema(close, fast), fast), fast)
    trix = 100.0 * np.log(trix_level).diff()
    momentum = close.diff()
    tsi_numerator = _ema(_ema(momentum, slow), fast)
    tsi_denominator = _ema(_ema(momentum.abs(), slow), fast).replace(0.0, np.nan)
    tsi = 100.0 * tsi_numerator / tsi_denominator
    return _pick(
        parameters,
        "F123",
        {"macd": macd, "ppo": ppo, "trix": trix, "tsi": tsi},
        "ppo",
    )


def _f124(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    conversion_window = _positive_int(parameters, "conversion_window", 9)
    base_window = _positive_int(parameters, "base_window", 26)
    span_b_window = _positive_int(parameters, "span_b_window", 52)
    atr_window = _positive_int(parameters, "atr_window", 14)
    if not conversion_window < base_window < span_b_window:
        raise TechnicalFeatureEngineError("F124_WINDOWS_NOT_ASCENDING")
    conversion = 0.5 * (
        spy["high"].rolling(conversion_window, min_periods=conversion_window).max()
        + spy["low"].rolling(conversion_window, min_periods=conversion_window).min()
    )
    base = 0.5 * (
        spy["high"].rolling(base_window, min_periods=base_window).max()
        + spy["low"].rolling(base_window, min_periods=base_window).min()
    )
    span_a = 0.5 * (conversion + base)
    span_b = 0.5 * (
        spy["high"].rolling(span_b_window, min_periods=span_b_window).max()
        + spy["low"].rolling(span_b_window, min_periods=span_b_window).min()
    )
    scale = _atr(spy, atr_window).replace(0.0, np.nan)
    upper = pd.concat((span_a, span_b), axis=1).max(axis=1)
    lower = pd.concat((span_a, span_b), axis=1).min(axis=1)
    conversion_base = (conversion - base) / scale
    cloud_position = (spy["close"] - 0.5 * (upper + lower)) / scale
    cloud_width = (span_a - span_b) / scale
    cloud_breakout = pd.Series(
        np.select(
            (spy["close"].gt(upper), spy["close"].lt(lower)),
            (1.0, -1.0),
            default=0.0,
        ),
        index=spy.index,
    ).where(span_a.notna() & span_b.notna())
    return _pick(
        parameters,
        "F124",
        {
            "conversion_base_spread": conversion_base,
            "cloud_position": cloud_position,
            "cloud_width": cloud_width,
            "cloud_breakout": cloud_breakout,
        },
        "cloud_position",
    )


def _parabolic_sar(
    high: pd.Series,
    low: pd.Series,
    *,
    acceleration_step: float,
    acceleration_max: float,
) -> pd.Series:
    high_values = high.to_numpy(dtype=float)
    low_values = low.to_numpy(dtype=float)
    result = np.full(len(high_values), np.nan)
    if not len(result):
        return pd.Series(result, index=high.index)
    bullish = True
    result[0] = low_values[0]
    extreme = high_values[0]
    acceleration = acceleration_step
    for index in range(1, len(result)):
        candidate = result[index - 1] + acceleration * (
            extreme - result[index - 1]
        )
        if bullish:
            candidate = min(candidate, low_values[index - 1])
            if index > 1:
                candidate = min(candidate, low_values[index - 2])
            if low_values[index] < candidate:
                bullish = False
                candidate = extreme
                extreme = low_values[index]
                acceleration = acceleration_step
            elif high_values[index] > extreme:
                extreme = high_values[index]
                acceleration = min(
                    acceleration + acceleration_step, acceleration_max
                )
        else:
            candidate = max(candidate, high_values[index - 1])
            if index > 1:
                candidate = max(candidate, high_values[index - 2])
            if high_values[index] > candidate:
                bullish = True
                candidate = extreme
                extreme = high_values[index]
                acceleration = acceleration_step
            elif low_values[index] < extreme:
                extreme = low_values[index]
                acceleration = min(
                    acceleration + acceleration_step, acceleration_max
                )
        result[index] = candidate
    return pd.Series(result, index=high.index)


def _supertrend(
    spy: pd.DataFrame, atr: pd.Series, multiplier: float
) -> pd.Series:
    midpoint = 0.5 * (spy["high"] + spy["low"])
    basic_upper = midpoint + multiplier * atr
    basic_lower = midpoint - multiplier * atr
    upper = np.full(len(spy), np.nan)
    lower = np.full(len(spy), np.nan)
    trend = np.full(len(spy), np.nan)
    close = spy["close"].to_numpy(dtype=float)
    raw_upper = basic_upper.to_numpy(dtype=float)
    raw_lower = basic_lower.to_numpy(dtype=float)
    for index in range(len(spy)):
        if not np.isfinite(raw_upper[index]) or not np.isfinite(raw_lower[index]):
            continue
        if index == 0 or not np.isfinite(upper[index - 1]):
            upper[index] = raw_upper[index]
            lower[index] = raw_lower[index]
            trend[index] = lower[index] if close[index] >= midpoint.iloc[index] else upper[index]
            continue
        upper[index] = (
            raw_upper[index]
            if raw_upper[index] < upper[index - 1] or close[index - 1] > upper[index - 1]
            else upper[index - 1]
        )
        lower[index] = (
            raw_lower[index]
            if raw_lower[index] > lower[index - 1] or close[index - 1] < lower[index - 1]
            else lower[index - 1]
        )
        if trend[index - 1] == upper[index - 1]:
            trend[index] = upper[index] if close[index] <= upper[index] else lower[index]
        else:
            trend[index] = lower[index] if close[index] >= lower[index] else upper[index]
    return pd.Series(trend, index=spy.index)


def _f125(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 22)
    atr_window = _positive_int(parameters, "atr_window", 14)
    multiplier = _non_negative_float(parameters, "atr_multiplier", 3.0)
    step = _non_negative_float(parameters, "acceleration_step", 0.02)
    maximum = _non_negative_float(parameters, "acceleration_max", 0.2)
    if step == 0.0 or maximum < step:
        raise TechnicalFeatureEngineError("F125_INVALID_ACCELERATION")
    if multiplier == 0.0:
        raise TechnicalFeatureEngineError("F125_ZERO_ATR_MULTIPLIER")
    atr = _atr(spy, atr_window).replace(0.0, np.nan)
    sar_level = _parabolic_sar(
        spy["high"],
        spy["low"],
        acceleration_step=step,
        acceleration_max=maximum,
    )
    supertrend_level = _supertrend(spy, atr, multiplier)
    chandelier_long = (
        spy["high"].rolling(window, min_periods=window).max() - multiplier * atr
    )
    chandelier_short = (
        spy["low"].rolling(window, min_periods=window).min() + multiplier * atr
    )
    chandelier_center = 0.5 * (chandelier_long + chandelier_short)
    parabolic = (spy["close"] - sar_level) / atr
    supertrend = (spy["close"] - supertrend_level) / atr
    chandelier = (spy["close"] - chandelier_center) / atr
    components = pd.concat((parabolic, supertrend, chandelier), axis=1)
    consensus = np.sign(components).mean(axis=1).where(components.notna().all(axis=1))
    return _pick(
        parameters,
        "F125",
        {
            "parabolic_sar": parabolic,
            "supertrend": supertrend,
            "chandelier": chandelier,
            "consensus": consensus,
        },
        "consensus",
    )


def _f126(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 20)
    prior_high = spy["high"].shift(1).rolling(window, min_periods=window).max()
    prior_low = spy["low"].shift(1).rolling(window, min_periods=window).min()
    prior_close = spy["close"].shift(1)
    width = (prior_high - prior_low).replace(0.0, np.nan)
    pivot = (prior_high + prior_low + prior_close) / 3.0
    support = 2.0 * pivot - prior_high
    resistance = 2.0 * pivot - prior_low
    pivot_distance = (spy["close"] - pivot) / width
    support_resistance = (
        2.0 * (spy["close"] - support) / (resistance - support).replace(0.0, np.nan)
        - 1.0
    )
    fib_382 = prior_low + 0.382 * width
    fib_500 = prior_low + 0.500 * width
    fib_618 = prior_low + 0.618 * width
    fibonacci_position = pd.Series(
        np.select(
            (
                spy["close"].lt(fib_382),
                spy["close"].lt(fib_500),
                spy["close"].lt(fib_618),
            ),
            (-1.0, -1.0 / 3.0, 1.0 / 3.0),
            default=1.0,
        ),
        index=spy.index,
    ).where(width.notna())
    levels = np.column_stack(
        (
            support.to_numpy(dtype=float),
            pivot.to_numpy(dtype=float),
            resistance.to_numpy(dtype=float),
            fib_382.to_numpy(dtype=float),
            fib_500.to_numpy(dtype=float),
            fib_618.to_numpy(dtype=float),
        )
    )
    deltas = spy["close"].to_numpy(dtype=float)[:, None] - levels
    absolute = np.where(np.isfinite(deltas), np.abs(deltas), np.inf)
    selected = np.argmin(absolute, axis=1)
    nearest = deltas[np.arange(len(spy)), selected]
    nearest[~np.isfinite(absolute).any(axis=1)] = np.nan
    nearest_level = pd.Series(nearest, index=spy.index) / width
    return _pick(
        parameters,
        "F126",
        {
            "pivot_distance": pivot_distance,
            "support_resistance_position": support_resistance,
            "fibonacci_position": fibonacci_position,
            "nearest_level_distance": nearest_level,
        },
        "fibonacci_position",
    )


def _heikin_ashi(spy: pd.DataFrame) -> pd.Series:
    ha_close = spy[["open", "high", "low", "close"]].mean(axis=1)
    ha_open = np.full(len(spy), np.nan)
    if len(spy):
        ha_open[0] = 0.5 * (spy["open"].iloc[0] + spy["close"].iloc[0])
    for index in range(1, len(spy)):
        ha_open[index] = 0.5 * (ha_open[index - 1] + ha_close.iloc[index - 1])
    scale = (spy["high"] - spy["low"]).replace(0.0, np.nan)
    return (ha_close - pd.Series(ha_open, index=spy.index)) / scale


def _renko_direction(close: pd.Series, box_size: pd.Series) -> pd.Series:
    prices = close.to_numpy(dtype=float)
    boxes = box_size.to_numpy(dtype=float)
    result = np.full(len(close), np.nan)
    brick_close = np.nan
    direction = 0.0
    for index, price in enumerate(prices):
        if not np.isfinite(boxes[index]) or boxes[index] <= 0.0:
            continue
        if not np.isfinite(brick_close):
            brick_close = prices[index - 1] if index else price
        brick_count = np.trunc((price - brick_close) / boxes[index])
        if abs(brick_count) >= 1.0:
            brick_close += brick_count * boxes[index]
            direction = float(np.sign(brick_count))
        result[index] = direction
    return pd.Series(result, index=close.index)


def _point_figure_direction(
    close: pd.Series, box_size: pd.Series, reversal_boxes: int
) -> pd.Series:
    prices = close.to_numpy(dtype=float)
    boxes = box_size.to_numpy(dtype=float)
    result = np.full(len(close), np.nan)
    level = np.nan
    direction = 0.0
    for index, price in enumerate(prices):
        box = boxes[index]
        if not np.isfinite(box) or box <= 0.0:
            continue
        if not np.isfinite(level):
            level = prices[index - 1] if index else price
        move = price - level
        if direction == 0.0:
            count = np.trunc(move / box)
            if abs(count) >= 1.0:
                direction = float(np.sign(count))
                level += count * box
        elif direction > 0.0:
            if move >= box:
                level += np.floor(move / box) * box
            elif move <= -float(reversal_boxes) * box:
                direction = -1.0
                level -= np.floor(-move / box) * box
        else:
            if move <= -box:
                level -= np.floor(-move / box) * box
            elif move >= float(reversal_boxes) * box:
                direction = 1.0
                level += np.floor(move / box) * box
        result[index] = direction
    return pd.Series(result, index=close.index)


def _f127(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 14)
    box_atr = _non_negative_float(parameters, "box_atr", 1.0)
    reversal_boxes = _positive_int(parameters, "reversal_boxes", 3)
    if box_atr == 0.0:
        raise TechnicalFeatureEngineError("F127_ZERO_BOX_ATR")
    box = _atr(spy, window).shift(1) * box_atr
    heikin_ashi = _heikin_ashi(spy)
    renko = _renko_direction(spy["close"], box)
    point_figure = _point_figure_direction(spy["close"], box, reversal_boxes)
    components = pd.concat((np.sign(heikin_ashi), renko, point_figure), axis=1)
    consensus = components.mean(axis=1).where(components.notna().all(axis=1))
    return _pick(
        parameters,
        "F127",
        {
            "heikin_ashi": heikin_ashi,
            "renko": renko,
            "point_figure": point_figure,
            "consensus": consensus,
        },
        "consensus",
    )


def _chart_patterns(
    spy: pd.DataFrame,
    *,
    window: int,
    tolerance: float,
    head_margin: float,
    breakout_buffer: float,
) -> Mapping[str, pd.Series]:
    outputs = {
        name: np.full(len(spy), np.nan)
        for name in ("triangle", "wedge", "double_extreme", "shoulders")
    }
    x = np.arange(float(window))
    high = spy["high"].to_numpy(dtype=float)
    low = spy["low"].to_numpy(dtype=float)
    close = spy["close"].to_numpy(dtype=float)
    first_end = window // 3
    second_end = 2 * window // 3
    for index in range(window - 1, len(spy)):
        start = index - window + 1
        highs = high[start : index + 1]
        lows = low[start : index + 1]
        closes = close[start : index + 1]
        high_slope = float(np.polyfit(x, highs, 1)[0])
        low_slope = float(np.polyfit(x, lows, 1)[0])
        midpoint = 0.5 * (highs[-1] + lows[-1])
        half_range = max(0.5 * (highs[-1] - lows[-1]), np.finfo(float).eps)
        triangle = high_slope < 0.0 and low_slope > 0.0
        outputs["triangle"][index] = (
            float(np.clip((closes[-1] - midpoint) / half_range, -2.0, 2.0))
            if triangle
            else 0.0
        )
        same_direction = high_slope * low_slope > 0.0
        converging = high_slope < low_slope
        slope_scale = abs(high_slope) + abs(low_slope) + np.finfo(float).eps
        outputs["wedge"][index] = (
            float(np.sign(high_slope + low_slope))
            * max(0.0, 1.0 - abs(high_slope - low_slope) / slope_scale)
            if same_direction and converging
            else 0.0
        )
        high_segments = (
            float(np.max(highs[:first_end])),
            float(np.max(highs[first_end:second_end])),
            float(np.max(highs[second_end:])),
        )
        low_segments = (
            float(np.min(lows[:first_end])),
            float(np.min(lows[first_end:second_end])),
            float(np.min(lows[second_end:])),
        )
        top_scale = max(0.5 * (high_segments[0] + high_segments[2]), np.finfo(float).eps)
        bottom_scale = max(0.5 * (low_segments[0] + low_segments[2]), np.finfo(float).eps)
        double_top = (
            abs(high_segments[0] - high_segments[2]) / top_scale <= tolerance
            and high_segments[1] < min(high_segments[0], high_segments[2])
            and closes[-1] < np.median(closes) * (1.0 - breakout_buffer)
        )
        double_bottom = (
            abs(low_segments[0] - low_segments[2]) / bottom_scale <= tolerance
            and low_segments[1] > max(low_segments[0], low_segments[2])
            and closes[-1] > np.median(closes) * (1.0 + breakout_buffer)
        )
        outputs["double_extreme"][index] = float(double_bottom) - float(double_top)
        top_shoulders = (
            abs(high_segments[0] - high_segments[2]) / top_scale <= tolerance
            and high_segments[1]
            > max(high_segments[0], high_segments[2]) * (1.0 + head_margin)
        )
        bottom_shoulders = (
            abs(low_segments[0] - low_segments[2]) / bottom_scale <= tolerance
            and low_segments[1]
            < min(low_segments[0], low_segments[2]) * (1.0 - head_margin)
        )
        outputs["shoulders"][index] = float(bottom_shoulders) - float(top_shoulders)
    return {
        name: pd.Series(values, index=spy.index) for name, values in outputs.items()
    }


def _f128(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    if window < 9:
        raise TechnicalFeatureEngineError("F128_WINDOW_BELOW_NINE")
    tolerance = _non_negative_float(parameters, "tolerance", 0.03)
    head_margin = _non_negative_float(parameters, "head_margin", 0.05)
    breakout_buffer = _non_negative_float(parameters, "breakout_buffer", 0.0)
    choices = _chart_patterns(
        spy,
        window=window,
        tolerance=tolerance,
        head_margin=head_margin,
        breakout_buffer=breakout_buffer,
    )
    return _pick(parameters, "F128", choices, "triangle")


def _f129(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 20)
    overnight = np.log(spy["open"] / spy["close"].shift(1))
    intraday = np.log(spy["close"] / spy["open"])
    overnight_momentum = overnight.rolling(window, min_periods=window).sum()
    intraday_momentum = intraday.rolling(window, min_periods=window).sum()
    continuation = (np.sign(overnight) * intraday).rolling(
        window, min_periods=window
    ).mean()
    gap_fill_ratio = (-np.sign(overnight) * intraday).div(overnight.abs())
    gap_fill_ratio = gap_fill_ratio.where(overnight.ne(0.0), 0.0).clip(-2.0, 2.0)
    gap_fill = gap_fill_ratio.rolling(window, min_periods=window).mean()
    return _pick(
        parameters,
        "F129",
        {
            "overnight_momentum": overnight_momentum,
            "intraday_momentum": intraday_momentum,
            "continuation": continuation,
            "gap_fill": gap_fill,
        },
        "continuation",
    )


def _money_flow_index(spy: pd.DataFrame, window: int) -> pd.Series:
    typical = (spy["high"] + spy["low"] + spy["close"]) / 3.0
    raw_flow = typical * spy["volume"]
    change = typical.diff()
    positive = raw_flow.where(change.gt(0.0), 0.0).rolling(
        window, min_periods=window
    ).sum()
    negative = raw_flow.where(change.lt(0.0), 0.0).rolling(
        window, min_periods=window
    ).sum()
    ratio = positive / negative.replace(0.0, np.nan)
    mfi = 100.0 - 100.0 / (1.0 + ratio)
    mfi = mfi.mask(negative.eq(0.0) & positive.gt(0.0), 100.0)
    mfi = mfi.mask(negative.eq(0.0) & positive.eq(0.0), 50.0)
    return (mfi - 50.0) / 50.0


def _klinger_volume_force(spy: pd.DataFrame) -> pd.Series:
    total = spy["high"] + spy["low"] + spy["close"]
    dm = (spy["high"] - spy["low"]).to_numpy(dtype=float)
    trend = np.zeros(len(spy), dtype=float)
    cm = np.full(len(spy), np.nan)
    if len(spy):
        cm[0] = dm[0]
    total_values = total.to_numpy(dtype=float)
    for index in range(1, len(spy)):
        direction = float(np.sign(total_values[index] - total_values[index - 1]))
        trend[index] = direction if direction else trend[index - 1]
        cm[index] = (
            cm[index - 1] + dm[index]
            if trend[index] == trend[index - 1]
            else dm[index - 1] + dm[index]
        )
    ratio = np.divide(
        dm,
        cm,
        out=np.zeros(len(spy), dtype=float),
        where=np.isfinite(cm) & (cm != 0.0),
    )
    force = spy["volume"].to_numpy(dtype=float) * trend * np.abs(2.0 * ratio - 1.0)
    return pd.Series(force, index=spy.index)


def _f130(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 20)
    fast = _positive_int(parameters, "klinger_fast", 34)
    slow = _positive_int(parameters, "klinger_slow", 55)
    signal = _positive_int(parameters, "klinger_signal", 13)
    if fast >= slow:
        raise TechnicalFeatureEngineError("F130_KLINGER_FAST_NOT_BELOW_SLOW")
    bar_range = (spy["high"] - spy["low"]).replace(0.0, np.nan)
    multiplier = (
        (spy["close"] - spy["low"]) - (spy["high"] - spy["close"])
    ) / bar_range
    money_flow_volume = multiplier * spy["volume"]
    chaikin = money_flow_volume.rolling(window, min_periods=window).sum() / spy[
        "volume"
    ].rolling(window, min_periods=window).sum().replace(0.0, np.nan)
    money_flow = _money_flow_index(spy, window)
    raw_force = spy["close"].diff() * spy["volume"]
    force_scale = _ema(raw_force.abs(), window).replace(0.0, np.nan)
    force = _ema(raw_force, window) / force_scale
    midpoint_move = (0.5 * (spy["high"] + spy["low"])).diff()
    raw_eom = midpoint_move * bar_range / spy["volume"].replace(0.0, np.nan)
    ease = raw_eom.rolling(window, min_periods=window).sum() / raw_eom.abs().rolling(
        window, min_periods=window
    ).sum().replace(0.0, np.nan)
    volume_force = _klinger_volume_force(spy)
    klinger_line = _ema(volume_force, fast) - _ema(volume_force, slow)
    klinger_signal = _ema(klinger_line, signal)
    klinger_scale = _ema(volume_force.abs(), slow).replace(0.0, np.nan)
    klinger = (klinger_line - klinger_signal) / klinger_scale
    components = pd.concat(
        (chaikin, money_flow, force, ease, klinger), axis=1
    )
    consensus = np.sign(components).mean(axis=1).where(components.notna().all(axis=1))
    return _pick(
        parameters,
        "F130",
        {
            "chaikin_money_flow": chaikin,
            "money_flow_index": money_flow,
            "force_index": force,
            "ease_of_movement": ease,
            "klinger_oscillator": klinger,
            "consensus": consensus,
        },
        "consensus",
    )


_EVALUATORS = {
    "F121": _f121,
    "F122": _f122,
    "F123": _f123,
    "F124": _f124,
    "F125": _f125,
    "F126": _f126,
    "F127": _f127,
    "F128": _f128,
    "F129": _f129,
    "F130": _f130,
}


def evaluate_technical_lane(
    lane_id: str, spy_frame: pd.DataFrame, parameters: Mapping[str, Any]
) -> pd.DataFrame:
    """Evaluate one frozen F121-F130 lane from next-session SPY observations."""

    if lane_id not in _EVALUATORS:
        raise TechnicalFeatureEngineError(
            f"TECHNICAL_LANE_NOT_IMPLEMENTED:{lane_id}"
        )
    spy = _validated_spy(spy_frame)
    return _output(spy, _EVALUATORS[lane_id](spy, parameters))


_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F121": {"statistic": "range_position", "window": 252, "buffer_fraction": 0.0, "confirmation": 2},
    "F122": {"statistic": "directional_strength", "window": 14},
    "F123": {"statistic": "ppo", "fast": 12, "slow": 26, "signal": 9},
    "F124": {"statistic": "cloud_position", "conversion_window": 9, "base_window": 26, "span_b_window": 52, "atr_window": 14},
    "F125": {"statistic": "consensus", "window": 22, "atr_window": 14, "atr_multiplier": 3.0, "acceleration_step": 0.02, "acceleration_max": 0.2},
    "F126": {"statistic": "fibonacci_position", "window": 20},
    "F127": {"statistic": "consensus", "window": 14, "box_atr": 1.0, "reversal_boxes": 3},
    "F128": {"statistic": "triangle", "window": 63, "tolerance": 0.03, "head_margin": 0.05, "breakout_buffer": 0.0},
    "F129": {"statistic": "continuation", "window": 20},
    "F130": {"statistic": "consensus", "window": 20, "klinger_fast": 34, "klinger_slow": 55, "klinger_signal": 13},
}


def evaluate_technical_family_batch(
    spy_frame: pd.DataFrame,
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for each F121-F130 lane."""

    spy = _validated_spy(spy_frame)
    return {
        lane_id: evaluate_technical_lane(lane_id, spy, parameters)
        for lane_id, parameters in _BATCH_PARAMETERS.items()
    }


__all__ = [
    "TechnicalFeatureEngineError",
    "evaluate_technical_family_batch",
    "evaluate_technical_lane",
]
