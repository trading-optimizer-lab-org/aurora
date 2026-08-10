"""Trailing-only nonlinear and regime kernels for SP500 lanes F131-F140."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class NonlinearFeatureEngineError(ValueError):
    """Raised when a nonlinear input or parameter violates the train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_EPSILON = np.finfo(float).eps
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


def _validated(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = ("date", "observed_at", "available_at")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise NonlinearFeatureEngineError(
            f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}"
        )
    panel = frame.copy()
    for column in required:
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.normalize()
    if panel[list(required)].isna().any().any():
        raise NonlinearFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(
        _TRAIN_END
    ).any():
        raise NonlinearFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["observed_at"].gt(panel["available_at"]).any() or panel[
        "available_at"
    ].gt(panel["date"]).any():
        raise NonlinearFeatureEngineError(f"NON_CAUSAL_PANEL_ROW:{name}")
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise NonlinearFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _required(panels: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
    if name not in panels:
        raise NonlinearFeatureEngineError(f"NONLINEAR_PANELS_MISSING:{name}")
    return _validated(name, panels[name])


def _spy(panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    spy = _required(panels, "spy")
    if "close" not in spy:
        raise NonlinearFeatureEngineError("PANEL_VALUE_MISSING:spy:close")
    spy["close"] = pd.to_numeric(spy["close"], errors="coerce")
    if not np.isfinite(spy["close"].to_numpy(dtype=float)).all() or spy[
        "close"
    ].le(0.0).any():
        raise NonlinearFeatureEngineError("INVALID_SPY_CLOSE")
    return spy


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise NonlinearFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _bounded_float(
    parameters: Mapping[str, Any],
    name: str,
    default: float,
    *,
    lower: float,
    upper: float,
    lower_open: bool = False,
) -> float:
    value = float(parameters.get(name, default))
    lower_ok = value > lower if lower_open else value >= lower
    if not np.isfinite(value) or not lower_ok or value > upper:
        raise NonlinearFeatureEngineError(f"INVALID_BOUNDED_PARAMETER:{name}:{value}")
    return value


def _pick(
    parameters: Mapping[str, Any],
    lane: str,
    choices: Mapping[str, pd.Series],
    default: str,
) -> pd.Series:
    statistic = str(parameters.get("statistic", default))
    if statistic not in choices:
        raise NonlinearFeatureEngineError(f"{lane}_UNKNOWN_STATISTIC:{statistic}")
    return choices[statistic]


def _output(
    master: pd.DataFrame,
    value: pd.Series | np.ndarray,
    observed: Sequence[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    observed_at = master["observed_at"]
    if observed:
        observed_at = pd.concat(
            [panel["observed_at"].reset_index(drop=True) for panel in observed],
            axis=1,
        ).max(axis=1)
    return pd.DataFrame(
        {
            "date": master["date"],
            "observed_at": observed_at,
            "available_at": master["available_at"],
            "value": pd.to_numeric(
                pd.Series(value, index=master.index), errors="coerce"
            ).replace([np.inf, -np.inf], np.nan),
        }
    )


def _returns(spy: pd.DataFrame) -> pd.Series:
    return np.log(spy["close"]).diff()


def _causal_filter(
    values: np.ndarray, coefficients: np.ndarray, dilation: int
) -> np.ndarray:
    result = np.full(len(values), np.nan)
    required = (len(coefficients) - 1) * dilation
    for index in range(required, len(values)):
        positions = index - np.arange(len(coefficients)) * dilation
        sample = values[positions]
        if np.isfinite(sample).all():
            result[index] = float(np.dot(coefficients, sample))
    return result


def _wavelet_details(
    values: np.ndarray, *, kind: str, scales: int
) -> list[np.ndarray]:
    if kind == "causal_modwt":
        details: list[np.ndarray] = []
        for scale in range(1, scales + 1):
            half = 2 ** (scale - 1)
            detail = np.full(len(values), np.nan)
            for index in range(2 * half - 1, len(values)):
                recent = values[index - half + 1 : index + 1]
                prior = values[index - 2 * half + 1 : index - half + 1]
                if np.isfinite(recent).all() and np.isfinite(prior).all():
                    detail[index] = float(
                        (recent.sum() - prior.sum()) / np.sqrt(2.0 * half)
                    )
            details.append(detail)
        return details
    if kind not in _WAVELET_FILTERS:
        raise NonlinearFeatureEngineError(f"F131_UNKNOWN_KIND:{kind}")
    low, high = _WAVELET_FILTERS[kind]
    approximation = values.copy()
    details = []
    for scale in range(1, scales + 1):
        dilation = 2 ** (scale - 1)
        details.append(_causal_filter(approximation, high / np.sqrt(2.0), dilation))
        approximation = _causal_filter(
            approximation, low / np.sqrt(2.0), dilation
        )
    return details


def _f131(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    scales = _positive_int(parameters, "scales", 3)
    if scales < 2 or scales > 5:
        raise NonlinearFeatureEngineError("F131_SCALES_OUT_OF_RANGE")
    kind = str(parameters.get("kind", "haar"))
    details = _wavelet_details(
        _returns(spy).to_numpy(dtype=float), kind=kind, scales=scales
    )
    energy = pd.DataFrame(np.column_stack(details), index=spy.index).pow(2).rolling(
        window, min_periods=window
    ).mean()
    total = energy.sum(axis=1, min_count=scales).replace(0.0, np.nan)
    shares = energy.div(total, axis=0)
    high = shares.iloc[:, 0]
    low = shares.iloc[:, -1]
    entropy = -(shares * np.log(shares.where(shares.gt(0.0)))).sum(
        axis=1, min_count=scales
    ) / np.log(float(scales))
    concentration = shares.max(axis=1).where(shares.notna().all(axis=1))
    return _pick(
        parameters,
        "F131",
        {
            "high_frequency_share": high,
            "low_frequency_share": low,
            "energy_entropy": entropy,
            "scale_concentration": concentration,
        },
        "energy_entropy",
    )


def _extrema(values: np.ndarray, *, maxima: bool) -> np.ndarray:
    center = values[1:-1]
    if maxima:
        mask = (center >= values[:-2]) & (center > values[2:])
    else:
        mask = (center <= values[:-2]) & (center < values[2:])
    return np.flatnonzero(mask) + 1


def _envelope(values: np.ndarray, indices: np.ndarray) -> np.ndarray:
    x = np.arange(len(values), dtype=float)
    envelope = np.interp(x, indices, values[indices])
    left_slope = (values[indices[1]] - values[indices[0]]) / float(
        indices[1] - indices[0]
    )
    right_slope = (values[indices[-1]] - values[indices[-2]]) / float(
        indices[-1] - indices[-2]
    )
    envelope[: indices[0]] = values[indices[0]] + left_slope * (
        x[: indices[0]] - float(indices[0])
    )
    envelope[indices[-1] + 1 :] = values[indices[-1]] + right_slope * (
        x[indices[-1] + 1 :] - float(indices[-1])
    )
    return envelope


def _emd_components(
    segment: np.ndarray, *, components: int, sift_iterations: int
) -> tuple[list[np.ndarray], np.ndarray]:
    residual = segment.copy()
    imfs: list[np.ndarray] = []
    for _ in range(components):
        candidate = residual.copy()
        for _ in range(sift_iterations):
            maxima = _extrema(candidate, maxima=True)
            minima = _extrema(candidate, maxima=False)
            if len(maxima) < 2 or len(minima) < 2:
                break
            candidate = candidate - 0.5 * (
                _envelope(candidate, maxima) + _envelope(candidate, minima)
            )
        imfs.append(candidate)
        residual = residual - candidate
    return imfs, residual


def _endpoint_emd(
    segment: np.ndarray,
    *,
    kind: str,
    components: int,
    sift_iterations: int,
    ensembles: int,
    noise_scale: float,
    seed: int,
) -> tuple[np.ndarray, float]:
    if kind == "emd":
        imfs, residual = _emd_components(
            segment, components=components, sift_iterations=sift_iterations
        )
        return np.array([imf[-1] for imf in imfs]), float(residual[-1])
    if kind != "eemd":
        raise NonlinearFeatureEngineError(f"F132_UNKNOWN_KIND:{kind}")
    scale = max(float(np.std(segment, ddof=0)), _EPSILON)
    endpoint_imfs = np.zeros(components)
    endpoint_residual = 0.0
    for ensemble in range(ensembles):
        generator = np.random.default_rng(seed + ensemble * 104729)
        noisy = segment + generator.standard_normal(len(segment)) * scale * noise_scale
        imfs, residual = _emd_components(
            noisy, components=components, sift_iterations=sift_iterations
        )
        endpoint_imfs += np.array([imf[-1] for imf in imfs])
        endpoint_residual += float(residual[-1])
    return endpoint_imfs / float(ensembles), endpoint_residual / float(ensembles)


def _f132(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    components = _positive_int(parameters, "components", 2)
    sifts = _positive_int(parameters, "sift_iterations", 3)
    ensembles = _positive_int(parameters, "ensembles", 4)
    noise_scale = _bounded_float(
        parameters, "noise_scale", 0.05, lower=0.0, upper=1.0
    )
    if components < 2 or components > 5:
        raise NonlinearFeatureEngineError("F132_COMPONENTS_OUT_OF_RANGE")
    if ensembles < 2:
        raise NonlinearFeatureEngineError("F132_ENSEMBLES_BELOW_TWO")
    kind = str(parameters.get("kind", "emd"))
    values = _returns(spy).to_numpy(dtype=float)
    outputs = {
        name: np.full(len(spy), np.nan)
        for name in ("imf1", "imf2", "residual", "oscillation_share")
    }
    for index in range(window, len(spy)):
        segment = values[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        imfs, residual = _endpoint_emd(
            segment,
            kind=kind,
            components=components,
            sift_iterations=sifts,
            ensembles=ensembles,
            noise_scale=noise_scale,
            seed=1320003 + index * 1009,
        )
        scale = max(float(np.std(segment, ddof=0)), _EPSILON)
        outputs["imf1"][index] = imfs[0] / scale
        outputs["imf2"][index] = imfs[1] / scale
        outputs["residual"][index] = residual / scale
        denominator = float(np.abs(imfs).sum() + abs(residual))
        outputs["oscillation_share"][index] = (
            float(np.abs(imfs).sum()) / max(denominator, _EPSILON)
        )
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F132", choices, "oscillation_share")


def _f133(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    embedding = _positive_int(parameters, "embedding", 10)
    components = _positive_int(parameters, "components", 3)
    if not 2 <= embedding < window:
        raise NonlinearFeatureEngineError("F133_INVALID_EMBEDDING")
    if components > min(embedding, window - embedding + 1):
        raise NonlinearFeatureEngineError("F133_TOO_MANY_COMPONENTS")
    values = _returns(spy).to_numpy(dtype=float)
    outputs = {
        name: np.full(len(spy), np.nan)
        for name in (
            "trend_component",
            "oscillatory_component",
            "residual",
            "singular_concentration",
        )
    }
    for index in range(window, len(spy)):
        segment = values[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        mean = float(segment.mean())
        centered = segment - mean
        trajectory = np.lib.stride_tricks.sliding_window_view(
            centered, embedding
        ).T
        left, singular, right = np.linalg.svd(trajectory, full_matrices=False)
        endpoint = singular[:components] * left[-1, :components] * right[:components, -1]
        scale = max(float(segment.std(ddof=0)), _EPSILON)
        trend = mean + endpoint[0]
        oscillation = float(endpoint[1:].sum()) if components > 1 else 0.0
        reconstruction = mean + float(endpoint.sum())
        energy = np.square(singular)
        outputs["trend_component"][index] = trend / scale
        outputs["oscillatory_component"][index] = oscillation / scale
        outputs["residual"][index] = (segment[-1] - reconstruction) / scale
        outputs["singular_concentration"][index] = energy[0] / max(
            float(energy.sum()), _EPSILON
        )
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F133", choices, "trend_component")


def _aligned_calendar(
    spy: pd.DataFrame, panels: Mapping[str, pd.DataFrame]
) -> pd.DataFrame:
    calendar = _required(panels, "calendar")
    required = {
        "weekday",
        "month",
        "session_of_month",
        "sessions_remaining_month",
    }
    missing = sorted(required - set(calendar.columns))
    if missing:
        raise NonlinearFeatureEngineError(
            f"CALENDAR_COLUMNS_MISSING:{','.join(missing)}"
        )
    aligned = spy[["date"]].merge(calendar, on="date", how="left", validate="one_to_one")
    if aligned[list(required) + ["observed_at", "available_at"]].isna().any().any():
        raise NonlinearFeatureEngineError("CALENDAR_DOES_NOT_COVER_SPY")
    if aligned["available_at"].gt(aligned["date"]).any():
        raise NonlinearFeatureEngineError("FORWARD_CALENDAR_ROW")
    return aligned


def _prior_bucket_mean(
    residual: np.ndarray,
    labels: np.ndarray,
    *,
    window: int,
    minimum: int,
) -> np.ndarray:
    result = np.full(len(residual), np.nan)
    for index in range(len(residual)):
        start = max(0, index - window)
        candidates = residual[start:index]
        matching = labels[start:index] == labels[index]
        values = candidates[matching & np.isfinite(candidates)]
        if len(values) >= minimum:
            result[index] = float(values.mean())
    return result


def _f134(
    spy: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.DataFrame]:
    window = _positive_int(parameters, "window", 252)
    trend_window = _positive_int(parameters, "trend_window", 63)
    minimum = _positive_int(parameters, "min_occurrences", 3)
    if trend_window >= window:
        raise NonlinearFeatureEngineError("F134_TREND_NOT_BELOW_WINDOW")
    calendar = _aligned_calendar(spy, panels)
    returns = _returns(spy)
    trend = returns.rolling(trend_window, min_periods=trend_window).mean()
    residual = (returns - trend).to_numpy(dtype=float)
    weekday = _prior_bucket_mean(
        residual,
        calendar["weekday"].to_numpy(),
        window=window,
        minimum=minimum,
    )
    month = _prior_bucket_mean(
        residual,
        calendar["month"].to_numpy(),
        window=window,
        minimum=minimum,
    )
    turn_label = np.select(
        (
            calendar["session_of_month"].to_numpy(dtype=float) <= 3.0,
            calendar["sessions_remaining_month"].to_numpy(dtype=float) <= 3.0,
        ),
        (1, -1),
        default=0,
    )
    turn = _prior_bucket_mean(
        residual, turn_label, window=window, minimum=minimum
    )
    scale = returns.shift(1).rolling(window, min_periods=window).std(
        ddof=0
    ).replace(0.0, np.nan)
    choices = {
        "trend": trend / scale,
        "weekday_seasonality": pd.Series(weekday, index=spy.index) / scale,
        "month_seasonality": pd.Series(month, index=spy.index) / scale,
        "turn_of_month": pd.Series(turn, index=spy.index) / scale,
        "combined": (
            trend
            + pd.Series(weekday + month + turn, index=spy.index)
        )
        / scale,
    }
    return _pick(parameters, "F134", choices, "combined"), calendar


def _normalize_subsequences(values: np.ndarray, kind: str) -> np.ndarray:
    if kind == "raw":
        scale = max(float(np.std(values, ddof=0)), _EPSILON)
        return values / scale
    if kind != "z":
        raise NonlinearFeatureEngineError(f"F135_UNKNOWN_NORMALIZATION:{kind}")
    means = values.mean(axis=1, keepdims=True)
    scales = values.std(axis=1, ddof=0, keepdims=True)
    return (values - means) / np.where(scales > _EPSILON, scales, 1.0)


def _f135(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    subsequence = _positive_int(parameters, "subsequence", 10)
    exclusion = _positive_int(parameters, "exclusion", 10)
    neighbors = _positive_int(parameters, "neighbors", 5)
    radius = _bounded_float(
        parameters, "radius", 1.0, lower=0.0, upper=10.0, lower_open=True
    )
    normalization = str(parameters.get("normalization", "z"))
    if 2 * subsequence + exclusion >= window:
        raise NonlinearFeatureEngineError("F135_WINDOW_TOO_SHORT")
    values = _returns(spy).to_numpy(dtype=float)
    outputs = {
        name: np.full(len(spy), np.nan)
        for name in (
            "discord_score",
            "motif_density",
            "motif_follow_through",
            "neighbor_dispersion",
        )
    }
    for index in range(window, len(spy)):
        segment = values[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        subsequences = np.lib.stride_tricks.sliding_window_view(segment, subsequence)
        query_start = len(segment) - subsequence
        last_candidate = query_start - exclusion - subsequence
        if last_candidate < 0:
            continue
        candidates = subsequences[: last_candidate + 1]
        normalized = _normalize_subsequences(
            np.vstack((candidates, subsequences[-1])), normalization
        )
        candidate_values = normalized[:-1]
        query = normalized[-1]
        distances = np.sqrt(np.mean(np.square(candidate_values - query), axis=1))
        count = min(neighbors, len(distances))
        selected = np.argpartition(distances, count - 1)[:count]
        continuation_indices = selected + subsequence
        follow = segment[continuation_indices]
        outputs["discord_score"][index] = float(distances.min())
        outputs["motif_density"][index] = float(np.mean(distances <= radius))
        outputs["motif_follow_through"][index] = float(follow.mean())
        outputs["neighbor_dispersion"][index] = float(follow.std(ddof=0))
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F135", choices, "motif_follow_through")


def _run_lengths(values: np.ndarray) -> list[int]:
    lengths: list[int] = []
    current = 0
    for value in values:
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _recurrence_statistics(
    segment: np.ndarray,
    *,
    embedding: int,
    delay: int,
    radius: float,
    minimum_line: int,
) -> tuple[float, float, float, float]:
    span = (embedding - 1) * delay + 1
    count = len(segment) - span + 1
    vectors = np.column_stack(
        [segment[offset : offset + count] for offset in range(0, span, delay)]
    )
    vectors = (vectors - vectors.mean(axis=0)) / np.where(
        vectors.std(axis=0, ddof=0) > _EPSILON,
        vectors.std(axis=0, ddof=0),
        1.0,
    )
    distance = np.sqrt(
        np.mean(np.square(vectors[:, None, :] - vectors[None, :, :]), axis=2)
    )
    recurrence = distance <= radius
    np.fill_diagonal(recurrence, False)
    recurrent_points = int(recurrence.sum())
    rate = recurrent_points / float(max(count * (count - 1), 1))
    diagonal_lengths: list[int] = []
    for offset in range(-(count - 1), count):
        if offset:
            diagonal_lengths.extend(_run_lengths(np.diagonal(recurrence, offset=offset)))
    qualifying_diagonal = [length for length in diagonal_lengths if length >= minimum_line]
    deterministic_points = sum(qualifying_diagonal)
    determinism = deterministic_points / float(max(recurrent_points, 1))
    if qualifying_diagonal:
        unique, counts = np.unique(qualifying_diagonal, return_counts=True)
        del unique
        probabilities = counts / counts.sum()
        entropy = float(-(probabilities * np.log(probabilities)).sum())
    else:
        entropy = 0.0
    vertical_lengths: list[int] = []
    for column in range(count):
        vertical_lengths.extend(_run_lengths(recurrence[:, column]))
    laminar_points = sum(
        length for length in vertical_lengths if length >= minimum_line
    )
    laminarity = laminar_points / float(max(recurrent_points, 1))
    return rate, entropy, determinism, laminarity


def _f136(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    embedding = _positive_int(parameters, "embedding", 3)
    delay = _positive_int(parameters, "delay", 1)
    minimum_line = _positive_int(parameters, "minimum_line", 2)
    radius = _bounded_float(
        parameters, "radius", 1.0, lower=0.0, upper=10.0, lower_open=True
    )
    if (embedding - 1) * delay + 2 > window:
        raise NonlinearFeatureEngineError("F136_EMBEDDING_EXCEEDS_WINDOW")
    values = _returns(spy).to_numpy(dtype=float)
    names = ("recurrence_rate", "recurrence_entropy", "determinism", "laminarity")
    outputs = {name: np.full(len(spy), np.nan) for name in names}
    for index in range(window, len(spy)):
        segment = values[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        statistics = _recurrence_statistics(
            segment,
            embedding=embedding,
            delay=delay,
            radius=radius,
            minimum_line=minimum_line,
        )
        for name, value in zip(names, statistics, strict=True):
            outputs[name][index] = value
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F136", choices, "determinism")


def _generalized_hurst(path: np.ndarray, q: float) -> float:
    lags = np.array([1, 2, 4, 8, 16, 32], dtype=int)
    lags = lags[lags <= max(1, len(path) // 4)]
    moments = np.array(
        [np.mean(np.abs(path[lag:] - path[:-lag]) ** q) for lag in lags]
    )
    valid = np.isfinite(moments) & (moments > _EPSILON)
    if valid.sum() < 2:
        return np.nan
    slope = np.polyfit(np.log(lags[valid]), np.log(moments[valid]), 1)[0]
    return float(slope / q)


def _f137(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    q_low = _bounded_float(
        parameters, "q_low", 0.5, lower=0.0, upper=4.0, lower_open=True
    )
    q_high = _bounded_float(
        parameters, "q_high", 2.0, lower=0.0, upper=4.0, lower_open=True
    )
    if q_low >= q_high:
        raise NonlinearFeatureEngineError("F137_Q_NOT_ASCENDING")
    direction = str(parameters.get("direction", "continuation"))
    if direction not in {"continuation", "reversal"}:
        raise NonlinearFeatureEngineError(f"F137_UNKNOWN_DIRECTION:{direction}")
    values = _returns(spy).to_numpy(dtype=float)
    names = ("hurst", "roughness", "fractal_dimension", "multifractal_width")
    outputs = {name: np.full(len(spy), np.nan) for name in names}
    for index in range(window, len(spy)):
        segment = values[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        path = np.cumsum(segment)
        hurst = _generalized_hurst(path, 2.0)
        low_hurst = _generalized_hurst(path, q_low)
        high_hurst = _generalized_hurst(path, q_high)
        roughness = float(np.mean(np.abs(np.diff(path)))) / max(
            float(np.std(path, ddof=0)), _EPSILON
        )
        sign = float(np.sign(path[-1] - path[0]))
        if direction == "reversal":
            sign = -sign
        outputs["hurst"][index] = sign * hurst
        outputs["roughness"][index] = sign * roughness
        outputs["fractal_dimension"][index] = sign * (2.0 - hurst)
        outputs["multifractal_width"][index] = sign * (low_hurst - high_hurst)
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F137", choices, "hurst")


def _f138(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    tail = _bounded_float(
        parameters, "tail", 0.05, lower=0.0, upper=0.25, lower_open=True
    )
    direction = str(parameters.get("direction", "reversal"))
    if direction not in {"continuation", "reversal"}:
        raise NonlinearFeatureEngineError(f"F138_UNKNOWN_DIRECTION:{direction}")
    values = _returns(spy).to_numpy(dtype=float)
    names = ("tail_frequency", "tail_magnitude", "stress_duration", "hill_tail_index")
    outputs = {name: np.full(len(spy), np.nan) for name in names}
    duration = 0
    for index in range(window + 1, len(spy)):
        history = values[index - window : index]
        current = values[index]
        if not np.isfinite(history).all() or not np.isfinite(current):
            duration = 0
            continue
        absolute = np.sort(np.abs(history))[::-1]
        count = max(2, int(np.ceil(tail * window)))
        threshold = max(float(absolute[count - 1]), _EPSILON)
        exceed = abs(current) > threshold
        duration = duration + 1 if exceed else 0
        recent = history[-max(5, window // 4) :]
        frequency = float(np.mean(np.abs(recent) > threshold)) - tail
        scale = max(float(np.std(history, ddof=0)), _EPSILON)
        magnitude = max(abs(current) - threshold, 0.0) / scale
        hill = float(np.mean(np.log(absolute[:count] / threshold)))
        tail_index = min(20.0, 1.0 / max(hill, _EPSILON))
        state_sign = float(np.sign(history[-min(20, window) :].sum()))
        if direction == "reversal":
            state_sign = -state_sign
        outputs["tail_frequency"][index] = state_sign * frequency
        outputs["tail_magnitude"][index] = state_sign * magnitude
        outputs["stress_duration"][index] = state_sign * duration / float(window)
        outputs["hill_tail_index"][index] = state_sign * tail_index
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F138", choices, "tail_magnitude")


def _f139(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    decay = _bounded_float(
        parameters, "shock_decay", 0.94, lower=0.0, upper=1.0, lower_open=True
    )
    if decay >= 1.0:
        raise NonlinearFeatureEngineError("F139_DECAY_NOT_BELOW_ONE")
    asymmetry = _bounded_float(
        parameters, "asymmetry", 1.0, lower=0.0, upper=5.0
    )
    kind = str(parameters.get("kind", "asymmetric_ewma"))
    if kind not in {"ewma", "garch_proxy", "asymmetric_ewma"}:
        raise NonlinearFeatureEngineError(f"F139_UNKNOWN_KIND:{kind}")
    returns = _returns(spy)
    values = returns.to_numpy(dtype=float)
    baseline = returns.rolling(window, min_periods=window).var(ddof=0).to_numpy()
    variance = np.full(len(spy), np.nan)
    innovation = np.full(len(spy), np.nan)
    downside = np.full(len(spy), np.nan)
    upside = np.full(len(spy), np.nan)
    for index in range(window, len(spy)):
        shock = values[index] ** 2
        if not np.isfinite(shock) or not np.isfinite(baseline[index]):
            continue
        if not np.isfinite(variance[index - 1]):
            variance[index] = baseline[index]
            downside[index] = baseline[index] / 2.0
            upside[index] = baseline[index] / 2.0
            continue
        prior = max(variance[index - 1], _EPSILON)
        innovation[index] = shock / prior - 1.0
        if kind == "ewma":
            variance[index] = decay * prior + (1.0 - decay) * shock
        elif kind == "garch_proxy":
            alpha = 0.8 * (1.0 - decay)
            beta = decay
            omega = max(1.0 - alpha - beta, 0.0) * baseline[index]
            variance[index] = omega + alpha * shock + beta * prior
        else:
            alpha = (1.0 - decay) / (1.0 + 0.5 * asymmetry)
            multiplier = 1.0 + asymmetry * float(values[index] < 0.0)
            variance[index] = decay * prior + alpha * shock * multiplier
        downside[index] = decay * downside[index - 1] + (
            (1.0 - decay) * shock if values[index] < 0.0 else 0.0
        )
        upside[index] = decay * upside[index - 1] + (
            (1.0 - decay) * shock if values[index] >= 0.0 else 0.0
        )
    filtered = np.sqrt(np.maximum(variance, 0.0) * 252.0)
    asymmetry_ratio = np.log(
        (downside + _EPSILON) / (upside + _EPSILON)
    )
    variance_gap = variance / np.where(baseline > _EPSILON, baseline, np.nan) - 1.0
    choices = {
        "filtered_volatility": pd.Series(filtered, index=spy.index),
        "volatility_innovation": pd.Series(innovation, index=spy.index),
        "asymmetry_ratio": pd.Series(asymmetry_ratio, index=spy.index),
        "variance_gap": pd.Series(variance_gap, index=spy.index),
    }
    return _pick(parameters, "F139", choices, "variance_gap")


def _fit_ar_regime(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if len(x) < 5 or float(np.var(x, ddof=0)) <= _EPSILON:
        return float(np.mean(y)) if len(y) else 0.0, 0.0
    design = np.column_stack((np.ones(len(x)), x))
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    return float(coefficients[0]), float(coefficients[1])


def _f140(spy: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.Series:
    window = _positive_int(parameters, "window", 126)
    regimes = _positive_int(parameters, "regimes", 2)
    lag = _positive_int(parameters, "lag", 1)
    quantile = _bounded_float(
        parameters,
        "threshold_quantile",
        0.5,
        lower=0.0,
        upper=1.0,
        lower_open=True,
    )
    speed = _bounded_float(
        parameters, "transition_speed", 5.0, lower=0.0, upper=50.0, lower_open=True
    )
    kind = str(parameters.get("kind", "setar"))
    if kind not in {"setar", "star", "observable_threshold"}:
        raise NonlinearFeatureEngineError(f"F140_UNKNOWN_KIND:{kind}")
    if regimes not in {2, 3}:
        raise NonlinearFeatureEngineError("F140_REGIMES_NOT_TWO_OR_THREE")
    if regimes == 3 and quantile >= 0.5:
        raise NonlinearFeatureEngineError("F140_THREE_REGIME_QUANTILE_NOT_BELOW_HALF")
    values = _returns(spy).to_numpy(dtype=float)
    names = ("forecast", "regime_state", "transition_probability", "regime_spread")
    outputs = {name: np.full(len(spy), np.nan) for name in names}
    for index in range(window + lag, len(spy)):
        segment = values[index - window + 1 : index + 1]
        if not np.isfinite(segment).all():
            continue
        x = segment[:-lag]
        y = segment[lag:]
        thresholds = (
            np.array([np.quantile(x, quantile)])
            if regimes == 2
            else np.quantile(x, [quantile, 1.0 - quantile])
        )
        labels = np.searchsorted(thresholds, x, side="right")
        current_label = int(np.searchsorted(thresholds, segment[-1], side="right"))
        models = [
            _fit_ar_regime(x[labels == regime], y[labels == regime])
            for regime in range(regimes)
        ]
        predictions = np.array(
            [intercept + slope * segment[-1] for intercept, slope in models]
        )
        scale = max(float(np.std(y, ddof=0)), _EPSILON)
        if kind == "star":
            threshold = float(thresholds[0])
            probability = float(
                1.0
                / (
                    1.0
                    + np.exp(
                        np.clip(
                            -speed * (segment[-1] - threshold) / scale,
                            -50.0,
                            50.0,
                        )
                    )
                )
            )
            forecast = (1.0 - probability) * predictions[0] + probability * predictions[-1]
        elif kind == "observable_threshold":
            probability = current_label / float(regimes - 1)
            forecast = float(np.mean(y[labels == current_label]))
        else:
            probability = current_label / float(regimes - 1)
            forecast = predictions[current_label]
        outputs["forecast"][index] = forecast / scale
        outputs["regime_state"][index] = 2.0 * current_label / float(regimes - 1) - 1.0
        outputs["transition_probability"][index] = probability
        outputs["regime_spread"][index] = (predictions[-1] - predictions[0]) / scale
    choices = {
        name: pd.Series(values_, index=spy.index) for name, values_ in outputs.items()
    }
    return _pick(parameters, "F140", choices, "forecast")


def evaluate_nonlinear_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F131-F140 lane with trailing information only."""

    spy = _spy(input_panels)
    if lane_id == "F134":
        value, calendar = _f134(spy, input_panels, parameters)
        return _output(spy, value, (spy, calendar))
    evaluators = {
        "F131": _f131,
        "F132": _f132,
        "F133": _f133,
        "F135": _f135,
        "F136": _f136,
        "F137": _f137,
        "F138": _f138,
        "F139": _f139,
        "F140": _f140,
    }
    if lane_id not in evaluators:
        raise NonlinearFeatureEngineError(f"NONLINEAR_LANE_NOT_IMPLEMENTED:{lane_id}")
    return _output(spy, evaluators[lane_id](spy, parameters))


_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F131": {"statistic": "energy_entropy", "kind": "haar", "scales": 3, "window": 63},
    "F132": {"statistic": "oscillation_share", "kind": "emd", "window": 63, "components": 2, "sift_iterations": 3, "ensembles": 4, "noise_scale": 0.05},
    "F133": {"statistic": "trend_component", "window": 63, "embedding": 10, "components": 3},
    "F134": {"statistic": "combined", "window": 252, "trend_window": 63, "min_occurrences": 3},
    "F135": {"statistic": "motif_follow_through", "window": 126, "subsequence": 10, "exclusion": 10, "neighbors": 5, "radius": 1.0, "normalization": "z"},
    "F136": {"statistic": "determinism", "window": 63, "embedding": 3, "delay": 1, "radius": 1.0, "minimum_line": 2},
    "F137": {"statistic": "hurst", "window": 126, "q_low": 0.5, "q_high": 2.0, "direction": "continuation"},
    "F138": {"statistic": "tail_magnitude", "window": 126, "tail": 0.05, "direction": "reversal"},
    "F139": {"statistic": "variance_gap", "kind": "asymmetric_ewma", "window": 63, "shock_decay": 0.94, "asymmetry": 1.0},
    "F140": {"statistic": "forecast", "kind": "setar", "window": 126, "threshold_quantile": 0.5, "regimes": 2, "lag": 1, "transition_speed": 5.0},
}


def evaluate_nonlinear_family_batch(
    input_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for each F131-F140 lane."""

    return {
        lane_id: evaluate_nonlinear_lane(lane_id, input_panels, parameters)
        for lane_id, parameters in _BATCH_PARAMETERS.items()
    }


__all__ = [
    "NonlinearFeatureEngineError",
    "evaluate_nonlinear_family_batch",
    "evaluate_nonlinear_lane",
]
