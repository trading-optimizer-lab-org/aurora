"""Causal industry and global-factor kernels for SP500 lanes F161-F170."""

from __future__ import annotations

from math import ceil
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class GlobalFactorFeatureEngineError(ValueError):
    """Raised when an industry or global-factor input breaks the contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_REGION_FACTORS = (
    "europe",
    "japan",
    "asia_pacific_ex_japan",
)
_REGION_MOMENTUM = (
    "europe_momentum",
    "japan_momentum",
    "asia_pacific_ex_japan_momentum",
)
_FACTOR_UNIVERSES: Mapping[str, tuple[str, ...]] = {
    "regions_only": _REGION_FACTORS,
    "developed_ex_us_plus_regions": ("developed_ex_us", *_REGION_FACTORS),
    "all_available": (
        "developed_five_factors",
        "developed_ex_us",
        *_REGION_FACTORS,
    ),
}
_MOMENTUM_UNIVERSES: Mapping[str, tuple[str, ...]] = {
    "regions_only": _REGION_MOMENTUM,
    "developed_ex_us_plus_regions": (
        "developed_ex_us_momentum",
        *_REGION_MOMENTUM,
    ),
    "all_available": (
        "developed_momentum",
        "developed_ex_us_momentum",
        *_REGION_MOMENTUM,
    ),
}
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F161": ("industries",),
    "F162": ("industries",),
    "F163": ("industries",),
    "F164": ("us_factors",),
    "F165": ("us_factors",),
    "F166": ("us_factors", "developed_ex_us"),
    "F167": _REGION_FACTORS,
    "F168": ("developed_five_factors",),
    "F169": tuple(_MOMENTUM_UNIVERSES["all_available"]),
    "F170": tuple(_FACTOR_UNIVERSES["all_available"]),
}
_TIMESTAMPS = ("date", "observed_at", "available_at")


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise GlobalFactorFeatureEngineError(
            f"MISSING_TIMESTAMP_COLUMNS:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result[list(_TIMESTAMPS)].isna().any().any():
        raise GlobalFactorFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(
        _TRAIN_END
    ).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise GlobalFactorFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise GlobalFactorFeatureEngineError(
            f"OBSERVED_AFTER_AVAILABILITY:{label}"
        )
    if result["available_at"].gt(result["date"]).any():
        raise GlobalFactorFeatureEngineError(
            f"AVAILABLE_AFTER_PANEL_DATE:{label}"
        )
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise GlobalFactorFeatureEngineError(
            f"DATES_NOT_STRICTLY_ORDERED:{label}"
        )
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise GlobalFactorFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _choice(
    parameters: Mapping[str, Any],
    name: str,
    choices: Sequence[str],
    default: str,
) -> str:
    value = str(parameters.get(name, default))
    if value not in choices:
        raise GlobalFactorFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(
        parameters,
        "direction",
        ("continuation", "reversal"),
        "continuation",
    )
    return value if direction == "continuation" else -value


def _numeric_matrix(
    panel: pd.DataFrame,
    *,
    columns: Sequence[str],
    label: str,
) -> pd.DataFrame:
    missing = sorted(set(columns) - set(panel.columns))
    if missing:
        raise GlobalFactorFeatureEngineError(
            f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}"
        )
    result = panel.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    return result.replace([np.inf, -np.inf], np.nan)


def _industry_columns(panel: pd.DataFrame) -> tuple[str, ...]:
    columns = tuple(column for column in panel if column not in _TIMESTAMPS)
    if len(columns) < 2:
        raise GlobalFactorFeatureEngineError("INSUFFICIENT_INDUSTRIES")
    return columns


def _align_panel(
    market: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    label: str,
) -> pd.DataFrame:
    value_columns = [column for column in panel if column not in _TIMESTAMPS]
    right = panel.rename(
        columns={
            "date": "source_date",
            "observed_at": "source_observed_at",
            "available_at": "source_available_at",
        }
    )
    aligned = pd.merge_asof(
        market.loc[:, ["date"]],
        right.loc[
            :,
            [
                "source_date",
                "source_observed_at",
                "source_available_at",
                *value_columns,
            ],
        ].sort_values("source_date", kind="mergesort"),
        left_on="date",
        right_on="source_date",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="source_date")
    if aligned["source_available_at"].gt(aligned["date"]).fillna(False).any():
        raise GlobalFactorFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{label}")
    return aligned


def _output(
    market: pd.DataFrame,
    value: pd.Series,
    aligned: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    observed = pd.concat(
        [panel["source_observed_at"] for panel in aligned], axis=1
    ).max(axis=1)
    available = pd.concat(
        [panel["source_available_at"] for panel in aligned], axis=1
    ).max(axis=1)
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": observed.fillna(market["observed_at"]),
            "available_at": available.fillna(market["available_at"]),
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _trailing_log(matrix: pd.DataFrame, window: int, skip: int = 0) -> pd.DataFrame:
    valid = matrix.where(matrix.gt(-1.0))
    return np.log1p(valid).shift(skip).rolling(window, min_periods=window).sum()


def _breadth_modes(
    cumulative: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    threshold = float(parameters.get("threshold", 0.5))
    if not 0.0 <= threshold <= 1.0:
        raise GlobalFactorFeatureEngineError(
            f"INVALID_BREADTH_THRESHOLD:{threshold}"
        )
    breadth = cumulative.gt(0.0).where(cumulative.notna()).mean(axis=1)
    mode = _choice(
        parameters,
        "mode",
        ("level", "change", "divergence"),
        "level",
    )
    if mode == "level":
        return breadth - threshold
    if mode == "change":
        lag = _positive(parameters, "change_lag", 5)
        return breadth.diff(lag)
    window = _positive(parameters, "window", 63)
    return breadth - breadth.rolling(window, min_periods=window).mean()


def _rank_weighted(matrix: pd.DataFrame) -> pd.Series:
    ranks = matrix.rank(axis=1, pct=True, method="average") - 0.5
    demeaned = matrix.sub(matrix.mean(axis=1), axis=0)
    denominator = ranks.abs().sum(axis=1).replace(0.0, np.nan)
    return (ranks * demeaned).sum(axis=1, min_count=2) / denominator


def _momentum_aggregation(
    cumulative: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    aggregation = _choice(
        parameters,
        "aggregation",
        ("mean", "median", "breadth", "rank"),
        "mean",
    )
    if aggregation == "breadth":
        return cumulative.gt(0.0).where(cumulative.notna()).mean(axis=1) - 0.5
    if aggregation == "rank":
        return _rank_weighted(cumulative)
    fraction = float(parameters.get("selection_fraction", 0.25))
    if not 0.0 < fraction <= 0.5:
        raise GlobalFactorFeatureEngineError(
            f"INVALID_SELECTION_FRACTION:{fraction}"
        )
    count = max(1, ceil(cumulative.shape[1] * fraction))
    sorted_values = np.sort(cumulative.to_numpy(dtype=float), axis=1)
    low = pd.DataFrame(sorted_values[:, :count], index=cumulative.index)
    high = pd.DataFrame(sorted_values[:, -count:], index=cumulative.index)
    if aggregation == "mean":
        return high.mean(axis=1) - low.mean(axis=1)
    return high.median(axis=1) - low.median(axis=1)


def _rolling_mean_correlation(matrix: pd.DataFrame, window: int) -> pd.Series:
    values = matrix.to_numpy(dtype=float)
    output = np.full(len(matrix), np.nan)
    for end in range(window - 1, len(matrix)):
        sample = values[end - window + 1 : end + 1]
        complete_columns = np.isfinite(sample).all(axis=0)
        sample = sample[:, complete_columns]
        if sample.shape[1] < 2:
            continue
        nonconstant = np.nanstd(sample, axis=0, ddof=0) > 0.0
        sample = sample[:, nonconstant]
        if sample.shape[1] < 2:
            continue
        correlation = np.corrcoef(sample, rowvar=False)
        upper = correlation[np.triu_indices(correlation.shape[0], k=1)]
        if np.isfinite(upper).any():
            output[end] = float(np.nanmean(upper))
    return pd.Series(output, index=matrix.index)


def _f161(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = _align_panel(market, panels["industries"], label="industries")
    columns = _industry_columns(panels["industries"])
    values = _numeric_matrix(aligned, columns=columns, label="industries")
    cumulative = _trailing_log(values, _positive(parameters, "window", 63))
    return _output(market, _breadth_modes(cumulative, parameters), (aligned,))


def _f162(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = _align_panel(market, panels["industries"], label="industries")
    columns = _industry_columns(panels["industries"])
    values = _numeric_matrix(aligned, columns=columns, label="industries")
    cumulative = _trailing_log(
        values,
        _positive(parameters, "window", 63),
        int(parameters.get("skip", 0)),
    )
    if int(parameters.get("skip", 0)) < 0:
        raise GlobalFactorFeatureEngineError("INVALID_NONNEGATIVE_PARAMETER:skip")
    value = _direction(_momentum_aggregation(cumulative, parameters), parameters)
    return _output(market, value, (aligned,))


def _f163(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = _align_panel(market, panels["industries"], label="industries")
    columns = _industry_columns(panels["industries"])
    values = _numeric_matrix(aligned, columns=columns, label="industries")
    window = _positive(parameters, "window", 63)
    statistic = _choice(
        parameters,
        "statistic",
        ("std", "iqr", "mad", "hhi", "mean_correlation"),
        "std",
    )
    if statistic == "std":
        raw = values.std(axis=1, ddof=0)
    elif statistic == "iqr":
        raw = values.quantile(0.75, axis=1) - values.quantile(0.25, axis=1)
    elif statistic == "mad":
        median = values.median(axis=1)
        raw = values.sub(median, axis=0).abs().median(axis=1)
    elif statistic == "hhi":
        absolute = values.abs()
        weights = absolute.div(absolute.sum(axis=1).replace(0.0, np.nan), axis=0)
        raw = weights.pow(2).sum(axis=1, min_count=2) - 1.0 / values.shape[1]
    else:
        raw = _rolling_mean_correlation(values, window)
        return _output(market, _direction(raw, parameters), (aligned,))
    value = raw.rolling(window, min_periods=window).mean()
    return _output(market, _direction(value, parameters), (aligned,))


def _us_factor_matrix(aligned: pd.DataFrame) -> pd.DataFrame:
    raw = _numeric_matrix(
        aligned,
        columns=("market_excess", "smb", "hml"),
        label="us_factors",
    )
    return raw.rename(columns={"smb": "size", "hml": "value"})


def _factor_component(
    cumulative: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> pd.Series:
    component = _choice(
        parameters,
        "component",
        ("market_excess", "size", "value", "equal_weight", "breadth"),
        "equal_weight",
    )
    if component in cumulative:
        return cumulative[component]
    if component == "equal_weight":
        return cumulative.mean(axis=1)
    return cumulative.gt(0.0).where(cumulative.notna()).mean(axis=1) - 0.5


def _f164(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = _align_panel(market, panels["us_factors"], label="us_factors")
    factors = _us_factor_matrix(aligned)
    cumulative = factors.rolling(
        _positive(parameters, "window", 63),
        min_periods=_positive(parameters, "window", 63),
    ).sum()
    return _output(market, _factor_component(cumulative, parameters), (aligned,))


def _f165(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = _align_panel(market, panels["us_factors"], label="us_factors")
    factors = _us_factor_matrix(aligned)
    window = _positive(parameters, "window", 63)
    short = _positive(parameters, "short_window", 20)
    if short >= window:
        raise GlobalFactorFeatureEngineError("SHORT_WINDOW_NOT_BELOW_WINDOW")
    statistic = _choice(
        parameters,
        "statistic",
        ("dispersion", "sign_disagreement", "regime_change", "mean_correlation"),
        "dispersion",
    )
    if statistic == "dispersion":
        value = factors.std(axis=1, ddof=0).rolling(
            window, min_periods=window
        ).mean()
    elif statistic == "sign_disagreement":
        cumulative = factors.rolling(window, min_periods=window).sum()
        value = 1.0 - cumulative.apply(np.sign).mean(axis=1).abs()
    elif statistic == "regime_change":
        long_state = factors.rolling(window, min_periods=window).sum()
        short_state = factors.rolling(short, min_periods=short).sum()
        value = (short_state * (window / short) - long_state).mean(axis=1)
    else:
        value = _rolling_mean_correlation(factors, window)
    return _output(market, value, (aligned,))


def _f166(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    us = _align_panel(market, panels["us_factors"], label="us_factors")
    ex_us = _align_panel(
        market, panels["developed_ex_us"], label="developed_ex_us"
    )
    us_values = _us_factor_matrix(us)
    ex_values = _numeric_matrix(
        ex_us,
        columns=("market_excess", "size", "value"),
        label="developed_ex_us",
    )
    window = _positive(parameters, "window", 63)
    difference = ex_values.rolling(window, min_periods=window).sum() - us_values.rolling(
        window, min_periods=window
    ).sum()
    value = _direction(_factor_component(difference, parameters), parameters)
    return _output(market, value, (us, ex_us))


def _regional_matrix(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    resources: Sequence[str],
    *,
    column: str,
) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    aligned: list[pd.DataFrame] = []
    values: dict[str, pd.Series] = {}
    for resource in resources:
        current = _align_panel(market, panels[resource], label=resource)
        aligned.append(current)
        values[resource] = _numeric_matrix(
            current, columns=(column,), label=resource
        )[column]
    return pd.DataFrame(values, index=market.index), aligned


def _f167(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    returns, aligned = _regional_matrix(
        market, panels, _REGION_FACTORS, column="market_excess"
    )
    window = _positive(parameters, "window", 63)
    cumulative = returns.rolling(window, min_periods=window).sum()
    aggregation = _choice(
        parameters,
        "aggregation",
        ("spread", "breadth", "rank", "weighted_vote"),
        "spread",
    )
    if aggregation == "spread":
        value = cumulative.max(axis=1) - cumulative.min(axis=1)
    elif aggregation == "breadth":
        value = cumulative.gt(0.0).where(cumulative.notna()).mean(axis=1) - 0.5
    elif aggregation == "rank":
        value = _rank_weighted(cumulative)
    else:
        volatility = returns.rolling(window, min_periods=window).std(ddof=0)
        inverse = 1.0 / volatility.replace(0.0, np.nan)
        value = (cumulative * inverse).sum(
            axis=1, min_count=len(_REGION_FACTORS)
        ) / (
            inverse.sum(axis=1, min_count=len(_REGION_FACTORS))
        )
    return _output(market, _direction(value, parameters), aligned)


def _f168(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = _align_panel(
        market,
        panels["developed_five_factors"],
        label="developed_five_factors",
    )
    columns = ("size", "value", "profitability", "investment")
    factors = _numeric_matrix(
        aligned, columns=columns, label="developed_five_factors"
    )
    window = _positive(parameters, "window", 63)
    cumulative = factors.rolling(window, min_periods=window).sum()
    component = _choice(
        parameters,
        "component",
        (
            "equal_weight",
            "size_value",
            "quality_investment",
            "quality_minus_speculation",
        ),
        "equal_weight",
    )
    coefficients = {
        "equal_weight": np.array([1.0, 1.0, 1.0, 1.0]),
        "size_value": np.array([1.0, 1.0, 0.0, 0.0]),
        "quality_investment": np.array([0.0, 0.0, 1.0, 1.0]),
        "quality_minus_speculation": np.array([-1.0, -1.0, 1.0, 1.0]),
    }[component]
    weighting = _choice(
        parameters,
        "weighting",
        ("equal", "inverse_vol", "sign_vote"),
        "equal",
    )
    if weighting == "sign_vote":
        active = coefficients != 0.0
        value = (
            np.sign(cumulative.loc[:, active]) * np.sign(coefficients[active])
        ).mean(axis=1)
    else:
        if weighting == "equal":
            weights = pd.DataFrame(
                np.broadcast_to(coefficients, cumulative.shape),
                index=cumulative.index,
                columns=cumulative.columns,
            )
        else:
            inverse_vol = 1.0 / factors.rolling(
                window, min_periods=window
            ).std(ddof=0).replace(0.0, np.nan)
            weights = inverse_vol.mul(coefficients, axis=1)
        denominator = weights.abs().sum(axis=1).replace(0.0, np.nan)
        value = (cumulative * weights).sum(axis=1, min_count=1) / denominator
    return _output(market, value, (aligned,))


def _f169(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    universe = _choice(
        parameters,
        "universe",
        tuple(_MOMENTUM_UNIVERSES),
        "regions_only",
    )
    resources = _MOMENTUM_UNIVERSES[universe]
    returns, aligned = _regional_matrix(
        market, panels, resources, column="momentum"
    )
    skip = int(parameters.get("skip", 0))
    if skip < 0:
        raise GlobalFactorFeatureEngineError("INVALID_NONNEGATIVE_PARAMETER:skip")
    cumulative = returns.shift(skip).rolling(
        _positive(parameters, "window", 63),
        min_periods=_positive(parameters, "window", 63),
    ).sum()
    value = _direction(_momentum_aggregation(cumulative, parameters), parameters)
    return _output(market, value, aligned)


def _f170(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    universe = _choice(
        parameters,
        "universe",
        tuple(_FACTOR_UNIVERSES),
        "regions_only",
    )
    resources = _FACTOR_UNIVERSES[universe]
    returns, aligned = _regional_matrix(
        market, panels, resources, column="market_excess"
    )
    window = _positive(parameters, "window", 63)
    cumulative = returns.rolling(window, min_periods=window).sum()
    return _output(market, _breadth_modes(cumulative, parameters), aligned)


_EVALUATORS = {
    "F161": _f161,
    "F162": _f162,
    "F163": _f163,
    "F164": _f164,
    "F165": _f165,
    "F166": _f166,
    "F167": _f167,
    "F168": _f168,
    "F169": _f169,
    "F170": _f170,
}
_DEFAULT_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F161": {"window": 63, "threshold": 0.5, "mode": "level", "change_lag": 10},
    "F162": {"window": 126, "skip": 5, "aggregation": "mean", "selection_fraction": 0.25, "direction": "continuation"},
    "F163": {"window": 63, "statistic": "std", "direction": "continuation"},
    "F164": {"window": 63, "component": "equal_weight"},
    "F165": {"window": 63, "short_window": 20, "statistic": "regime_change"},
    "F166": {"window": 63, "component": "equal_weight", "direction": "continuation"},
    "F167": {"window": 63, "aggregation": "weighted_vote", "direction": "continuation"},
    "F168": {"window": 63, "component": "quality_minus_speculation", "weighting": "inverse_vol"},
    "F169": {"window": 126, "skip": 5, "aggregation": "breadth", "selection_fraction": 0.25, "universe": "all_available", "direction": "continuation"},
    "F170": {"window": 63, "threshold": 0.5, "mode": "divergence", "change_lag": 10, "universe": "all_available"},
}


def evaluate_global_factor_lane(
    lane_id: str,
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F161-F170 lane using released train rows only."""

    if lane_id not in _EVALUATORS:
        raise GlobalFactorFeatureEngineError(
            f"UNKNOWN_GLOBAL_FACTOR_LANE:{lane_id}"
        )
    market = _validated(market_frame, label="market")
    missing = [source for source in _LANE_SOURCES[lane_id] if source not in raw_panels]
    if missing:
        raise GlobalFactorFeatureEngineError(
            f"MISSING_GLOBAL_FACTOR_PANEL:{lane_id}:{','.join(missing)}"
        )
    panels = {
        source: _validated(raw_panels[source], label=source)
        for source in _LANE_SOURCES[lane_id]
    }
    return _EVALUATORS[lane_id](market, panels, parameters)


def evaluate_global_factor_family_batch(
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate the ten frozen defaults in stable F161-F170 order."""

    return {
        lane: evaluate_global_factor_lane(
            lane, market_frame, raw_panels, parameters
        )
        for lane, parameters in _DEFAULT_PARAMETERS.items()
    }


__all__ = [
    "GlobalFactorFeatureEngineError",
    "evaluate_global_factor_family_batch",
    "evaluate_global_factor_lane",
]
