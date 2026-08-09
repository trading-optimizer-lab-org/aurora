"""Causal daily path, volume and liquidity kernels for SP500 lanes F071-F080."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


class MicrostructureFeatureEngineError(ValueError):
    """Raised when a daily microstructure feature violates the frozen contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_EPSILON = 1e-12


def _validated_spy(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "date",
        "observed_at",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MicrostructureFeatureEngineError(
            f"SPY_COLUMNS_MISSING:{','.join(missing)}"
        )
    spy = frame.loc[:, sorted(required)].copy()
    for column in ("date", "observed_at", "available_at"):
        spy[column] = (
            pd.to_datetime(spy[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if spy[["date", "observed_at", "available_at"]].isna().any().any():
        raise MicrostructureFeatureEngineError("INVALID_SPY_DATE")
    if spy["date"].gt(_TRAIN_END).any() or spy["available_at"].gt(_TRAIN_END).any():
        raise MicrostructureFeatureEngineError("NON_TRAIN_SPY_ROW")
    if spy["available_at"].gt(spy["date"]).any():
        raise MicrostructureFeatureEngineError("SPY_NOT_AVAILABLE_AT_DECISION")
    if spy["observed_at"].gt(spy["available_at"]).any():
        raise MicrostructureFeatureEngineError("SPY_OBSERVED_AFTER_AVAILABILITY")
    if spy["date"].duplicated().any() or not spy["date"].is_monotonic_increasing:
        raise MicrostructureFeatureEngineError("SPY_DATES_NOT_ORDERED")
    for column in ("open", "high", "low", "close", "volume"):
        spy[column] = pd.to_numeric(spy[column], errors="coerce")
    if spy[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise MicrostructureFeatureEngineError("INVALID_SPY_VALUE")
    if spy[["open", "high", "low", "close"]].le(0.0).any().any():
        raise MicrostructureFeatureEngineError("NON_POSITIVE_SPY_PRICE")
    if spy["volume"].le(0.0).any():
        raise MicrostructureFeatureEngineError("NON_POSITIVE_SPY_VOLUME")
    if spy["high"].lt(spy[["open", "close"]].max(axis=1)).any():
        raise MicrostructureFeatureEngineError("SPY_HIGH_BELOW_BODY")
    if spy["low"].gt(spy[["open", "close"]].min(axis=1)).any():
        raise MicrostructureFeatureEngineError("SPY_LOW_ABOVE_BODY")
    return spy.reset_index(drop=True)


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


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise MicrostructureFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _daily_variances(spy: pd.DataFrame) -> pd.DataFrame:
    high_low = np.log(spy["high"] / spy["low"])
    close_open = np.log(spy["close"] / spy["open"])
    return pd.DataFrame(
        {
            "close": np.log(spy["close"]).diff().pow(2),
            "parkinson": high_low.pow(2) / (4.0 * np.log(2.0)),
            "garman_klass": (
                0.5 * high_low.pow(2)
                - (2.0 * np.log(2.0) - 1.0) * close_open.pow(2)
            ).clip(lower=_EPSILON),
            "rogers_satchell": (
                np.log(spy["high"] / spy["open"])
                * np.log(spy["high"] / spy["close"])
                + np.log(spy["low"] / spy["open"])
                * np.log(spy["low"] / spy["close"])
            ).clip(lower=_EPSILON),
        },
        index=spy.index,
    )


def _f071(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    """Daily-sampling proxies; deliberately not intraday realised measures."""

    window = _positive_int(parameters, "window", 63)
    statistic = str(parameters.get("statistic", "semivariance_imbalance"))
    returns = np.log(spy["close"]).diff()
    squared = returns.pow(2)
    positive_daily = squared.where(returns.ge(0.0), 0.0).where(returns.notna())
    negative_daily = squared.where(returns.lt(0.0), 0.0).where(returns.notna())
    positive = positive_daily.rolling(
        window, min_periods=window
    ).mean()
    negative = negative_daily.rolling(
        window, min_periods=window
    ).mean()
    bipower_daily = (np.pi / 2.0) * returns.abs() * returns.shift(1).abs()
    bipower = bipower_daily.rolling(window, min_periods=window).mean()
    range_variance = _daily_variances(spy)["rogers_satchell"]
    range_mean = range_variance.rolling(window, min_periods=window).mean()
    orientation = np.sign(returns.rolling(window, min_periods=window).sum())
    if statistic == "semivariance_imbalance":
        return (positive - negative) / (positive + negative + _EPSILON)
    if statistic == "bipower_share":
        return orientation * bipower / (bipower + range_mean + _EPSILON)
    if statistic == "jump_proxy":
        jump = (range_variance - bipower_daily).clip(lower=0.0)
        signed_jump = np.sign(returns) * jump
        numerator = signed_jump.rolling(window, min_periods=window).sum()
        denominator = range_variance.rolling(window, min_periods=window).sum()
        return numerator / (denominator + _EPSILON)
    raise MicrostructureFeatureEngineError(f"F071_UNKNOWN_STATISTIC:{statistic}")


def _f072(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    statistic = str(parameters.get("statistic", "dispersion"))
    smoothed = _daily_variances(spy).rolling(window, min_periods=window).mean()
    logged = np.log(smoothed.clip(lower=_EPSILON))
    if statistic == "dispersion":
        return logged.std(axis=1, ddof=0)
    if statistic == "max_min_ratio":
        return logged.max(axis=1) - logged.min(axis=1)
    if statistic == "close_vs_range":
        range_mean = smoothed[
            ["parkinson", "garman_klass", "rogers_satchell"]
        ].mean(axis=1)
        return np.log((smoothed["close"] + _EPSILON) / (range_mean + _EPSILON))
    raise MicrostructureFeatureEngineError(f"F072_UNKNOWN_STATISTIC:{statistic}")


def _f073(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    length = _positive_int(parameters, "length", 3)
    if not 2 <= length <= 5:
        raise MicrostructureFeatureEngineError(f"F073_LENGTH_OUTSIDE_2_TO_5:{length}")
    tolerance = float(parameters.get("tolerance", 0.1))
    if not 0.0 <= tolerance < 1.0:
        raise MicrostructureFeatureEngineError("F073_INVALID_TOLERANCE")
    pattern = str(parameters.get("pattern", "direction_run"))
    bar_range = (spy["high"] - spy["low"]).clip(lower=_EPSILON)
    body = spy["close"] - spy["open"]
    body_ratio = body / bar_range
    orientation = np.sign(body).where(body_ratio.abs().ge(tolerance), 0.0)
    if pattern == "direction_run":
        value = orientation.rolling(length, min_periods=length).mean()
    elif pattern == "engulfing":
        previous_body_high = spy[["open", "close"]].max(axis=1).shift(1).rolling(
            length - 1, min_periods=length - 1
        ).max()
        previous_body_low = spy[["open", "close"]].min(axis=1).shift(1).rolling(
            length - 1, min_periods=length - 1
        ).min()
        current_high = spy[["open", "close"]].max(axis=1)
        current_low = spy[["open", "close"]].min(axis=1)
        engulfed = current_high.ge(previous_body_high) & current_low.le(previous_body_low)
        value = orientation.where(engulfed, 0.0)
        value = value.where(previous_body_high.notna())
    elif pattern == "wick_reversal":
        upper = spy["high"] - spy[["open", "close"]].max(axis=1)
        lower = spy[["open", "close"]].min(axis=1) - spy["low"]
        wick_score = (lower - upper) / bar_range
        value = wick_score.rolling(length, min_periods=length).mean()
        valid = value.notna()
        pattern_present = body_ratio.abs().rolling(length).max().ge(tolerance)
        value = value.where(pattern_present, 0.0).where(valid)
    elif pattern == "range_breakout":
        previous_high = spy["high"].shift(1).rolling(
            length - 1, min_periods=length - 1
        ).max()
        previous_low = spy["low"].shift(1).rolling(
            length - 1, min_periods=length - 1
        ).min()
        previous_range = (previous_high - previous_low).clip(lower=_EPSILON)
        upward = ((spy["close"] - previous_high) / previous_range - tolerance).clip(
            lower=0.0
        )
        downward = ((previous_low - spy["close"]) / previous_range - tolerance).clip(
            lower=0.0
        )
        value = (upward - downward).clip(-1.0, 1.0)
        value = value.where(previous_high.notna())
    else:
        raise MicrostructureFeatureEngineError(f"F073_UNKNOWN_PATTERN:{pattern}")
    direction = str(parameters.get("direction", "continuation"))
    if direction == "reversal":
        return -value
    if direction == "continuation":
        return value
    raise MicrostructureFeatureEngineError(f"F073_UNKNOWN_DIRECTION:{direction}")


def _confirmed_pivots(
    values: np.ndarray, *, span: int, high: bool
) -> list[tuple[int, int, float]]:
    pivots: list[tuple[int, int, float]] = []
    for index in range(span, len(values) - span):
        segment = values[index - span : index + span + 1]
        pivot = values[index]
        is_pivot = pivot >= float(segment.max()) if high else pivot <= float(segment.min())
        if is_pivot:
            pivots.append((index, index + span, float(pivot)))
    return pivots


def _f074(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    span = _positive_int(parameters, "pivot_span", 3)
    tolerance = float(parameters.get("tolerance", 0.01))
    if not 0.0 < tolerance <= 0.1:
        raise MicrostructureFeatureEngineError("F074_INVALID_TOLERANCE")
    statistic = str(parameters.get("statistic", "nearest_balance"))
    highs = spy["high"].to_numpy(dtype=float)
    lows = spy["low"].to_numpy(dtype=float)
    closes = spy["close"].to_numpy(dtype=float)
    high_pivots = _confirmed_pivots(highs, span=span, high=True)
    low_pivots = _confirmed_pivots(lows, span=span, high=False)
    result = np.full(len(spy), np.nan, dtype=float)
    for index in range(window, len(spy)):
        current = closes[index]
        if statistic == "breakout_pressure":
            past_high = float(highs[index - window : index].max())
            past_low = float(lows[index - window : index].min())
            midpoint = 0.5 * (past_high + past_low)
            result[index] = float(
                np.clip(2.0 * (current - midpoint) / (past_high - past_low), -2.0, 2.0)
            )
            continue
        first = index - window
        supports = [
            value
            for pivot_index, confirmed_at, value in low_pivots
            if first <= pivot_index < index and confirmed_at <= index and value <= current
        ]
        resistances = [
            value
            for pivot_index, confirmed_at, value in high_pivots
            if first <= pivot_index < index and confirmed_at <= index and value >= current
        ]
        if statistic == "nearest_balance":
            support = max(supports, default=float(lows[first:index].min()))
            resistance = min(resistances, default=float(highs[first:index].max()))
            downside = max(current - support, 0.0)
            upside = max(resistance - current, 0.0)
            result[index] = (upside - downside) / (upside + downside + _EPSILON)
        elif statistic == "touch_imbalance":
            support_touches = sum(
                abs(current - value) / current <= tolerance for value in supports
            )
            resistance_touches = sum(
                abs(value - current) / current <= tolerance for value in resistances
            )
            result[index] = (support_touches - resistance_touches) / max(
                support_touches + resistance_touches, 1
            )
        else:
            raise MicrostructureFeatureEngineError(
                f"F074_UNKNOWN_STATISTIC:{statistic}"
            )
    return pd.Series(result, index=spy.index)


def _f075(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    degree = _positive_int(parameters, "degree", 2)
    if degree not in {2, 3}:
        raise MicrostructureFeatureEngineError(f"F075_INVALID_DEGREE:{degree}")
    statistic = str(parameters.get("statistic", "slope"))
    log_close = np.log(spy["close"]).to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    x = np.linspace(-1.0, 0.0, window)
    for index in range(window - 1, len(spy)):
        segment = log_close[index - window + 1 : index + 1]
        coefficients = np.polynomial.polynomial.polyfit(
            x, segment - float(segment.mean()), degree
        )
        slope = float(coefficients[1]) / (window - 1)
        acceleration = 2.0 * float(coefficients[2]) / ((window - 1) ** 2)
        scale = max(float(np.std(np.diff(segment), ddof=0)), _EPSILON)
        if statistic == "slope":
            value = slope / scale
        elif statistic == "acceleration":
            value = acceleration / scale
        elif statistic == "convexity":
            value = acceleration / (scale * (1.0 + (slope / scale) ** 2) ** 1.5)
        elif statistic == "exhaustion":
            value = -np.sign(slope) * acceleration / scale
        else:
            raise MicrostructureFeatureEngineError(
                f"F075_UNKNOWN_STATISTIC:{statistic}"
            )
        result[index] = float(np.clip(value, -20.0, 20.0))
    return pd.Series(result, index=spy.index)


def _f076(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    lag = _positive_int(parameters, "lag", 2)
    direction = str(parameters.get("direction", "volume_leads_return"))
    statistic = str(parameters.get("statistic", "correlation"))
    returns = np.log(spy["close"]).diff().to_numpy(dtype=float)
    volume_change = np.log(spy["volume"]).diff().to_numpy(dtype=float)
    if direction == "volume_leads_return":
        leader, target = volume_change, returns
    elif direction == "return_leads_volume":
        leader, target = returns, volume_change
    else:
        raise MicrostructureFeatureEngineError(f"F076_UNKNOWN_DIRECTION:{direction}")
    result = np.full(len(spy), np.nan, dtype=float)
    for index in range(window + lag, len(spy)):
        target_segment = target[index - window + 1 : index + 1]
        leader_segment = leader[index - window + 1 - lag : index + 1 - lag]
        if not np.isfinite(target_segment).all() or not np.isfinite(leader_segment).all():
            continue
        if min(float(np.std(target_segment)), float(np.std(leader_segment))) <= _EPSILON:
            correlation = 0.0
        else:
            correlation = float(np.corrcoef(leader_segment, target_segment)[0, 1])
        if statistic == "correlation":
            result[index] = correlation
        elif statistic == "predictive_score":
            recent = leader[index - window + 1 : index + 1]
            scale = max(float(np.std(recent, ddof=0)), _EPSILON)
            impulse = (leader[index] - float(np.mean(recent))) / scale
            result[index] = float(np.clip(correlation * impulse, -10.0, 10.0))
        else:
            raise MicrostructureFeatureEngineError(
                f"F076_UNKNOWN_STATISTIC:{statistic}"
            )
    return pd.Series(result, index=spy.index)


def _f077(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    statistic = str(parameters.get("statistic", "imbalance"))
    returns = np.log(spy["close"]).diff()
    signed_volume = np.sign(returns) * spy["volume"]
    if statistic == "imbalance":
        return signed_volume.rolling(window, min_periods=window).sum() / (
            spy["volume"].rolling(window, min_periods=window).sum() + _EPSILON
        )
    if statistic == "obv_slope":
        obv = signed_volume.fillna(0.0).cumsum()
        average_volume = spy["volume"].rolling(window, min_periods=window).mean()
        return (obv - obv.shift(window - 1)) / (
            (window - 1) * average_volume + _EPSILON
        )
    if statistic == "pressure":
        median_volume = spy["volume"].rolling(window, min_periods=window).median()
        pressure = np.sign(returns) * np.log1p(spy["volume"] / median_volume)
        return np.tanh(pressure.rolling(window, min_periods=window).mean())
    raise MicrostructureFeatureEngineError(f"F077_UNKNOWN_STATISTIC:{statistic}")


def _roll_spread(spy: pd.DataFrame, window: int) -> pd.Series:
    price_change = spy["close"].diff()
    covariance = price_change.rolling(window, min_periods=window).cov(
        price_change.shift(1)
    )
    spread = 2.0 * np.sqrt((-covariance).clip(lower=0.0))
    return spread / spy["close"].rolling(window, min_periods=window).mean()


def _corwin_schultz_spread(spy: pd.DataFrame, window: int) -> pd.Series:
    log_range = np.log(spy["high"] / spy["low"])
    beta = log_range.pow(2) + log_range.shift(1).pow(2)
    two_day_high = spy["high"].rolling(2, min_periods=2).max()
    two_day_low = spy["low"].rolling(2, min_periods=2).min()
    gamma = np.log(two_day_high / two_day_low).pow(2)
    denominator = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (
        (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denominator
        - np.sqrt(gamma / denominator)
    ).clip(lower=0.0, upper=20.0)
    spread = 2.0 * np.expm1(alpha) / (1.0 + np.exp(alpha))
    return spread.rolling(window, min_periods=window).mean()


def _amihud_illiquidity(spy: pd.DataFrame, window: int) -> pd.Series:
    returns = np.log(spy["close"]).diff().abs()
    dollar_volume = spy["close"] * spy["volume"]
    daily = 1_000_000.0 * returns / dollar_volume
    return daily.rolling(window, min_periods=window).mean()


def _f078(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    estimator = str(parameters.get("estimator", "roll"))
    if estimator == "roll":
        return _roll_spread(spy, window)
    if estimator == "corwin_schultz":
        return _corwin_schultz_spread(spy, window)
    if estimator == "amihud":
        return _amihud_illiquidity(spy, window)
    raise MicrostructureFeatureEngineError(f"F078_UNKNOWN_ESTIMATOR:{estimator}")


def _f079(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    statistic = str(parameters.get("statistic", "zero_return_rate"))
    tolerance = float(parameters.get("zero_tolerance_bps", 0.5))
    if tolerance < 0.0:
        raise MicrostructureFeatureEngineError("F079_NEGATIVE_ZERO_TOLERANCE")
    returns = np.log(spy["close"]).diff()
    dollar_volume = spy["close"] * spy["volume"]
    log_volume = np.log(dollar_volume)
    median = log_volume.rolling(window, min_periods=window).median()
    if statistic == "zero_return_rate":
        zero = returns.abs().mul(10_000.0).le(tolerance).astype(float)
        zero = zero.where(returns.notna())
        return zero.rolling(window, min_periods=window).mean()
    if statistic == "volume_drought":
        return (median - log_volume).clip(lower=0.0)
    if statistic == "volume_shock":
        scale = log_volume.rolling(window, min_periods=window).std(ddof=0)
        return (log_volume - median).abs() / (scale + _EPSILON)
    raise MicrostructureFeatureEngineError(f"F079_UNKNOWN_STATISTIC:{statistic}")


def _causal_percentile(series: pd.Series, window: int) -> pd.Series:
    def percentile(values: np.ndarray) -> float:
        if not np.isfinite(values).all():
            return np.nan
        current = values[-1]
        return float(np.mean(values < current) + 0.5 * np.mean(values == current))

    return series.rolling(window, min_periods=window).apply(percentile, raw=True)


def _f080(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    base_window = _positive_int(parameters, "base_window", 20)
    liquidity_window = _positive_int(parameters, "liquidity_window", 63)
    confirmation = _positive_int(parameters, "confirmation", 2)
    threshold = float(parameters.get("stress_quantile", 0.75))
    if not 0.0 < threshold < 1.0:
        raise MicrostructureFeatureEngineError("F080_INVALID_STRESS_QUANTILE")
    returns = np.log(spy["close"]).diff()
    cumulative = np.log(spy["close"] / spy["close"].shift(base_window))
    volatility = returns.rolling(base_window, min_periods=base_window).std(ddof=0)
    base_score = np.tanh(cumulative / (volatility * np.sqrt(base_window) + _EPSILON))
    base = str(parameters.get("base", "trend"))
    if base == "reversal":
        base_score = -base_score
    elif base != "trend":
        raise MicrostructureFeatureEngineError(f"F080_UNKNOWN_BASE:{base}")
    liquidity = str(parameters.get("liquidity", "roll"))
    if liquidity in {"roll", "corwin_schultz"}:
        stress = _f078(
            spy, {"estimator": liquidity, "window": liquidity_window}
        )
    elif liquidity == "volume_drought":
        stress = _f079(
            spy,
            {
                "statistic": "volume_drought",
                "window": liquidity_window,
                "zero_tolerance_bps": 0.5,
            },
        )
    else:
        raise MicrostructureFeatureEngineError(
            f"F080_UNKNOWN_LIQUIDITY:{liquidity}"
        )
    stress_percentile = _causal_percentile(stress, liquidity_window)
    liquid = stress_percentile.le(threshold).where(stress_percentile.notna())
    confirmed = liquid.astype(float).rolling(
        confirmation, min_periods=confirmation
    ).min()
    logic = str(parameters.get("logic", "gate"))
    if logic == "gate":
        return base_score * confirmed
    if logic == "attenuate":
        return base_score * confirmed * (1.0 - stress_percentile)
    raise MicrostructureFeatureEngineError(f"F080_UNKNOWN_LOGIC:{logic}")


def evaluate_microstructure_lane(
    lane_id: str,
    spy_frame: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one exact F071-F080 kernel using information known by each row."""

    spy = _validated_spy(spy_frame)
    evaluators = {
        "F071": _f071,
        "F072": _f072,
        "F073": _f073,
        "F074": _f074,
        "F075": _f075,
        "F076": _f076,
        "F077": _f077,
        "F078": _f078,
        "F079": _f079,
        "F080": _f080,
    }
    try:
        evaluator = evaluators[lane_id]
    except KeyError as exc:
        raise MicrostructureFeatureEngineError(
            f"MICROSTRUCTURE_LANE_NOT_IMPLEMENTED:{lane_id}"
        ) from exc
    return _output(spy, evaluator(spy, parameters))


_MICROSTRUCTURE_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F071": {"statistic": "jump_proxy", "window": 126},
    "F072": {"statistic": "dispersion", "window": 126},
    "F073": {
        "pattern": "wick_reversal",
        "length": 3,
        "tolerance": 0.1,
        "direction": "continuation",
    },
    "F074": {
        "statistic": "nearest_balance",
        "window": 252,
        "pivot_span": 5,
        "tolerance": 0.01,
    },
    "F075": {"statistic": "acceleration", "window": 126, "degree": 3},
    "F076": {
        "direction": "volume_leads_return",
        "statistic": "predictive_score",
        "window": 252,
        "lag": 5,
    },
    "F077": {"statistic": "imbalance", "window": 126},
    "F078": {"estimator": "corwin_schultz", "window": 126},
    "F079": {
        "statistic": "volume_drought",
        "window": 126,
        "zero_tolerance_bps": 0.5,
    },
    "F080": {
        "base": "trend",
        "base_window": 63,
        "liquidity": "volume_drought",
        "liquidity_window": 126,
        "stress_quantile": 0.75,
        "confirmation": 3,
        "logic": "gate",
    },
}


def evaluate_microstructure_family_batch(
    spy_frame: pd.DataFrame,
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for every F071-F080 lane."""

    return {
        lane_id: evaluate_microstructure_lane(lane_id, spy_frame, parameters)
        for lane_id, parameters in _MICROSTRUCTURE_BATCH_PARAMETERS.items()
    }


__all__ = [
    "MicrostructureFeatureEngineError",
    "evaluate_microstructure_family_batch",
    "evaluate_microstructure_lane",
]
