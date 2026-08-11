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


def _rolling_percentile(values: pd.Series, window: int) -> pd.Series:
    def percentile(row: np.ndarray) -> float:
        current = row[-1]
        return float((np.sum(row < current) + 0.5 * np.sum(row == current)) / len(row))

    return values.rolling(window, min_periods=window).apply(percentile, raw=True) - 0.5


def _normalize(values: pd.Series, kind: str, window: int) -> pd.Series:
    if kind == "none":
        return values
    if kind == "rolling_z":
        return _rolling_z(values, window)
    if kind == "rolling_percentile":
        return _rolling_percentile(values, window)
    raise FeatureEngineError(f"UNKNOWN_NORMALIZATION:{kind}")


def _orient(values: pd.Series, direction: str) -> pd.Series:
    if direction == "continuation":
        return values
    if direction == "reversal":
        return -values
    raise FeatureEngineError(f"UNKNOWN_DIRECTION:{direction}")


def _deadband(values: pd.Series, threshold: float | pd.Series) -> pd.Series:
    if isinstance(threshold, pd.Series):
        if threshold.dropna().lt(0.0).any():
            raise FeatureEngineError("NEGATIVE_THRESHOLD_SERIES")
    elif threshold < 0.0:
        raise FeatureEngineError(f"NEGATIVE_THRESHOLD:{threshold}")
    return np.sign(values) * (values.abs() - threshold).clip(lower=0.0)


def _confirmed(values: pd.Series, periods: int) -> pd.Series:
    if periods < 1:
        raise FeatureEngineError(f"INVALID_CONFIRMATION:{periods}")
    if periods == 1:
        return values
    sign = np.sign(values)
    positive = sign.eq(1.0).rolling(periods, min_periods=periods).sum().eq(periods)
    negative = sign.eq(-1.0).rolling(periods, min_periods=periods).sum().eq(periods)
    state = pd.Series(np.nan, index=values.index, dtype=float)
    state.loc[positive] = 1.0
    state.loc[negative] = -1.0
    state = state.ffill().fillna(0.0)
    return state * values.abs()


def _minimum_hold(values: pd.Series, periods: int) -> pd.Series:
    if periods < 1:
        raise FeatureEngineError(f"INVALID_HOLD:{periods}")
    desired = np.sign(values.fillna(0.0)).to_numpy(dtype=float)
    state = 0.0
    age = periods
    held = np.zeros(len(desired), dtype=float)
    for index, target in enumerate(desired):
        if target != 0.0 and target != state and age >= periods:
            state = target
            age = 0
        else:
            age += 1
        held[index] = state
    return pd.Series(held, index=values.index) * values.abs()


def _rolling_r2(values: pd.Series, window: int) -> pd.Series:
    x = np.arange(float(window))

    def r2(row: np.ndarray) -> float:
        if float(np.std(row)) == 0.0:
            return 0.0
        correlation = float(np.corrcoef(x, row)[0, 1])
        return correlation * correlation

    return values.rolling(window, min_periods=window).apply(r2, raw=True)


def _directional_components(spy: pd.DataFrame, window: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = spy["high"].diff()
    down = -spy["low"].diff()
    plus_dm = up.where((up > down) & (up > 0.0), 0.0)
    minus_dm = down.where((down > up) & (down > 0.0), 0.0)
    atr = _true_range(spy).rolling(window, min_periods=window).mean().replace(0.0, np.nan)
    plus_di = 100.0 * plus_dm.rolling(window, min_periods=window).mean() / atr
    minus_di = 100.0 * minus_dm.rolling(window, min_periods=window).mean() / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.rolling(window, min_periods=window).mean()
    return plus_di, minus_di, adx


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
        threshold = float(parameters.get("threshold", 0.0))
        if normalization == "price_ratio":
            threshold /= 100.0
        value = _deadband(value, threshold)
    elif lane_id == "F002":
        kind = str(parameters.get("kind", "ema"))
        fast = int(parameters.get("fast", 20))
        slow = int(parameters.get("slow", 126))
        if fast >= slow:
            raise FeatureEngineError("F002_FAST_NOT_BELOW_SLOW")
        if kind in {"sma", "ema", "wma"}:
            value = (
                _moving_average(close, kind, fast)
                / _moving_average(close, kind, slow)
                - 1.0
            )
        elif kind == "macd":
            value = (
                _moving_average(close, "ema", fast)
                - _moving_average(close, "ema", slow)
            ) / close
        elif kind == "ppo":
            slow_average = _moving_average(close, "ema", slow)
            value = 100.0 * (
                _moving_average(close, "ema", fast) / slow_average - 1.0
            )
        elif kind == "trix":
            fast_triple = close
            slow_triple = close
            for _ in range(3):
                fast_triple = fast_triple.ewm(
                    span=fast, adjust=False, min_periods=fast
                ).mean()
                slow_triple = slow_triple.ewm(
                    span=slow, adjust=False, min_periods=slow
                ).mean()
            value = fast_triple.pct_change(fill_method=None) - slow_triple.pct_change(
                fill_method=None
            )
        elif kind == "tsi":
            momentum = close.diff()
            numerator = momentum.ewm(
                span=slow, adjust=False, min_periods=slow
            ).mean().ewm(span=fast, adjust=False, min_periods=fast).mean()
            denominator = momentum.abs().ewm(
                span=slow, adjust=False, min_periods=slow
            ).mean().ewm(span=fast, adjust=False, min_periods=fast).mean()
            value = numerator / denominator.replace(0.0, np.nan)
        else:
            raise FeatureEngineError(f"F002_UNKNOWN_KIND:{kind}")
        value = _confirmed(value, int(parameters.get("confirmation", 1)))
    elif lane_id == "F003":
        window = int(parameters["window"])
        skip = int(parameters.get("skip", 0))
        endpoint = close.shift(skip)
        if str(parameters.get("return_kind", "simple")) == "log":
            value = np.log(endpoint) - np.log(endpoint.shift(window))
        else:
            value = endpoint / endpoint.shift(window) - 1.0
        value = _deadband(value, float(parameters.get("threshold", 0.0)))
    elif lane_id == "F004":
        component_count = int(parameters.get("components", 4))
        short_window = int(parameters.get("short_window", 5))
        long_window = int(parameters.get("long_window", 126))
        if component_count < 2 or short_window >= long_window:
            raise FeatureEngineError("F004_INVALID_HORIZONS")
        horizons = tuple(
            dict.fromkeys(
                int(round(value))
                for value in np.geomspace(short_window, long_window, component_count)
            )
        )
        if len(horizons) != component_count:
            raise FeatureEngineError("F004_NON_UNIQUE_HORIZONS")
        momentum = pd.concat(
            [close / close.shift(window) - 1.0 for window in horizons],
            axis=1,
        )
        aggregation = str(parameters.get("aggregation", "weighted_score"))
        if aggregation == "majority":
            value = np.sign(momentum).mean(axis=1, skipna=False)
        elif aggregation == "weighted_score":
            weights = np.arange(1.0, component_count + 1.0)
            value = momentum.mul(weights, axis=1).sum(axis=1, min_count=component_count) / float(
                weights.sum()
            )
        elif aggregation == "acceleration":
            horizon_x = np.log(np.asarray(horizons, dtype=float))
            centered = horizon_x - horizon_x.mean()
            denominator = float(np.dot(centered, centered))
            value = -momentum.apply(
                lambda row: float(np.dot(row.to_numpy() - row.mean(), centered) / denominator)
                if row.notna().all()
                else np.nan,
                axis=1,
            )
        else:
            raise FeatureEngineError(f"F004_UNKNOWN_AGGREGATION:{aggregation}")
    elif lane_id == "F005":
        window = int(parameters.get("window", 63))
        log_close = np.log(close)
        estimator = str(parameters.get("estimator", "ols"))
        if estimator == "ols":
            value = _rolling_slope(log_close, window)
        elif estimator == "theil_sen":
            lags = sorted({max(2, window // 4), max(2, window // 2), window - 1})
            value = pd.concat(
                [(log_close - log_close.shift(lag)) / lag for lag in lags],
                axis=1,
            ).median(axis=1, skipna=False)
        elif estimator == "kaufman_efficiency":
            net = log_close.diff(window)
            path = log_close.diff().abs().rolling(window, min_periods=window).sum()
            value = net / path.replace(0.0, np.nan)
        else:
            raise FeatureEngineError(f"F005_UNKNOWN_ESTIMATOR:{estimator}")
        minimum_r2 = float(parameters.get("minimum_r2", 0.0))
        if not 0.0 <= minimum_r2 <= 1.0:
            raise FeatureEngineError("F005_INVALID_MINIMUM_R2")
        value = value.where(_rolling_r2(log_close, window).ge(minimum_r2), 0.0)
    elif lane_id == "F006":
        window = int(parameters.get("window", 20))
        prior_high = spy["high"].shift(1).rolling(window, min_periods=window).max()
        prior_low = spy["low"].shift(1).rolling(window, min_periods=window).min()
        midpoint = (prior_high + prior_low) / 2.0
        prior_range = (prior_high - prior_low).replace(0.0, np.nan)
        atr = _true_range(spy).rolling(window, min_periods=window).mean().replace(0.0, np.nan)
        kind = str(parameters.get("kind", "donchian"))
        buffer = float(parameters.get("buffer", 0.0))
        if kind == "donchian":
            value = (close - midpoint) / prior_range
            value = _deadband(value, buffer * atr / prior_range)
        elif kind == "prior_extreme":
            upper = (close - prior_high) / atr
            lower = (close - prior_low) / atr
            value = upper.where(close >= midpoint, lower)
            value = _deadband(value, buffer)
        elif kind == "atr_channel":
            center = close.shift(1).rolling(window, min_periods=window).mean()
            value = _deadband((close - center) / atr, buffer)
        elif kind == "record_distance":
            upper_distance = (close - prior_high) / atr
            lower_distance = (close - prior_low) / atr
            value = upper_distance.where(
                upper_distance.abs() <= lower_distance.abs(), -lower_distance
            )
            value = _deadband(value, buffer)
        else:
            raise FeatureEngineError(f"F006_UNKNOWN_KIND:{kind}")
        value = _confirmed(value, int(parameters.get("confirmation", 1)))
    elif lane_id == "F007":
        window = int(parameters.get("window", 20))
        kind = str(parameters.get("kind", "bollinger"))
        width = float(parameters.get("width", 2.0))
        if width <= 0.0:
            raise FeatureEngineError("F007_INVALID_WIDTH")
        if kind == "bollinger":
            center = close.rolling(window, min_periods=window).mean()
            scale = close.rolling(window, min_periods=window).std(ddof=0)
        elif kind == "keltner":
            center = close.ewm(span=window, adjust=False, min_periods=window).mean()
            scale = _true_range(spy).rolling(window, min_periods=window).mean()
        elif kind == "ichimoku":
            half = max(2, window // 2)
            conversion = (
                spy["high"].rolling(half, min_periods=half).max()
                + spy["low"].rolling(half, min_periods=half).min()
            ) / 2.0
            base = (
                spy["high"].rolling(window, min_periods=window).max()
                + spy["low"].rolling(window, min_periods=window).min()
            ) / 2.0
            center = (conversion + base) / 2.0
            scale = _true_range(spy).rolling(window, min_periods=window).mean()
        else:
            raise FeatureEngineError(f"F007_UNKNOWN_KIND:{kind}")
        value = (close - center) / (width * scale.replace(0.0, np.nan))
        mode = str(parameters.get("mode", "breakout"))
        if mode == "reversal":
            value = -value
        elif mode != "breakout":
            raise FeatureEngineError(f"F007_UNKNOWN_MODE:{mode}")
    elif lane_id == "F008":
        window = int(parameters.get("window", 63))
        lag = int(parameters.get("lag", 1))
        statistic = str(parameters.get("statistic", "autocorrelation"))
        if statistic == "autocorrelation":
            value = returns.rolling(window, min_periods=window).corr(returns.shift(lag))
        elif statistic == "variance_ratio":
            lag_return = np.log(close).diff(lag)
            numerator = lag_return.rolling(window, min_periods=window).var(ddof=0)
            denominator = lag * np.log(close).diff().rolling(
                window, min_periods=window
            ).var(ddof=0)
            value = numerator / denominator.replace(0.0, np.nan) - 1.0
        elif statistic == "entropy":
            def entropy(row: np.ndarray) -> float:
                counts = np.histogram(row, bins=8)[0].astype(float)
                probabilities = counts[counts > 0.0] / counts.sum()
                return float(-np.sum(probabilities * np.log(probabilities)) / np.log(8.0) - 0.5)

            value = returns.rolling(window, min_periods=window).apply(entropy, raw=True)
        elif statistic == "lzc":
            signs = np.sign(returns)
            value = signs.ne(signs.shift(1)).astype(float).rolling(
                window, min_periods=window
            ).mean() - 0.5
        elif statistic == "matrix_profile":
            standardized = _rolling_z(returns, window)
            value = -(standardized - standardized.shift(lag)).abs()
        elif statistic == "recurrence":
            scale = returns.rolling(window, min_periods=window).std(ddof=0)
            difference = (returns - returns.shift(lag)).abs()
            value = difference.le(scale * 0.25).astype(float).rolling(
                window, min_periods=window
            ).mean() - 0.5
        else:
            raise FeatureEngineError(f"F008_UNKNOWN_STATISTIC:{statistic}")
    elif lane_id == "F009":
        window = int(parameters.get("window", 2))
        value = -(close / close.shift(window) - 1.0)
        value = _deadband(value, float(parameters.get("threshold", 0.0)))
        value = _confirmed(value, int(parameters.get("confirmation", 1)))
        value = _minimum_hold(value, int(parameters.get("hold", 1)))
    elif lane_id == "F010":
        window = int(parameters.get("window", 14))
        kind = str(parameters.get("kind", "rsi"))
        change = close.diff()
        gain = change.clip(lower=0.0).rolling(window, min_periods=window).mean()
        loss = (-change.clip(upper=0.0)).rolling(window, min_periods=window).mean()
        rs = gain / loss.replace(0.0, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        rsi = rsi.mask((loss == 0.0) & (gain > 0.0), 100.0)
        rsi = rsi.mask((loss == 0.0) & (gain == 0.0), 50.0)
        rolling_high = spy["high"].rolling(window, min_periods=window).max()
        rolling_low = spy["low"].rolling(window, min_periods=window).min()
        stochastic = 100.0 * (close - rolling_low) / (rolling_high - rolling_low).replace(
            0.0, np.nan
        )
        if kind == "rsi":
            oscillator = rsi
        elif kind == "stochastic":
            oscillator = stochastic
        elif kind == "williams_r":
            oscillator = stochastic
        elif kind == "cci":
            typical = (spy["high"] + spy["low"] + close) / 3.0
            center = typical.rolling(window, min_periods=window).mean()
            deviation = (typical - center).abs().rolling(window, min_periods=window).mean()
            cci = (typical - center) / (0.015 * deviation.replace(0.0, np.nan))
            oscillator = 50.0 + 50.0 * np.tanh(cci / 100.0)
        elif kind == "connors":
            streak = _signed_streak(returns)
            streak_rank = _rolling_percentile(streak, window) + 0.5
            return_rank = _rolling_percentile(returns, window) + 0.5
            oscillator = (rsi / 100.0 + streak_rank + return_rank) * (100.0 / 3.0)
        elif kind in {"adx", "dmi"}:
            plus_di, minus_di, adx = _directional_components(spy, window)
            spread = 50.0 + 50.0 * (plus_di - minus_di) / (
                plus_di + minus_di
            ).replace(0.0, np.nan)
            oscillator = (50.0 + np.sign(spread - 50.0) * adx / 2.0) if kind == "adx" else spread
        elif kind == "aroon":
            periods_since_high = spy["high"].rolling(window, min_periods=window).apply(
                lambda row: float(window - 1 - np.argmax(row)), raw=True
            )
            periods_since_low = spy["low"].rolling(window, min_periods=window).apply(
                lambda row: float(window - 1 - np.argmin(row)), raw=True
            )
            oscillator = 50.0 + 50.0 * (periods_since_low - periods_since_high) / window
        else:
            raise FeatureEngineError(f"F010_UNKNOWN_KIND:{kind}")
        lower = float(parameters.get("lower", 30.0))
        upper = float(parameters.get("upper", 70.0))
        if not 0.0 <= lower < upper <= 100.0:
            raise FeatureEngineError("F010_INVALID_BOUNDS")
        value = pd.Series(0.0, index=close.index)
        value = value.where(oscillator.ge(lower), (lower - oscillator) / max(lower, 1.0))
        value = value.where(oscillator.le(upper), -(oscillator - upper) / max(100.0 - upper, 1.0))
        value = value.where(oscillator.notna())
    elif lane_id == "F011":
        window = int(parameters.get("window", 63))
        value = _rolling_z(close, window)
        value = _normalize(value, str(parameters.get("normalization", "none")), window)
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F012":
        window = int(parameters.get("window", 63))
        value = _normalize(
            _signed_streak(returns),
            str(parameters.get("normalization", "none")),
            window,
        )
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F013":
        window = int(parameters.get("window", 63))
        overnight = spy["open"] / close.shift(1) - 1.0
        intraday = close / spy["open"] - 1.0
        value = _normalize(
            overnight - intraday,
            str(parameters.get("normalization", "none")),
            window,
        )
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F014":
        window = int(parameters.get("window", 63))
        bar_range = (spy["high"] - spy["low"]).replace(0.0, np.nan)
        value = _normalize(
            (2.0 * close - spy["high"] - spy["low"]) / bar_range,
            str(parameters.get("normalization", "none")),
            window,
        )
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F015":
        window = int(parameters.get("window", 20))
        kind = str(parameters.get("kind", "close"))
        log_hl = np.log(spy["high"] / spy["low"])
        log_co = np.log(close / spy["open"])
        if kind == "close":
            variance = returns.pow(2)
        elif kind == "parkinson":
            variance = log_hl.pow(2) / (4.0 * np.log(2.0))
        elif kind == "garman_klass":
            variance = 0.5 * log_hl.pow(2) - (2.0 * np.log(2.0) - 1.0) * log_co.pow(2)
        elif kind == "rogers_satchell":
            variance = np.log(spy["high"] / spy["open"]) * np.log(
                spy["high"] / close
            ) + np.log(spy["low"] / spy["open"]) * np.log(spy["low"] / close)
        elif kind == "yang_zhang":
            overnight = np.log(spy["open"] / close.shift(1))
            rogers = np.log(spy["high"] / spy["open"]) * np.log(
                spy["high"] / close
            ) + np.log(spy["low"] / spy["open"]) * np.log(spy["low"] / close)
            variance = overnight.pow(2) + 0.34 * log_co.pow(2) + 0.66 * rogers
        elif kind == "downside":
            variance = returns.clip(upper=0.0).pow(2)
        elif kind == "upside":
            variance = returns.clip(lower=0.0).pow(2)
        elif kind == "vol_of_vol":
            base = returns.rolling(max(5, window // 2), min_periods=max(5, window // 2)).std(
                ddof=0
            )
            variance = base.diff().pow(2)
        else:
            raise FeatureEngineError(f"F015_UNKNOWN_KIND:{kind}")
        realized = np.sqrt(
            variance.clip(lower=0.0).rolling(window, min_periods=window).mean() * 252.0
        )
        statistic = str(parameters.get("statistic", "level"))
        if statistic == "level":
            value = realized
        elif statistic == "change":
            previous = realized.shift(1).replace(0.0, np.nan)
            value = realized / previous - 1.0
        elif statistic == "spread":
            value = realized - realized.rolling(window, min_periods=window).mean()
        elif statistic == "percentile":
            value = _rolling_percentile(realized, window)
        else:
            raise FeatureEngineError(f"F015_UNKNOWN_STATISTIC:{statistic}")
    elif lane_id == "F016":
        window = int(parameters.get("window", 63))
        value = returns.rolling(window, min_periods=window).skew()
        value = _normalize(value, str(parameters.get("normalization", "none")), window)
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F017":
        window = int(parameters.get("window", 126))
        half = max(2, window // 2)
        long_vol = returns.rolling(window, min_periods=window).std(ddof=0)
        short_vol = returns.rolling(half, min_periods=half).std(ddof=0)
        value = 0.5 + np.log(long_vol / short_vol.replace(0.0, np.nan)) / np.log(2.0)
        value = _normalize(value, str(parameters.get("normalization", "none")), window)
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F018":
        window = int(parameters.get("window", 20))
        atr = _true_range(spy).rolling(window, min_periods=window).mean() / close
        value = atr.pct_change(fill_method=None)
        value = _normalize(value, str(parameters.get("normalization", "none")), window)
        value = _orient(value, str(parameters.get("direction", "continuation")))
    elif lane_id == "F019":
        direction = np.sign(close.diff()).fillna(0.0)
        obv = (direction * spy["volume"]).cumsum()
        window = int(parameters.get("window", 20))
        value = obv.diff(window) / spy["volume"].rolling(window, min_periods=window).sum()
        value = _normalize(value, str(parameters.get("normalization", "none")), window)
        value = _orient(value, str(parameters.get("direction", "continuation")))
    else:  # F020
        window = int(parameters.get("window", 20))
        dollar_volume = (close * spy["volume"]).replace(0.0, np.nan)
        amihud = returns.abs() / dollar_volume
        value = _normalize(
            -_rolling_z(amihud, window),
            str(parameters.get("normalization", "none")),
            window,
        )
        value = _orient(value, str(parameters.get("direction", "continuation")))
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
