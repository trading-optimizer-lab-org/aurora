"""Causal FX, commodity, rates and cross-asset kernels for lanes F171-F180."""

from __future__ import annotations

from math import ceil
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class CrossAssetFeatureEngineError(ValueError):
    """Raised when a cross-asset input or parameter breaks the frozen contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_FX_COLUMNS = (
    "fx_cad",
    "fx_jpy",
    "fx_chf",
    "fx_gbp",
    "fx_aud",
    "fx_nzd",
    "fx_dkk",
    "fx_nok",
    "fx_sek",
)
_ENERGY = ("crude_oil", "coal", "natural_gas")
_INDUSTRIAL_METALS = ("aluminum", "copper", "lead", "tin", "nickel", "zinc")
_PRECIOUS_METALS = ("gold", "platinum", "silver")
_AGRICULTURE = (
    "cocoa",
    "coffee_arabica",
    "coffee_robusta",
    "palm_oil",
    "soybeans",
    "maize",
    "rice",
    "wheat",
    "beef",
    "sugar",
    "cotton",
)
_FERTILIZERS = ("phosphate_rock", "dap", "urea", "potash")
_ALL_COMMODITIES = (
    *_ENERGY,
    *_INDUSTRIAL_METALS,
    *_PRECIOUS_METALS,
    *_AGRICULTURE,
    *_FERTILIZERS,
)
_MINIMUM_CROSS_SECTION_COVERAGE = 0.8
_MATURITY_SPECS: Mapping[str, tuple[str, str, float, float, float]] = {
    "2y": ("yield_2y", "yield_3m", 2.0, 0.25, 1.9),
    "5y": ("yield_5y", "yield_2y", 5.0, 2.0, 4.5),
    "10y": ("yield_10y", "yield_5y", 10.0, 5.0, 8.0),
    "20y": ("yield_20y", "yield_10y", 20.0, 10.0, 12.0),
}
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F171": ("fx",),
    "F172": ("fx", "rates"),
    "F173": ("fx",),
    "F174": ("commodities",),
    "F175": ("commodities",),
    "F176": ("commodities",),
    "F177": ("commodities",),
    "F178": ("fx", "rates", "commodities"),
    "F179": ("rates",),
    "F180": ("rates",),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise CrossAssetFeatureEngineError(
            f"MISSING_TIMESTAMP_COLUMNS:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result[list(_TIMESTAMPS)].isna().any().any():
        raise CrossAssetFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(
        _TRAIN_END
    ).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise CrossAssetFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise CrossAssetFeatureEngineError(
            f"OBSERVED_AFTER_AVAILABILITY:{label}"
        )
    if result["available_at"].gt(result["date"]).any():
        raise CrossAssetFeatureEngineError(f"AVAILABLE_AFTER_PANEL_DATE:{label}")
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise CrossAssetFeatureEngineError(f"DATES_NOT_STRICTLY_ORDERED:{label}")
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise CrossAssetFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _nonnegative(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 0:
        raise CrossAssetFeatureEngineError(
            f"INVALID_NONNEGATIVE_PARAMETER:{name}:{value}"
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
        raise CrossAssetFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(
        parameters, "direction", ("continuation", "reversal"), "continuation"
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
        raise CrossAssetFeatureEngineError(
            f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}"
        )
    result = panel.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    return result.replace([np.inf, -np.inf], np.nan)


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
        raise CrossAssetFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{label}")
    return aligned


def _output(
    market: pd.DataFrame,
    value: pd.Series,
    aligned: Sequence[pd.DataFrame],
    *,
    include_market: bool = False,
) -> pd.DataFrame:
    observed_parts = [panel["source_observed_at"] for panel in aligned]
    available_parts = [panel["source_available_at"] for panel in aligned]
    if include_market:
        observed_parts.append(market["observed_at"])
        available_parts.append(market["available_at"])
    observed = pd.concat(observed_parts, axis=1).max(axis=1)
    available = pd.concat(available_parts, axis=1).max(axis=1)
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


def _align_derived(
    market: pd.DataFrame,
    source: pd.DataFrame,
    value: pd.Series,
    *,
    label: str,
) -> pd.DataFrame:
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["value"] = pd.to_numeric(value, errors="coerce")
    aligned = _align_panel(market, derived, label=label)
    return _output(market, aligned["value"], (aligned,))


def _rolling_zscore(value: pd.Series, window: int) -> pd.Series:
    mean = value.rolling(window, min_periods=window).mean()
    scale = value.rolling(window, min_periods=window).std(ddof=0)
    return (value - mean) / scale.replace(0.0, np.nan)


def _minimum_coverage(matrix: pd.DataFrame) -> pd.Series:
    minimum = ceil(matrix.shape[1] * _MINIMUM_CROSS_SECTION_COVERAGE)
    return matrix.notna().sum(axis=1).ge(minimum)


def _covered_mean(matrix: pd.DataFrame) -> pd.Series:
    return matrix.mean(axis=1).where(_minimum_coverage(matrix))


def _covered_std(matrix: pd.DataFrame) -> pd.Series:
    return matrix.std(axis=1, ddof=0).where(_minimum_coverage(matrix))


def _covered_breadth(matrix: pd.DataFrame, threshold: float) -> pd.Series:
    if not 0.0 <= threshold <= 1.0:
        raise CrossAssetFeatureEngineError(
            f"INVALID_BREADTH_THRESHOLD:{threshold}"
        )
    breadth = matrix.gt(0.0).where(matrix.notna()).mean(axis=1) - threshold
    return breadth.where(_minimum_coverage(matrix))


def _rank_weighted(matrix: pd.DataFrame) -> pd.Series:
    ranks = matrix.rank(axis=1, pct=True, method="average") - 0.5
    demeaned = matrix.sub(matrix.mean(axis=1), axis=0)
    denominator = ranks.abs().sum(axis=1).replace(0.0, np.nan)
    value = (ranks * demeaned).sum(axis=1, min_count=2) / denominator
    return value.where(_minimum_coverage(matrix))


def _tail_spread(
    matrix: pd.DataFrame,
    *,
    fraction: float,
    median: bool,
) -> pd.Series:
    if not 0.0 < fraction <= 0.5:
        raise CrossAssetFeatureEngineError(
            f"INVALID_SELECTION_FRACTION:{fraction}"
        )
    minimum = ceil(matrix.shape[1] * _MINIMUM_CROSS_SECTION_COVERAGE)
    output = np.full(len(matrix), np.nan)
    for index, row in enumerate(matrix.to_numpy(dtype=float)):
        available = np.sort(row[np.isfinite(row)])
        if len(available) < minimum:
            continue
        count = max(1, ceil(len(available) * fraction))
        low = available[:count]
        high = available[-count:]
        reducer = np.median if median else np.mean
        output[index] = float(reducer(high) - reducer(low))
    return pd.Series(output, index=matrix.index)


def _fx_changes(fx: pd.DataFrame, *, window: int, skip: int = 0) -> pd.DataFrame:
    levels = _numeric_matrix(fx, columns=_FX_COLUMNS, label="fx")
    levels = np.log(levels.where(levels.gt(0.0)))
    return levels.shift(skip).diff(window)


def _f171(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    fx = panels["fx"]
    window = _positive(parameters, "window", 13)
    changes = _fx_changes(fx, window=window)
    broad = np.log(
        _numeric_matrix(fx, columns=("broad_dollar",), label="fx")[
            "broad_dollar"
        ].where(lambda values: values.gt(0.0))
    ).diff(window)
    cross_mean = _covered_mean(changes)
    statistic = _choice(
        parameters,
        "statistic",
        ("official_broad", "cross_mean", "breadth", "divergence", "dispersion"),
        "official_broad",
    )
    choices = {
        "official_broad": broad,
        "cross_mean": cross_mean,
        "breadth": _covered_breadth(
            changes, float(parameters.get("threshold", 0.5))
        ),
        "divergence": broad - cross_mean,
        "dispersion": _covered_std(changes),
    }
    return _align_derived(
        market, fx, _direction(choices[statistic], parameters), label="f171"
    )


def _f172(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    fx = _align_panel(market, panels["fx"], label="fx")
    rates = _align_panel(market, panels["rates"], label="rates")
    window = _positive(parameters, "window", 63)
    long_window = _positive(parameters, "long_window", 252)
    rate_values = _numeric_matrix(
        rates,
        columns=("treasury_3m", "offshore_basis"),
        label="rates",
    )
    cash_level = _rolling_zscore(rate_values["treasury_3m"], long_window)
    offshore_basis = _rolling_zscore(rate_values["offshore_basis"], long_window)
    carry_pressure = cash_level - offshore_basis
    broad = _numeric_matrix(
        fx, columns=("broad_dollar",), label="fx"
    )["broad_dollar"]
    dollar_direction = np.sign(np.log(broad.where(broad.gt(0.0))).diff(window))
    statistic = _choice(
        parameters,
        "statistic",
        ("cash_level", "offshore_basis", "carry_pressure", "fx_adjusted_pressure"),
        "carry_pressure",
    )
    choices = {
        "cash_level": cash_level,
        "offshore_basis": offshore_basis,
        "carry_pressure": carry_pressure,
        "fx_adjusted_pressure": carry_pressure * dollar_direction,
    }
    return _output(
        market, _direction(choices[statistic], parameters), (fx, rates)
    )


def _f173(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    fx = panels["fx"]
    changes = _fx_changes(
        fx,
        window=_positive(parameters, "window", 13),
        skip=_nonnegative(parameters, "skip", 1),
    )
    aggregation = _choice(
        parameters, "aggregation", ("mean", "median", "breadth", "rank"), "mean"
    )
    if aggregation == "breadth":
        value = _covered_breadth(changes, 0.5)
    elif aggregation == "rank":
        value = _rank_weighted(changes)
    else:
        value = _tail_spread(
            changes,
            fraction=float(parameters.get("selection_fraction", 0.25)),
            median=aggregation == "median",
        )
    return _align_derived(
        market, fx, _direction(value, parameters), label="f173"
    )


def _commodity_changes(
    commodities: pd.DataFrame,
    columns: Sequence[str],
    window: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    levels = _numeric_matrix(
        commodities, columns=columns, label="commodities"
    ).where(lambda values: values.gt(0.0))
    log_levels = np.log(levels)
    return log_levels, log_levels.diff(window)


def _commodity_level_momentum_breadth(
    commodities: pd.DataFrame,
    columns: Sequence[str],
    parameters: Mapping[str, Any],
) -> pd.Series:
    log_levels, changes = _commodity_changes(
        commodities, columns, _positive(parameters, "window", 12)
    )
    normalization_window = _positive(parameters, "normalization_window", 36)
    mean = log_levels.rolling(
        normalization_window, min_periods=normalization_window
    ).mean()
    scale = log_levels.rolling(
        normalization_window, min_periods=normalization_window
    ).std(ddof=0)
    level = _covered_mean((log_levels - mean) / scale.replace(0.0, np.nan))
    statistic = _choice(
        parameters, "statistic", ("level", "momentum", "breadth"), "momentum"
    )
    if statistic == "level":
        return level
    if statistic == "momentum":
        return _covered_mean(changes)
    return _covered_breadth(changes, float(parameters.get("threshold", 0.5)))


def _f174(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    commodities = panels["commodities"]
    value = _commodity_level_momentum_breadth(
        commodities, _ENERGY, parameters
    )
    return _align_derived(
        market, commodities, _direction(value, parameters), label="f174"
    )


def _f175(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    commodities = panels["commodities"]
    window = _positive(parameters, "window", 12)
    _, industrial = _commodity_changes(
        commodities, _INDUSTRIAL_METALS, window
    )
    _, precious = _commodity_changes(commodities, _PRECIOUS_METALS, window)
    industrial_momentum = _covered_mean(industrial)
    precious_momentum = _covered_mean(precious)
    all_changes = pd.concat([industrial, precious], axis=1)
    statistic = _choice(
        parameters,
        "statistic",
        (
            "industrial_momentum",
            "precious_momentum",
            "industrial_minus_precious",
            "breadth",
            "dispersion",
        ),
        "industrial_minus_precious",
    )
    choices = {
        "industrial_momentum": industrial_momentum,
        "precious_momentum": precious_momentum,
        "industrial_minus_precious": industrial_momentum - precious_momentum,
        "breadth": _covered_breadth(all_changes, 0.5),
        "dispersion": _covered_std(all_changes),
    }
    return _align_derived(
        market,
        commodities,
        _direction(choices[statistic], parameters),
        label="f175",
    )


def _f176(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    commodities = panels["commodities"]
    value = _commodity_level_momentum_breadth(
        commodities, _AGRICULTURE, parameters
    )
    return _align_derived(
        market, commodities, _direction(value, parameters), label="f176"
    )


def _f177(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    commodities = panels["commodities"]
    _, changes = _commodity_changes(
        commodities, _ALL_COMMODITIES, _positive(parameters, "window", 12)
    )
    mean = _covered_mean(changes)
    dispersion = _covered_std(changes)
    absolute = changes.abs()
    weights = absolute.div(absolute.sum(axis=1).replace(0.0, np.nan), axis=0)
    concentration = (
        weights.pow(2).sum(axis=1, min_count=2) - 1.0 / changes.shape[1]
    ).where(_minimum_coverage(changes))
    statistic = _choice(
        parameters,
        "statistic",
        ("breadth", "dispersion", "inflation_pressure", "concentration"),
        "dispersion",
    )
    choices = {
        "breadth": _covered_breadth(
            changes, float(parameters.get("threshold", 0.5))
        ),
        "dispersion": dispersion,
        "inflation_pressure": mean / dispersion.replace(0.0, np.nan),
        "concentration": concentration,
    }
    return _align_derived(
        market,
        commodities,
        _direction(choices[statistic], parameters),
        label="f177",
    )


def _f178(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    fx = _align_panel(market, panels["fx"], label="fx")
    rates = _align_panel(market, panels["rates"], label="rates")
    commodities = _align_panel(
        market, panels["commodities"], label="commodities"
    )
    window = _positive(parameters, "window", 63)
    normalization_window = _positive(parameters, "normalization_window", 252)
    close = _numeric_matrix(market, columns=("close",), label="market")["close"]
    broad = _numeric_matrix(fx, columns=("broad_dollar",), label="fx")[
        "broad_dollar"
    ]
    yield_10y = _numeric_matrix(
        rates, columns=("yield_10y",), label="rates"
    )["yield_10y"]
    commodity_levels = _numeric_matrix(
        commodities, columns=_ALL_COMMODITIES, label="commodities"
    ).where(lambda values: values.gt(0.0))
    commodity_index = np.log(commodity_levels).mean(axis=1)
    trends = pd.DataFrame(
        {
            "spy": np.log(close.where(close.gt(0.0))).diff(window),
            "usd": -np.log(broad.where(broad.gt(0.0))).diff(window),
            "bond": -8.0 * yield_10y.diff(window) / 100.0
            + yield_10y.shift(window) / 100.0 * window / 252.0,
            "commodity": commodity_index.diff(window),
        }
    )
    scales = trends.rolling(
        normalization_window, min_periods=normalization_window
    ).std(ddof=0)
    scaled = trends / scales.replace(0.0, np.nan)
    statistic = _choice(
        parameters,
        "statistic",
        (
            "sign_breadth",
            "volatility_scaled_mean",
            "dispersion",
            "stock_minus_defensive",
        ),
        "sign_breadth",
    )
    choices = {
        "sign_breadth": np.sign(trends).mean(axis=1),
        "volatility_scaled_mean": scaled.mean(axis=1),
        "dispersion": scaled.std(axis=1, ddof=0),
        "stock_minus_defensive": scaled["spy"]
        - scaled.loc[:, ["usd", "bond"]].mean(axis=1),
    }
    return _output(
        market,
        _direction(choices[statistic], parameters),
        (fx, rates, commodities),
        include_market=True,
    )


def _maturity_inputs(
    rates: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> tuple[pd.Series, pd.Series, float, float, float]:
    maturity = _choice(parameters, "maturity", tuple(_MATURITY_SPECS), "10y")
    current_column, previous_column, years, previous_years, duration = (
        _MATURITY_SPECS[maturity]
    )
    values = _numeric_matrix(
        rates,
        columns=(current_column, previous_column),
        label="rates",
    )
    return values[current_column], values[previous_column], years, previous_years, duration


def _f179(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    rates = _align_panel(market, panels["rates"], label="rates")
    current, previous, years, previous_years, duration = _maturity_inputs(
        rates, parameters
    )
    window = _positive(parameters, "window", 63)
    carry = current.shift(1) / 100.0 * window / 252.0
    roll = (
        duration
        * (current.shift(1) - previous.shift(1))
        / 100.0
        * window
        / (252.0 * (years - previous_years))
    )
    momentum = -duration * (current - current.shift(window)) / 100.0
    statistic = _choice(
        parameters, "statistic", ("carry", "roll", "momentum", "total"), "total"
    )
    value = {
        "carry": carry,
        "roll": roll,
        "momentum": momentum,
        "total": carry + roll + momentum,
    }[statistic]
    normalization = _choice(
        parameters, "normalization", ("raw", "rolling_zscore"), "raw"
    )
    if normalization == "rolling_zscore":
        value = _rolling_zscore(value, _positive(parameters, "z_window", 252))
    return _output(market, _direction(value, parameters), (rates,))


def _f180(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    rates = _align_panel(market, panels["rates"], label="rates")
    current, _, _, _, duration = _maturity_inputs(rates, parameters)
    close = _numeric_matrix(market, columns=("close",), label="market")["close"]
    stock_return = np.log(close.where(close.gt(0.0))).diff()
    bond_return = -duration * current.diff() / 100.0 + current.shift(1) / 100.0 / 252.0
    window = _positive(parameters, "window", 63)
    long_window = _positive(parameters, "long_window", 252)
    correlation = stock_return.rolling(window, min_periods=window).corr(bond_return)
    long_correlation = stock_return.rolling(
        long_window, min_periods=long_window
    ).corr(bond_return)
    statistic = _choice(
        parameters,
        "statistic",
        ("correlation", "decoupling", "sign_change", "beta"),
        "correlation",
    )
    if statistic in {"decoupling", "sign_change"} and long_window <= window:
        raise CrossAssetFeatureEngineError("LONG_WINDOW_NOT_ABOVE_WINDOW")
    covariance = stock_return.rolling(window, min_periods=window).cov(bond_return)
    bond_variance = bond_return.rolling(window, min_periods=window).var(ddof=1)
    sign_change = np.sign(correlation).where(
        np.sign(correlation).ne(np.sign(long_correlation)), 0.0
    )
    sign_change = sign_change.where(
        correlation.notna() & long_correlation.notna()
    )
    choices = {
        "correlation": correlation,
        "decoupling": correlation - long_correlation,
        "sign_change": sign_change,
        "beta": covariance / bond_variance.replace(0.0, np.nan),
    }
    return _output(
        market,
        _direction(choices[statistic], parameters),
        (rates,),
        include_market=True,
    )


_EVALUATORS = {
    "F171": _f171,
    "F172": _f172,
    "F173": _f173,
    "F174": _f174,
    "F175": _f175,
    "F176": _f176,
    "F177": _f177,
    "F178": _f178,
    "F179": _f179,
    "F180": _f180,
}
_DEFAULT_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F171": {"window": 13, "statistic": "divergence", "threshold": 0.5, "direction": "continuation"},
    "F172": {"window": 63, "long_window": 252, "statistic": "carry_pressure", "direction": "continuation"},
    "F173": {"window": 26, "skip": 1, "aggregation": "rank", "selection_fraction": 0.25, "direction": "continuation"},
    "F174": {"window": 12, "normalization_window": 36, "statistic": "breadth", "threshold": 0.5, "direction": "continuation"},
    "F175": {"window": 12, "statistic": "industrial_minus_precious", "direction": "continuation"},
    "F176": {"window": 12, "normalization_window": 36, "statistic": "momentum", "threshold": 0.5, "direction": "continuation"},
    "F177": {"window": 12, "statistic": "inflation_pressure", "threshold": 0.5, "direction": "continuation"},
    "F178": {"window": 63, "normalization_window": 252, "statistic": "volatility_scaled_mean", "direction": "continuation"},
    "F179": {"window": 63, "maturity": "10y", "statistic": "total", "normalization": "raw", "z_window": 252, "direction": "continuation"},
    "F180": {"window": 63, "long_window": 252, "maturity": "10y", "statistic": "decoupling", "direction": "continuation"},
}


def evaluate_cross_asset_lane(
    lane_id: str,
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F171-F180 lane using released train rows only."""

    if lane_id not in _EVALUATORS:
        raise CrossAssetFeatureEngineError(f"UNKNOWN_CROSS_ASSET_LANE:{lane_id}")
    market = _validated(market_frame, label="market")
    missing = [source for source in _LANE_SOURCES[lane_id] if source not in raw_panels]
    if missing:
        raise CrossAssetFeatureEngineError(
            f"MISSING_CROSS_ASSET_PANEL:{lane_id}:{','.join(missing)}"
        )
    panels = {
        source: _validated(raw_panels[source], label=source)
        for source in _LANE_SOURCES[lane_id]
    }
    return _EVALUATORS[lane_id](market, panels, parameters)


def evaluate_cross_asset_family_batch(
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate the ten frozen defaults in stable F171-F180 order."""

    return {
        lane: evaluate_cross_asset_lane(
            lane, market_frame, raw_panels, parameters
        )
        for lane, parameters in _DEFAULT_PARAMETERS.items()
    }


__all__ = [
    "CrossAssetFeatureEngineError",
    "evaluate_cross_asset_family_batch",
    "evaluate_cross_asset_lane",
]
