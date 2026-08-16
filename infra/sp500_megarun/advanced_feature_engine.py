"""Causal advanced price and volatility kernels for SP500 lanes F061-F070."""

from __future__ import annotations

from math import factorial
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from numba import njit
from scipy.optimize import minimize
from scipy.special import expit, gammaln


class AdvancedFeatureEngineError(ValueError):
    """Raised when an advanced feature is invalid, non-causal or outside train."""


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
        raise AdvancedFeatureEngineError(f"SPY_COLUMNS_MISSING:{','.join(missing)}")
    spy = frame.loc[:, sorted(required)].copy()
    for column in ("date", "observed_at", "available_at"):
        spy[column] = (
            pd.to_datetime(spy[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if spy[["date", "observed_at", "available_at"]].isna().any().any():
        raise AdvancedFeatureEngineError("INVALID_SPY_DATE")
    if spy["date"].gt(_TRAIN_END).any() or spy["available_at"].gt(_TRAIN_END).any():
        raise AdvancedFeatureEngineError("NON_TRAIN_SPY_ROW")
    if spy["available_at"].gt(spy["date"]).any():
        raise AdvancedFeatureEngineError("SPY_NOT_AVAILABLE_AT_DECISION")
    if spy["observed_at"].gt(spy["available_at"]).any():
        raise AdvancedFeatureEngineError("SPY_OBSERVED_AFTER_AVAILABILITY")
    if spy["date"].duplicated().any() or not spy["date"].is_monotonic_increasing:
        raise AdvancedFeatureEngineError("SPY_DATES_NOT_ORDERED")
    for column in ("open", "high", "low", "close", "volume"):
        spy[column] = pd.to_numeric(spy[column], errors="coerce")
    if spy[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise AdvancedFeatureEngineError("INVALID_SPY_VALUE")
    if spy[["open", "high", "low", "close"]].le(0.0).any().any():
        raise AdvancedFeatureEngineError("NON_POSITIVE_SPY_PRICE")
    if spy["volume"].lt(0.0).any():
        raise AdvancedFeatureEngineError("NEGATIVE_SPY_VOLUME")
    if spy["high"].lt(spy[["open", "close"]].max(axis=1)).any():
        raise AdvancedFeatureEngineError("SPY_HIGH_BELOW_BODY")
    if spy["low"].gt(spy[["open", "close"]].min(axis=1)).any():
        raise AdvancedFeatureEngineError("SPY_LOW_ABOVE_BODY")
    return spy.reset_index(drop=True)


def _output(spy: pd.DataFrame, value: pd.Series | np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": spy["date"],
            "observed_at": spy["observed_at"],
            "available_at": spy["available_at"],
            "value": pd.to_numeric(pd.Series(value, index=spy.index), errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise AdvancedFeatureEngineError(f"INVALID_POSITIVE_PARAMETER:{name}:{value}")
    return value


def _refit_due(dates: pd.Series, index: int, cadence: str, has_model: bool) -> bool:
    if not has_model:
        return True
    current = pd.Timestamp(dates.iloc[index])
    previous = pd.Timestamp(dates.iloc[index - 1])
    if cadence == "weekly":
        return current.to_period("W") != previous.to_period("W")
    if cadence == "monthly":
        return current.to_period("M") != previous.to_period("M")
    if cadence == "quarterly":
        return current.to_period("Q") != previous.to_period("Q")
    raise AdvancedFeatureEngineError(f"UNKNOWN_REFIT_CADENCE:{cadence}")


def _adaptive_average(close: pd.Series, *, kind: str, window: int) -> pd.Series:
    prices = close.to_numpy(dtype=float)
    result = np.full(len(prices), np.nan, dtype=float)
    if len(prices) <= window:
        return pd.Series(result, index=close.index)
    result[window] = prices[window]
    fast = 2.0 / 3.0
    slow = 2.0 / 31.0
    for index in range(window + 1, len(prices)):
        segment = prices[index - window : index + 1]
        changes = np.diff(segment)
        if kind == "kama":
            denominator = float(np.abs(changes).sum())
            efficiency = abs(float(segment[-1] - segment[0])) / max(
                denominator, _EPSILON
            )
            alpha = (efficiency * (fast - slow) + slow) ** 2
        elif kind == "vidya":
            upward = float(np.clip(changes, 0.0, None).sum())
            downward = float(np.clip(-changes, 0.0, None).sum())
            cmo = abs(upward - downward) / max(upward + downward, _EPSILON)
            alpha = (2.0 / (window + 1.0)) * cmo
        elif kind == "frama":
            half = window // 2
            first = segment[-2 * half : -half]
            second = segment[-half:]
            full = segment[-2 * half :]
            n1 = (float(first.max()) - float(first.min())) / half
            n2 = (float(second.max()) - float(second.min())) / half
            n3 = (float(full.max()) - float(full.min())) / (2.0 * half)
            if min(n1 + n2, n3) <= _EPSILON:
                dimension = 1.0
            else:
                dimension = (np.log(n1 + n2) - np.log(n3)) / np.log(2.0)
            alpha = float(np.clip(np.exp(-4.6 * (dimension - 1.0)), 0.01, 1.0))
        else:
            raise AdvancedFeatureEngineError(f"F061_UNKNOWN_KIND:{kind}")
        result[index] = result[index - 1] + alpha * (prices[index] - result[index - 1])
    return pd.Series(result, index=close.index)


def _f061(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    kind = str(parameters.get("kind", "kama"))
    average = _adaptive_average(spy["close"], kind=kind, window=window)
    log_return = np.log(spy["close"]).diff()
    scale = log_return.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    raw = np.log(spy["close"] / average) / scale
    threshold = float(parameters.get("threshold", 0.0))
    if threshold < 0.0:
        raise AdvancedFeatureEngineError("F061_NEGATIVE_THRESHOLD")
    return np.sign(raw) * (raw.abs() - threshold).clip(lower=0.0)


def _polynomial_transition(states: int) -> np.ndarray:
    transition = np.zeros((states, states), dtype=float)
    for row in range(states):
        for column in range(row, states):
            transition[row, column] = 1.0 / factorial(column - row)
    return transition


def _kalman_score(segment: np.ndarray, *, kind: str, noise_ratio: float) -> float:
    state_count = {"local_level": 1, "local_trend": 2, "kalman_slope": 3}.get(kind)
    if state_count is None:
        raise AdvancedFeatureEngineError(f"F062_UNKNOWN_KIND:{kind}")
    transition = _polynomial_transition(state_count)
    observation = np.zeros((1, state_count), dtype=float)
    observation[0, 0] = 1.0
    measurement_variance = max(float(np.var(np.diff(segment), ddof=0)), _EPSILON)
    decay = np.power(0.1, np.arange(state_count, dtype=float))
    process_covariance = np.diag(measurement_variance * noise_ratio * decay)
    state = np.zeros(state_count, dtype=float)
    state[0] = float(segment[0])
    covariance = np.eye(state_count, dtype=float) * measurement_variance * 100.0
    levels: list[float] = []
    identity = np.eye(state_count, dtype=float)
    for value in segment:
        predicted_state = transition @ state
        predicted_covariance = transition @ covariance @ transition.T + process_covariance
        innovation_variance = float(
            (observation @ predicted_covariance @ observation.T)[0, 0]
            + measurement_variance
        )
        gain = (predicted_covariance @ observation.T)[:, 0] / innovation_variance
        innovation = float(value - (observation @ predicted_state)[0])
        state = predicted_state + gain * innovation
        covariance = (identity - np.outer(gain, observation[0])) @ predicted_covariance
        levels.append(float(state[0]))
    scale = np.sqrt(measurement_variance)
    if kind == "local_level":
        score = levels[-1] - levels[-2]
    elif kind == "local_trend":
        score = state[1]
    else:
        score = state[1] + 0.5 * state[2]
    return float(np.clip(score / scale, -10.0, 10.0))


def _f062(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 504)
    noise_ratio = float(parameters.get("noise_ratio", 0.01))
    if not 0.0 < noise_ratio <= 1.0:
        raise AdvancedFeatureEngineError("F062_INVALID_NOISE_RATIO")
    kind = str(parameters.get("kind", "local_trend"))
    log_close = np.log(spy["close"]).to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    for index in range(window, len(spy)):
        result[index] = _kalman_score(
            log_close[index - window : index + 1],
            kind=kind,
            noise_ratio=noise_ratio,
        )
    return pd.Series(result, index=spy.index)


_WAVELET_FILTERS: Mapping[str, tuple[np.ndarray, np.ndarray]] = {
    "haar": (
        np.array([0.7071067811865476, 0.7071067811865476]),
        np.array([0.7071067811865476, -0.7071067811865476]),
    ),
    "db2": (
        np.array(
            [
                0.4829629131445341,
                0.8365163037378079,
                0.2241438680420134,
                -0.1294095225512604,
            ]
        ),
        np.array(
            [
                -0.1294095225512604,
                -0.2241438680420134,
                0.8365163037378079,
                -0.4829629131445341,
            ]
        ),
    ),
    "db4": (
        np.array(
            [
                0.2303778133088964,
                0.7148465705529154,
                0.6308807679298587,
                -0.0279837694168599,
                -0.1870348117188811,
                0.0308413818355607,
                0.0328830116668852,
                -0.0105974017850690,
            ]
        ),
        np.array(
            [
                -0.0105974017850690,
                -0.0328830116668852,
                0.0308413818355607,
                0.1870348117188811,
                -0.0279837694168599,
                -0.6308807679298587,
                0.7148465705529154,
                -0.2303778133088964,
            ]
        ),
    ),
}


def _causal_filter(values: np.ndarray, coefficients: np.ndarray, dilation: int) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=float)
    required = (len(coefficients) - 1) * dilation
    for index in range(required, len(values)):
        positions = index - np.arange(len(coefficients)) * dilation
        sample = values[positions]
        if np.isfinite(sample).all():
            result[index] = float(np.dot(coefficients, sample))
    return result


def _causal_wavelet_details(
    returns: np.ndarray,
    *,
    kind: str,
    scales: int,
) -> tuple[list[np.ndarray], np.ndarray]:
    if kind == "causal_modwt":
        details: list[np.ndarray] = []
        for scale in range(1, scales + 1):
            half = 2 ** (scale - 1)
            detail = np.full(len(returns), np.nan, dtype=float)
            for index in range(2 * half - 1, len(returns)):
                recent = returns[index - half + 1 : index + 1]
                prior = returns[index - 2 * half + 1 : index - half + 1]
                if np.isfinite(recent).all() and np.isfinite(prior).all():
                    detail[index] = float((recent.sum() - prior.sum()) / np.sqrt(2 * half))
            details.append(detail)
        approximation = (
            pd.Series(returns)
            .rolling(2**scales, min_periods=2**scales)
            .mean()
            .to_numpy()
        )
        return details, approximation
    if kind not in _WAVELET_FILTERS:
        raise AdvancedFeatureEngineError(f"F063_UNKNOWN_KIND:{kind}")
    low, high = _WAVELET_FILTERS[kind]
    approximation = returns.copy()
    details = []
    for scale in range(1, scales + 1):
        dilation = 2 ** (scale - 1)
        details.append(_causal_filter(approximation, high / np.sqrt(2.0), dilation))
        approximation = _causal_filter(approximation, low / np.sqrt(2.0), dilation)
    return details, approximation


def _rolling_slope(values: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    centered = x - x.mean()
    denominator = float(np.dot(centered, centered))
    return values.rolling(window, min_periods=window).apply(
        lambda row: float(np.dot(row - row.mean(), centered) / denominator),
        raw=True,
    )


def _f063(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 252)
    scales = _positive_int(parameters, "scales", 3)
    if scales > 5:
        raise AdvancedFeatureEngineError("F063_TOO_MANY_SCALES")
    kind = str(parameters.get("kind", "haar"))
    statistic = str(parameters.get("statistic", "sign"))
    returns = np.log(spy["close"]).diff().to_numpy(dtype=float)
    details, approximation = _causal_wavelet_details(returns, kind=kind, scales=scales)
    detail_frame = pd.DataFrame(np.column_stack(details), index=spy.index)
    energy = detail_frame.pow(2).rolling(window, min_periods=window).mean()
    reconstruction = detail_frame.sum(axis=1, min_count=scales)
    if statistic == "energy":
        base = pd.Series(returns, index=spy.index).pow(2).rolling(
            window, min_periods=window
        ).mean()
        magnitude = np.sqrt(energy.sum(axis=1, min_count=scales) / base.replace(0.0, np.nan))
        value = np.sign(reconstruction) * magnitude
    elif statistic == "sign":
        numerator = (np.sign(detail_frame) * energy).sum(axis=1, min_count=scales)
        value = numerator / energy.sum(axis=1, min_count=scales).replace(0.0, np.nan)
    elif statistic == "slope":
        value = _rolling_slope(pd.Series(approximation, index=spy.index), window)
        scale = pd.Series(returns, index=spy.index).rolling(
            window, min_periods=window
        ).std(ddof=0)
        value = value / scale.replace(0.0, np.nan)
    elif statistic == "reconstruction":
        scale = pd.Series(returns, index=spy.index).rolling(
            window, min_periods=window
        ).std(ddof=0)
        value = reconstruction / scale.replace(0.0, np.nan)
    else:
        raise AdvancedFeatureEngineError(f"F063_UNKNOWN_STATISTIC:{statistic}")
    return pd.Series(value, index=spy.index).clip(-20.0, 20.0)


def _goertzel_coefficient(values: np.ndarray, omega: float) -> complex:
    cosine = float(np.cos(omega))
    sine = float(np.sin(omega))
    prior = 0.0
    prior_two = 0.0
    for value in values:
        current = float(value) + 2.0 * cosine * prior - prior_two
        prior_two = prior
        prior = current
    return complex(prior - prior_two * cosine, prior_two * sine)


def _detrended(values: np.ndarray, kind: str) -> np.ndarray:
    if kind == "mean":
        return values - float(values.mean())
    if kind == "linear":
        x = np.arange(len(values), dtype=float)
        design = np.column_stack([np.ones(len(values)), x])
        fitted = design @ np.linalg.lstsq(design, values, rcond=None)[0]
        return values - fitted
    raise AdvancedFeatureEngineError(f"F064_UNKNOWN_DETREND:{kind}")


def _f064(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 252)
    period = _positive_int(parameters, "period", 20)
    if period < 3 or window < 2 * period:
        raise AdvancedFeatureEngineError("F064_WINDOW_REQUIRES_TWO_CYCLES")
    threshold = float(parameters.get("phase_stability", 0.25))
    if not 0.0 <= threshold <= 1.0:
        raise AdvancedFeatureEngineError("F064_INVALID_PHASE_STABILITY")
    detrend = str(parameters.get("detrend", "mean"))
    omega = 2.0 * np.pi / period
    returns = np.log(spy["close"]).diff().to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    for index in range(window, len(spy)):
        segment = returns[index - window + 1 : index + 1]
        if len(segment) != window or not np.isfinite(segment).all():
            continue
        centered = _detrended(segment, detrend)
        coefficient = _goertzel_coefficient(centered, omega)
        forecast = 2.0 / window * float(
            np.real(coefficient * np.exp(1j * omega * window))
        )
        phases: list[complex] = []
        for indexes in np.array_split(np.arange(window), 3):
            block = _detrended(segment[indexes], detrend)
            block_coefficient = _goertzel_coefficient(block, omega)
            absolute_coefficient = block_coefficient * np.exp(-1j * omega * indexes[0])
            if abs(absolute_coefficient) > _EPSILON:
                phases.append(absolute_coefficient / abs(absolute_coefficient))
        coherence = abs(sum(phases) / len(phases)) if len(phases) == 3 else 0.0
        scale = max(float(np.std(segment, ddof=0)), _EPSILON)
        result[index] = 0.0 if coherence < threshold else forecast / scale * coherence
    return pd.Series(result, index=spy.index).clip(-20.0, 20.0)


def _binary_entropy(symbols: np.ndarray) -> float:
    probabilities = np.bincount(symbols.astype(int), minlength=2).astype(float)
    probabilities /= probabilities.sum()
    positive = probabilities[probabilities > 0.0]
    return float(-(positive * np.log2(positive)).sum())


def _lempel_ziv_complexity(symbols: np.ndarray) -> float:
    text = "".join("1" if value else "0" for value in symbols)
    dictionary: set[str] = set()
    index = 0
    phrases = 0
    while index < len(text):
        end = index + 1
        while end <= len(text) and text[index:end] in dictionary:
            end += 1
        dictionary.add(text[index:min(end, len(text))])
        phrases += 1
        index = end
    if len(text) <= 1:
        return 0.0
    return float(np.clip(phrases * np.log2(len(text)) / len(text), 0.0, 1.0))


def _f065(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    lag = _positive_int(parameters, "lag", 1)
    statistic = str(parameters.get("statistic", "binary_entropy"))
    direction = str(parameters.get("direction", "continuation"))
    if direction not in {"continuation", "reversal"}:
        raise AdvancedFeatureEngineError(f"F065_UNKNOWN_DIRECTION:{direction}")
    returns = np.log(spy["close"]).diff().to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    for index in range(window, len(spy)):
        segment = returns[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        symbols = (segment[::-lag][::-1] >= 0.0).astype(int)
        if statistic == "binary_entropy":
            complexity = _binary_entropy(symbols)
        elif statistic == "lempel_ziv":
            complexity = _lempel_ziv_complexity(symbols)
        else:
            raise AdvancedFeatureEngineError(f"F065_UNKNOWN_STATISTIC:{statistic}")
        orientation = float(np.sign(segment[-lag:].sum()))
        if direction == "reversal":
            orientation *= -1.0
        result[index] = orientation * (1.0 - complexity)
    return pd.Series(result, index=spy.index)


def _f066(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 252)
    order = _positive_int(parameters, "order", 3)
    smoothing = float(parameters.get("smoothing", 0.5))
    if smoothing <= 0.0 or order >= window:
        raise AdvancedFeatureEngineError("F066_INVALID_ORDINAL_PARAMETERS")
    returns = np.log(spy["close"]).diff().to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    for index in range(window, len(spy)):
        segment = returns[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        signs = np.where(segment >= 0.0, 1, -1)
        context = tuple(signs[-order:])
        negative = smoothing
        positive = smoothing
        for target_index in range(order, len(signs)):
            if tuple(signs[target_index - order : target_index]) != context:
                continue
            if signs[target_index] > 0:
                positive += 1.0
            else:
                negative += 1.0
        result[index] = (positive - negative) / (positive + negative)
    return pd.Series(result, index=spy.index)


def _f067(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 252)
    order = _positive_int(parameters, "order", 3)
    bins = _positive_int(parameters, "bins", 5)
    smoothing = float(parameters.get("smoothing", 0.5))
    if smoothing <= 0.0 or bins < 2 or order >= window:
        raise AdvancedFeatureEngineError("F067_INVALID_ORDINAL_PARAMETERS")
    returns = np.log(spy["close"]).diff().to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    scores = np.linspace(-1.0, 1.0, bins)
    for index in range(window, len(spy)):
        segment = returns[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        thresholds = np.quantile(segment, np.arange(1, bins, dtype=float) / bins)
        states = np.searchsorted(thresholds, segment, side="right")
        context = tuple(states[-order:])
        counts = np.full(bins, smoothing, dtype=float)
        for target_index in range(order, len(states)):
            if tuple(states[target_index - order : target_index]) == context:
                counts[states[target_index]] += 1.0
        result[index] = float(np.dot(counts / counts.sum(), scores))
    return pd.Series(result, index=spy.index)


def _arma_residuals(values: np.ndarray, coefficients: np.ndarray, p: int, q: int) -> np.ndarray:
    residuals = np.zeros(len(values), dtype=float)
    start = max(p, q)
    for index in range(start, len(values)):
        forecast = float(coefficients[0])
        forecast += sum(coefficients[lag] * values[index - lag] for lag in range(1, p + 1))
        forecast += sum(
            coefficients[p + lag] * residuals[index - lag] for lag in range(1, q + 1)
        )
        residuals[index] = values[index] - forecast
    return residuals


def _project_arma_coefficients(
    coefficients: np.ndarray,
    values: np.ndarray,
    p: int,
    q: int,
) -> np.ndarray:
    projected = np.asarray(coefficients, dtype=float).copy()
    scale = max(float(np.std(values, ddof=0)), _EPSILON)
    projected[0] = float(np.clip(projected[0], -5.0 * scale, 5.0 * scale))
    for start, count in ((1, p), (1 + p, q)):
        if count == 0:
            continue
        block = projected[start : start + count]
        absolute_sum = float(np.abs(block).sum())
        if absolute_sum > 0.98:
            projected[start : start + count] = block * (0.98 / absolute_sum)
    return projected


def _fit_arma(values: np.ndarray, p: int, q: int) -> np.ndarray:
    residuals = np.zeros(len(values), dtype=float)
    coefficients = np.zeros(1 + p + q, dtype=float)
    coefficients[0] = float(values.mean())
    start = max(p, q)
    for _ in range(6):
        rows: list[list[float]] = []
        targets: list[float] = []
        for index in range(start, len(values)):
            rows.append(
                [1.0]
                + [float(values[index - lag]) for lag in range(1, p + 1)]
                + [float(residuals[index - lag]) for lag in range(1, q + 1)]
            )
            targets.append(float(values[index]))
        design = np.asarray(rows, dtype=float)
        target = np.asarray(targets, dtype=float)
        penalty = np.eye(design.shape[1], dtype=float) * 1e-8
        penalty[0, 0] = 0.0
        augmented_design = np.vstack([design, np.sqrt(penalty)])
        augmented_target = np.concatenate([target, np.zeros(design.shape[1])])
        coefficients = np.linalg.lstsq(
            augmented_design,
            augmented_target,
            rcond=None,
        )[0]
        coefficients = _project_arma_coefficients(coefficients, values, p, q)
        residuals = _arma_residuals(values, coefficients, p, q)
    return coefficients


def _arma_forecast(values: np.ndarray, coefficients: np.ndarray, p: int, q: int) -> float:
    residuals = _arma_residuals(values, coefficients, p, q)
    forecast = float(coefficients[0])
    forecast += sum(coefficients[lag] * values[-lag] for lag in range(1, p + 1))
    forecast += sum(
        coefficients[p + lag] * residuals[-lag] for lag in range(1, q + 1)
    )
    scale = max(float(np.std(values, ddof=0)), _EPSILON)
    return float(np.clip(forecast, -5.0 * scale, 5.0 * scale))


def _f068(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    p = _positive_int(parameters, "p", 1)
    q = int(parameters.get("q", 0))
    window = _positive_int(parameters, "window", 504)
    cadence = str(parameters.get("refit", "monthly"))
    if q < 0 or max(p, q) * 5 >= window:
        raise AdvancedFeatureEngineError("F068_INVALID_ARMA_ORDER")
    returns = (100.0 * np.log(spy["close"]).diff()).to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    model: np.ndarray | None = None
    for index in range(window, len(spy)):
        segment = returns[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        if _refit_due(spy["date"], index, cadence, model is not None):
            model = _fit_arma(segment, p, q)
        if model is not None:
            result[index] = _arma_forecast(segment, model, p, q) / 100.0
    return pd.Series(result, index=spy.index)


def _student_expected_absolute(df: float) -> float:
    return float(
        2.0
        * np.sqrt(df - 2.0)
        * np.exp(gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0))
        / (np.sqrt(np.pi) * (df - 1.0))
    )


def _decode_volatility_parameters(
    theta: np.ndarray,
    *,
    kind: str,
    p: int,
    q: int,
    variance: float,
) -> dict[str, Any]:
    if kind in {"garch", "gjr"}:
        shock_terms = p if kind == "garch" else 2 * p
        persistence = 0.995 * float(expit(theta[0]))
        raw = np.exp(np.clip(theta[1 : 1 + shock_terms + q], -20.0, 20.0))
        effective = persistence * raw / raw.sum()
        alpha = effective[:p]
        if kind == "gjr":
            gamma = 2.0 * effective[p : 2 * p]
            beta = effective[2 * p :]
        else:
            gamma = np.zeros(p, dtype=float)
            beta = effective[p:]
        return {
            "kind": kind,
            "omega": max(variance * (1.0 - persistence), _EPSILON),
            "alpha": alpha,
            "gamma": gamma,
            "beta": beta,
        }
    if kind == "egarch":
        beta_total = 0.995 * float(expit(theta[0]))
        beta_raw = np.exp(np.clip(theta[1 : 1 + q], -20.0, 20.0))
        beta = beta_total * beta_raw / beta_raw.sum()
        alpha_start = 1 + q
        alpha = 0.75 * expit(theta[alpha_start : alpha_start + p])
        gamma = 0.75 * np.tanh(theta[alpha_start + p : alpha_start + 2 * p])
        return {
            "kind": kind,
            "omega": float(np.log(max(variance, _EPSILON)) * (1.0 - beta.sum())),
            "alpha": alpha,
            "gamma": gamma,
            "beta": beta,
        }
    raise AdvancedFeatureEngineError(f"F069_UNKNOWN_KIND:{kind}")


def _variance_path_python(
    residuals: np.ndarray,
    model: Mapping[str, Any],
    *,
    expected_absolute: float,
) -> np.ndarray:
    variance = max(float(np.var(residuals, ddof=0)), _EPSILON)
    path = np.full(len(residuals), variance, dtype=float)
    alpha = np.asarray(model["alpha"], dtype=float)
    gamma = np.asarray(model["gamma"], dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    start = max(len(alpha), len(beta))
    if model["kind"] == "egarch":
        log_path = np.full(len(residuals), np.log(variance), dtype=float)
        for index in range(start, len(residuals)):
            value = float(model["omega"])
            for lag, coefficient in enumerate(alpha, start=1):
                standardized = residuals[index - lag] / np.sqrt(
                    max(np.exp(log_path[index - lag]), _EPSILON)
                )
                value += coefficient * (abs(standardized) - expected_absolute)
                value += gamma[lag - 1] * standardized
            value += sum(
                coefficient * log_path[index - lag]
                for lag, coefficient in enumerate(beta, start=1)
            )
            log_path[index] = float(np.clip(value, -30.0, 30.0))
        return np.exp(log_path)
    for index in range(start, len(residuals)):
        value = float(model["omega"])
        for lag, coefficient in enumerate(alpha, start=1):
            shock = residuals[index - lag] ** 2
            value += coefficient * shock
            if residuals[index - lag] < 0.0:
                value += gamma[lag - 1] * shock
        value += sum(
            coefficient * path[index - lag]
            for lag, coefficient in enumerate(beta, start=1)
        )
        path[index] = max(value, _EPSILON)
    return path


@njit(cache=True)
def _variance_path_compiled(
    residuals: np.ndarray,
    *,
    variance: float,
    omega: float,
    alpha: np.ndarray,
    gamma: np.ndarray,
    beta: np.ndarray,
    kind_code: int,
    expected_absolute: float,
) -> np.ndarray:
    path = np.full(len(residuals), variance, dtype=np.float64)
    start = max(len(alpha), len(beta))
    if kind_code == 2:
        log_path = np.full(len(residuals), np.log(variance), dtype=np.float64)
        for index in range(start, len(residuals)):
            value = omega
            for offset in range(len(alpha)):
                lag = offset + 1
                lag_variance = max(np.exp(log_path[index - lag]), _EPSILON)
                standardized = residuals[index - lag] / np.sqrt(lag_variance)
                value += alpha[offset] * (abs(standardized) - expected_absolute)
                value += gamma[offset] * standardized
            beta_total = 0.0
            for offset in range(len(beta)):
                lag = offset + 1
                beta_total += beta[offset] * log_path[index - lag]
            value += beta_total
            log_path[index] = min(max(value, -30.0), 30.0)
        return np.exp(log_path)
    for index in range(start, len(residuals)):
        value = omega
        for offset in range(len(alpha)):
            lag = offset + 1
            shock = residuals[index - lag] ** 2
            value += alpha[offset] * shock
            if residuals[index - lag] < 0.0:
                value += gamma[offset] * shock
        beta_total = 0.0
        for offset in range(len(beta)):
            lag = offset + 1
            beta_total += beta[offset] * path[index - lag]
        value += beta_total
        path[index] = max(value, _EPSILON)
    return path


def _variance_path(
    residuals: np.ndarray,
    model: Mapping[str, Any],
    *,
    expected_absolute: float,
) -> np.ndarray:
    variance = max(float(np.var(residuals, ddof=0)), _EPSILON)
    kind = str(model["kind"])
    kind_code = 2 if kind == "egarch" else (1 if kind == "gjr" else 0)
    return _variance_path_compiled(
        np.asarray(residuals, dtype=np.float64),
        variance=variance,
        omega=float(model["omega"]),
        alpha=np.asarray(model["alpha"], dtype=np.float64),
        gamma=np.asarray(model["gamma"], dtype=np.float64),
        beta=np.asarray(model["beta"], dtype=np.float64),
        kind_code=kind_code,
        expected_absolute=float(expected_absolute),
    )


def _volatility_nll(
    theta: np.ndarray,
    residuals: np.ndarray,
    *,
    kind: str,
    p: int,
    q: int,
    distribution: str,
    student_df: float,
) -> float:
    variance = max(float(np.var(residuals, ddof=0)), _EPSILON)
    model = _decode_volatility_parameters(
        theta, kind=kind, p=p, q=q, variance=variance
    )
    expected_absolute = (
        np.sqrt(2.0 / np.pi)
        if distribution == "normal"
        else _student_expected_absolute(student_df)
    )
    path = _variance_path(residuals, model, expected_absolute=expected_absolute)
    start = max(p, q)
    values = residuals[start:]
    conditional = path[start:]
    if distribution == "normal":
        terms = 0.5 * (
            np.log(2.0 * np.pi) + np.log(conditional) + values**2 / conditional
        )
        return float(np.sum(terms))
    constant = (
        gammaln((student_df + 1.0) / 2.0)
        - gammaln(student_df / 2.0)
        - 0.5 * np.log((student_df - 2.0) * np.pi)
    )
    log_density = (
        constant
        - 0.5 * np.log(conditional)
        - (student_df + 1.0)
        / 2.0
        * np.log1p(values**2 / (conditional * (student_df - 2.0)))
    )
    return float(-np.sum(log_density))


def _fit_volatility(
    residuals: np.ndarray,
    *,
    kind: str,
    p: int,
    q: int,
    distribution: str,
    student_df: float,
) -> dict[str, Any]:
    parameter_count = 1 + (p + q if kind == "garch" else 2 * p + q)
    initial = np.zeros(parameter_count, dtype=float)

    def objective(theta: np.ndarray) -> float:
        return _volatility_nll(
            theta,
            residuals,
            kind=kind,
            p=p,
            q=q,
            distribution=distribution,
            student_df=student_df,
        )

    fitted = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        bounds=[(-6.0, 6.0)] * parameter_count,
        options={"maxiter": 40, "ftol": 1e-8},
    )
    return _decode_volatility_parameters(
        np.asarray(fitted.x, dtype=float),
        kind=kind,
        p=p,
        q=q,
        variance=max(float(np.var(residuals, ddof=0)), _EPSILON),
    )


def _next_variance(
    residuals: np.ndarray,
    model: Mapping[str, Any],
    *,
    expected_absolute: float,
) -> float:
    path = _variance_path(residuals, model, expected_absolute=expected_absolute)
    alpha = np.asarray(model["alpha"], dtype=float)
    gamma = np.asarray(model["gamma"], dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    if model["kind"] == "egarch":
        value = float(model["omega"])
        for lag, coefficient in enumerate(alpha, start=1):
            standardized = residuals[-lag] / np.sqrt(max(path[-lag], _EPSILON))
            value += coefficient * (abs(standardized) - expected_absolute)
            value += gamma[lag - 1] * standardized
        value += sum(
            coefficient * np.log(max(path[-lag], _EPSILON))
            for lag, coefficient in enumerate(beta, start=1)
        )
        return float(np.exp(np.clip(value, -30.0, 30.0)))
    value = float(model["omega"])
    for lag, coefficient in enumerate(alpha, start=1):
        shock = residuals[-lag] ** 2
        value += coefficient * shock
        if residuals[-lag] < 0.0:
            value += gamma[lag - 1] * shock
    value += sum(coefficient * path[-lag] for lag, coefficient in enumerate(beta, start=1))
    return max(float(value), _EPSILON)


def _f069(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    kind = str(parameters.get("kind", "garch"))
    p = _positive_int(parameters, "p", 1)
    q = _positive_int(parameters, "q", 1)
    window = _positive_int(parameters, "window", 756)
    distribution = str(parameters.get("distribution", "normal"))
    if distribution not in {"normal", "student_t"}:
        raise AdvancedFeatureEngineError(f"F069_UNKNOWN_DISTRIBUTION:{distribution}")
    student_df = float(parameters.get("student_df", 8))
    if distribution == "student_t" and student_df <= 2.0:
        raise AdvancedFeatureEngineError("F069_STUDENT_DF_NOT_ABOVE_TWO")
    cadence = str(parameters.get("refit", "quarterly"))
    returns = (100.0 * np.log(spy["close"]).diff()).to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    model: dict[str, Any] | None = None
    expected_absolute = (
        np.sqrt(2.0 / np.pi)
        if distribution == "normal"
        else _student_expected_absolute(student_df)
    )
    for index in range(window, len(spy)):
        segment = returns[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        residuals = segment - float(segment.mean())
        if _refit_due(spy["date"], index, cadence, model is not None):
            model = _fit_volatility(
                residuals,
                kind=kind,
                p=p,
                q=q,
                distribution=distribution,
                student_df=student_df,
            )
        if model is not None:
            forecast = _next_variance(
                residuals, model, expected_absolute=expected_absolute
            )
            baseline = max(float(np.mean(residuals**2)), _EPSILON)
            result[index] = float(np.log(forecast / baseline))
    return pd.Series(result, index=spy.index).clip(-20.0, 20.0)


def _daily_variance(spy: pd.DataFrame, estimator: str) -> pd.Series:
    log_high_low = np.log(spy["high"] / spy["low"])
    log_close_open = np.log(spy["close"] / spy["open"])
    if estimator == "close":
        return np.log(spy["close"]).diff().pow(2)
    if estimator == "parkinson":
        return log_high_low.pow(2) / (4.0 * np.log(2.0))
    if estimator == "garman_klass":
        return (
            0.5 * log_high_low.pow(2)
            - (2.0 * np.log(2.0) - 1.0) * log_close_open.pow(2)
        ).clip(lower=_EPSILON)
    if estimator == "rogers_satchell":
        return (
            np.log(spy["high"] / spy["open"])
            * np.log(spy["high"] / spy["close"])
            + np.log(spy["low"] / spy["open"])
            * np.log(spy["low"] / spy["close"])
        ).clip(lower=_EPSILON)
    raise AdvancedFeatureEngineError(f"F070_UNKNOWN_ESTIMATOR:{estimator}")


def _har_horizons(name: str) -> tuple[int, ...]:
    mapping = {"1_5_22": (1, 5, 22), "1_5_22_63": (1, 5, 22, 63)}
    try:
        return mapping[name]
    except KeyError as exc:
        raise AdvancedFeatureEngineError(f"F070_UNKNOWN_HORIZONS:{name}") from exc


def _har_state(
    variance: np.ndarray,
    index: int,
    horizons: Sequence[int],
    transform: str,
) -> np.ndarray | None:
    values: list[float] = []
    for horizon in horizons:
        if index - horizon + 1 < 0:
            return None
        component = variance[index - horizon + 1 : index + 1]
        if not np.isfinite(component).all():
            return None
        mean = max(float(component.mean()), _EPSILON)
        values.append(np.log(mean) if transform == "log" else mean)
    return np.asarray(values, dtype=float)


def _f070(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    estimator = str(parameters.get("estimator", "close"))
    horizons = _har_horizons(str(parameters.get("horizons", "1_5_22")))
    window = _positive_int(parameters, "window", 504)
    cadence = str(parameters.get("refit", "quarterly"))
    transform = str(parameters.get("transform", "log"))
    if transform not in {"level", "log"}:
        raise AdvancedFeatureEngineError(f"F070_UNKNOWN_TRANSFORM:{transform}")
    variance = _daily_variance(spy, estimator).to_numpy(dtype=float)
    result = np.full(len(spy), np.nan, dtype=float)
    model: np.ndarray | None = None
    maximum_horizon = max(horizons)
    for index in range(window, len(spy)):
        if _refit_due(spy["date"], index, cadence, model is not None):
            rows: list[np.ndarray] = []
            targets: list[float] = []
            first = max(maximum_horizon - 1, index - window)
            for feature_index in range(first, index):
                state = _har_state(variance, feature_index, horizons, transform)
                target = variance[feature_index + 1]
                if state is None or not np.isfinite(target):
                    continue
                rows.append(state)
                targets.append(
                    np.log(max(float(target), _EPSILON))
                    if transform == "log"
                    else float(target)
                )
            if len(rows) == window:
                design = np.column_stack([np.ones(window), np.asarray(rows)])
                penalty = np.eye(design.shape[1], dtype=float) * 1e-8
                penalty[0, 0] = 0.0
                model = np.linalg.solve(
                    design.T @ design + penalty,
                    design.T @ np.asarray(targets),
                )
        state = _har_state(variance, index, horizons, transform)
        if model is None or state is None:
            continue
        predicted = float(np.dot(np.r_[1.0, state], model))
        baseline_horizon = 22 if 22 in horizons else max(horizons)
        baseline = max(
            float(variance[index - baseline_horizon + 1 : index + 1].mean()),
            _EPSILON,
        )
        if transform == "log":
            result[index] = predicted - np.log(baseline)
        else:
            result[index] = max(predicted, _EPSILON) / baseline - 1.0
    return pd.Series(result, index=spy.index).clip(-20.0, 20.0)


def evaluate_advanced_lane(
    lane_id: str,
    spy_frame: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one exact F061-F070 kernel using only rows known at decision time."""

    spy = _validated_spy(spy_frame)
    evaluators = {
        "F061": _f061,
        "F062": _f062,
        "F063": _f063,
        "F064": _f064,
        "F065": _f065,
        "F066": _f066,
        "F067": _f067,
        "F068": _f068,
        "F069": _f069,
        "F070": _f070,
    }
    try:
        evaluator = evaluators[lane_id]
    except KeyError as exc:
        raise AdvancedFeatureEngineError(
            f"ADVANCED_LANE_NOT_IMPLEMENTED:{lane_id}"
        ) from exc
    return _output(spy, evaluator(spy, parameters))


_ADVANCED_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F061": {"kind": "kama", "window": 63, "threshold": 0.25},
    "F062": {"kind": "local_trend", "window": 504, "noise_ratio": 0.01},
    "F063": {"kind": "db2", "scales": 3, "window": 126, "statistic": "sign"},
    "F064": {
        "period": 20,
        "window": 252,
        "detrend": "mean",
        "phase_stability": 0.5,
    },
    "F065": {
        "statistic": "lempel_ziv",
        "window": 126,
        "lag": 2,
        "direction": "continuation",
    },
    "F066": {"order": 3, "window": 252, "smoothing": 0.5},
    "F067": {"order": 2, "window": 252, "bins": 5, "smoothing": 0.5},
    "F068": {"p": 2, "q": 1, "window": 504, "refit": "monthly"},
    "F069": {
        "kind": "gjr",
        "p": 1,
        "q": 1,
        "distribution": "student_t",
        "student_df": 8,
        "window": 504,
        "refit": "quarterly",
    },
    "F070": {
        "estimator": "rogers_satchell",
        "horizons": "1_5_22",
        "window": 504,
        "refit": "quarterly",
        "transform": "log",
    },
}


def evaluate_advanced_family_batch(
    spy_frame: pd.DataFrame,
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for every F061-F070 lane."""

    return {
        lane_id: evaluate_advanced_lane(lane_id, spy_frame, parameters)
        for lane_id, parameters in _ADVANCED_BATCH_PARAMETERS.items()
    }


__all__ = [
    "AdvancedFeatureEngineError",
    "evaluate_advanced_family_batch",
    "evaluate_advanced_lane",
]
