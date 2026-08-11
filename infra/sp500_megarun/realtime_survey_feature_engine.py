"""Causal real-time macro and survey kernels for SP500 lanes F191-F200."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


class RealtimeSurveyFeatureEngineError(ValueError):
    """Raised when a real-time/survey input or parameter breaks the frozen contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F191": ("realtime",),
    "F192": ("realtime",),
    "F193": ("macro_release",),
    "F194": ("macro_release",),
    "F195": ("macro_release", "cycle"),
    "F196": ("macro_release",),
    "F197": ("spf_central",),
    "F198": ("spf_disagreement",),
    "F199": ("spf_error",),
    "F200": ("sloos",),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise RealtimeSurveyFeatureEngineError(
            f"MISSING_TIMESTAMP_COLUMNS:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result[list(_TIMESTAMPS)].isna().any().any():
        raise RealtimeSurveyFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(_TRAIN_END).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise RealtimeSurveyFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise RealtimeSurveyFeatureEngineError(f"OBSERVED_AFTER_AVAILABILITY:{label}")
    if result["available_at"].gt(result["date"]).any():
        raise RealtimeSurveyFeatureEngineError(f"AVAILABLE_AFTER_PANEL_DATE:{label}")
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise RealtimeSurveyFeatureEngineError(f"DATES_NOT_STRICTLY_ORDERED:{label}")
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise RealtimeSurveyFeatureEngineError(f"INVALID_POSITIVE_PARAMETER:{name}:{value}")
    return value


def _choice(
    parameters: Mapping[str, Any],
    name: str,
    choices: Sequence[str],
    default: str,
) -> str:
    value = str(parameters.get(name, default))
    if value not in choices:
        raise RealtimeSurveyFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(parameters, "direction", ("continuation", "reversal"), "continuation")
    return value if direction == "continuation" else -value


def _numeric_matrix(
    frame: pd.DataFrame,
    *,
    columns: Sequence[str],
    label: str,
) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise RealtimeSurveyFeatureEngineError(
            f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}"
        )
    return (
        frame.loc[:, list(columns)]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )


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
            ["source_date", "source_observed_at", "source_available_at", *value_columns],
        ].sort_values("source_date", kind="mergesort"),
        left_on="date",
        right_on="source_date",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="source_date")
    if aligned["source_available_at"].gt(aligned["date"]).fillna(False).any():
        raise RealtimeSurveyFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{label}")
    return aligned


def _output(
    market: pd.DataFrame,
    value: pd.Series,
    aligned: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    observed = pd.concat([panel["source_observed_at"] for panel in aligned], axis=1).max(axis=1)
    available = pd.concat([panel["source_available_at"] for panel in aligned], axis=1).max(axis=1)
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": observed.fillna(market["observed_at"]),
            "available_at": available.fillna(market["available_at"]),
            "value": pd.to_numeric(value, errors="coerce").replace([np.inf, -np.inf], np.nan),
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


def _normalize(
    value: pd.Series,
    parameters: Mapping[str, Any],
    *,
    window: int,
) -> pd.Series:
    normalization = _choice(
        parameters,
        "normalization",
        ("raw", "change", "rolling_zscore"),
        "raw",
    )
    if normalization == "change":
        return value.diff(_positive(parameters, "change_lag", 1))
    if normalization == "rolling_zscore":
        return _rolling_zscore(value, window)
    return value


def _breadth(values: pd.DataFrame) -> pd.Series:
    return values.gt(0.0).where(values.notna()).mean(axis=1) - 0.5


def _ffilled(source: pd.DataFrame, columns: Sequence[str], *, label: str) -> pd.DataFrame:
    return _numeric_matrix(source, columns=columns, label=label).ffill()


def _event_lane(
    market: pd.DataFrame,
    source: pd.DataFrame,
    choices: Mapping[str, pd.Series],
    parameters: Mapping[str, Any],
    *,
    default: str,
    window: int,
    label: str,
) -> pd.DataFrame:
    statistic = _choice(parameters, "statistic", tuple(choices), default)
    value = _normalize(choices[statistic], parameters, window=window)
    return _align_derived(market, source, _direction(value, parameters), label=label)


def _f191(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["realtime"]
    values = _numeric_matrix(
        source,
        columns=("output_growth", "gdi_growth", "output_revision", "gdi_revision"),
        label="realtime",
    )
    growth = values.loc[:, ["output_growth", "gdi_growth"]]
    revisions = values.loc[:, ["output_revision", "gdi_revision"]]
    choices = {
        "output_growth": values["output_growth"],
        "gdi_growth": values["gdi_growth"],
        "average_growth": growth.mean(axis=1, skipna=False),
        "growth_spread": values["output_growth"] - values["gdi_growth"],
        "revision_breadth": revisions.apply(np.sign).mean(axis=1),
        "growth_breadth": _breadth(growth),
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="average_growth",
        window=_positive(parameters, "window", 8),
        label="realtime_f191",
    )


def _f192(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["realtime"]
    values = _numeric_matrix(
        source,
        columns=(
            "nominal_consumption_growth",
            "nominal_disposable_income_growth",
            "saving_rate",
            "saving_rate_change",
        ),
        label="realtime",
    )
    household = pd.concat(
        [
            values["nominal_consumption_growth"],
            values["nominal_disposable_income_growth"],
            values["saving_rate_change"],
        ],
        axis=1,
    )
    choices = {
        "consumption_growth": values["nominal_consumption_growth"],
        "income_growth": values["nominal_disposable_income_growth"],
        "consumption_income_gap": (
            values["nominal_consumption_growth"]
            - values["nominal_disposable_income_growth"]
        ),
        "saving_rate": values["saving_rate"],
        "saving_rate_change": values["saving_rate_change"],
        "household_breadth": _breadth(household),
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="household_breadth",
        window=_positive(parameters, "window", 8),
        label="realtime_f192",
    )


def _f193(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["macro_release"]
    columns = (
        "nonresidential_investment_first",
        "nonresidential_investment_revision",
        "residential_investment_first",
        "residential_investment_revision",
        "housing_starts_first",
        "housing_starts_revision",
    )
    values = _ffilled(source, columns, label="macro_release")
    window = _positive(parameters, "window", 24)
    lag = _positive(parameters, "lag", 3)
    housing_change = np.log(values["housing_starts_first"].where(lambda x: x.gt(0.0))).diff(lag)
    revisions = values.loc[
        :,
        [
            "nonresidential_investment_revision",
            "residential_investment_revision",
            "housing_starts_revision",
        ],
    ]
    composite = pd.concat(
        [
            _rolling_zscore(values["nonresidential_investment_first"], window),
            _rolling_zscore(values["residential_investment_first"], window),
            _rolling_zscore(housing_change, window),
        ],
        axis=1,
    ).mean(axis=1)
    choices = {
        "nonresidential_investment": values["nonresidential_investment_first"],
        "residential_investment": values["residential_investment_first"],
        "housing_starts": values["housing_starts_first"],
        "housing_starts_change": housing_change,
        "investment_breadth": _breadth(
            pd.concat(
                [
                    values["nonresidential_investment_first"],
                    values["residential_investment_first"],
                    housing_change,
                ],
                axis=1,
            )
        ),
        "housing_investment_composite": composite,
        "revision_composite": pd.concat(
            [_rolling_zscore(revisions[column], window) for column in revisions], axis=1
        ).mean(axis=1),
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="housing_investment_composite",
        window=window,
        label="macro_release_f193",
    )


def _f194(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["macro_release"]
    values = _ffilled(
        source,
        (
            "cpi_first",
            "core_cpi_first",
            "core_pce_first",
            "core_pce_revision",
        ),
        label="macro_release",
    )
    inflation = values.loc[:, ["cpi_first", "core_cpi_first", "core_pce_first"]]
    choices = {
        "headline_cpi": values["cpi_first"],
        "core_cpi": values["core_cpi_first"],
        "core_pce": values["core_pce_first"],
        "headline_core_gap": values["cpi_first"] - values["core_cpi_first"],
        "inflation_breadth": inflation.mean(axis=1),
        "revision_pressure": values["core_pce_revision"],
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="inflation_breadth",
        window=_positive(parameters, "window", 24),
        label="macro_release_f194",
    )


def _f195(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    macro = _align_panel(market, panels["macro_release"], label="macro_release")
    cycle = _align_panel(market, panels["cycle"], label="cycle")
    payroll = _numeric_matrix(
        macro,
        columns=("payroll_first", "payroll_revision"),
        label="macro_release",
    ).ffill()
    labor = _numeric_matrix(
        cycle,
        columns=("realtime_unemployment", "unemployment_change"),
        label="cycle",
    ).ffill()
    window = _positive(parameters, "window", 126)
    breadth = pd.concat(
        [payroll["payroll_first"], payroll["payroll_revision"], -labor["unemployment_change"]],
        axis=1,
    )
    composite = pd.concat(
        [
            _rolling_zscore(payroll["payroll_first"], window),
            _rolling_zscore(payroll["payroll_revision"], window),
            -_rolling_zscore(labor["unemployment_change"], window),
        ],
        axis=1,
    ).mean(axis=1)
    choices = {
        "payroll_first": payroll["payroll_first"],
        "payroll_revision": payroll["payroll_revision"],
        "unemployment_level": labor["realtime_unemployment"],
        "unemployment_change": labor["unemployment_change"],
        "labor_breadth": _breadth(breadth),
        "labor_composite": composite,
    }
    statistic = _choice(parameters, "statistic", tuple(choices), "labor_composite")
    value = _normalize(choices[statistic], parameters, window=window)
    return _output(market, _direction(value, parameters), (macro, cycle))


def _f196(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["macro_release"]
    columns = (
        "industrial_production_first",
        "industrial_production_revision",
        "manufacturing_production_first",
        "manufacturing_production_revision",
        "capacity_utilization_first",
        "capacity_utilization_revision",
        "manufacturing_capacity_first",
        "manufacturing_capacity_revision",
    )
    values = _ffilled(source, columns, label="macro_release")
    window = _positive(parameters, "window", 24)
    lag = _positive(parameters, "lag", 3)
    capacity_change = values["capacity_utilization_first"].diff(lag)
    manufacturing_capacity_change = values["manufacturing_capacity_first"].diff(lag)
    breadth_values = pd.concat(
        [
            values["industrial_production_first"],
            values["manufacturing_production_first"],
            capacity_change,
            manufacturing_capacity_change,
        ],
        axis=1,
    )
    revisions = values.loc[
        :,
        [
            "industrial_production_revision",
            "manufacturing_production_revision",
            "capacity_utilization_revision",
            "manufacturing_capacity_revision",
        ],
    ]
    composite = pd.concat(
        [_rolling_zscore(breadth_values[column], window) for column in breadth_values],
        axis=1,
    ).mean(axis=1)
    choices = {
        "industrial_production": values["industrial_production_first"],
        "manufacturing_production": values["manufacturing_production_first"],
        "capacity_utilization": values["capacity_utilization_first"],
        "manufacturing_capacity": values["manufacturing_capacity_first"],
        "utilization_spread": (
            values["capacity_utilization_first"] - values["manufacturing_capacity_first"]
        ),
        "production_breadth": _breadth(breadth_values),
        "production_capacity_composite": composite,
        "revision_composite": pd.concat(
            [_rolling_zscore(revisions[column], window) for column in revisions], axis=1
        ).mean(axis=1),
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="production_breadth",
        window=window,
        label="macro_release_f196",
    )


def _f197(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["spf_central"]
    values = _numeric_matrix(
        source,
        columns=(
            "output_nowcast",
            "output_next_forecast",
            "unemployment_nowcast",
            "cpi_nowcast",
            "housing_nowcast",
            "tbill_nowcast",
        ),
        label="spf_central",
    )
    window = _positive(parameters, "window", 8)
    outlook = pd.concat(
        [
            _rolling_zscore(values["output_nowcast"], window),
            _rolling_zscore(values["housing_nowcast"], window),
            -_rolling_zscore(values["unemployment_nowcast"], window),
            -_rolling_zscore(values["cpi_nowcast"], window),
            -_rolling_zscore(values["tbill_nowcast"], window),
        ],
        axis=1,
    ).mean(axis=1)
    choices = {
        "output_nowcast": values["output_nowcast"],
        "output_next_forecast": values["output_next_forecast"],
        "unemployment_nowcast": values["unemployment_nowcast"],
        "cpi_nowcast": values["cpi_nowcast"],
        "housing_nowcast": values["housing_nowcast"],
        "tbill_nowcast": values["tbill_nowcast"],
        "macro_outlook_composite": outlook,
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="macro_outlook_composite",
        window=window,
        label="spf_central_f197",
    )


def _f198(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["spf_disagreement"]
    values = _numeric_matrix(
        source,
        columns=("ngdp_iqr", "unemployment_iqr", "cpi_iqr", "housing_iqr", "tbill_iqr"),
        label="spf_disagreement",
    )
    window = _positive(parameters, "window", 8)
    normalized = pd.concat(
        [_rolling_zscore(values[column], window) for column in values], axis=1
    )
    medians = values.rolling(window, min_periods=window).median()
    choices = {
        "ngdp_iqr": values["ngdp_iqr"],
        "unemployment_iqr": values["unemployment_iqr"],
        "cpi_iqr": values["cpi_iqr"],
        "housing_iqr": values["housing_iqr"],
        "tbill_iqr": values["tbill_iqr"],
        "macro_disagreement": normalized.mean(axis=1),
        "disagreement_breadth": values.gt(medians).where(values.notna()).mean(axis=1) - 0.5,
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="macro_disagreement",
        window=window,
        label="spf_disagreement_f198",
    )


def _f199(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["spf_error"]
    values = _numeric_matrix(
        source,
        columns=(
            "output_forecast_revision",
            "nowcast_signed_error",
            "nowcast_absolute_error",
            "prior_signed_error",
            "prior_absolute_error",
        ),
        label="spf_error",
    )
    window = _positive(parameters, "window", 8)
    choices = {
        "forecast_revision": values["output_forecast_revision"],
        "nowcast_signed_error": values["nowcast_signed_error"],
        "nowcast_absolute_error": values["nowcast_absolute_error"],
        "prior_signed_error": values["prior_signed_error"],
        "prior_absolute_error": values["prior_absolute_error"],
        "rolling_bias": values["nowcast_signed_error"].rolling(window, min_periods=window).mean(),
        "rolling_absolute_error": values["nowcast_absolute_error"]
        .rolling(window, min_periods=window)
        .mean(),
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="rolling_absolute_error",
        window=window,
        label="spf_error_f199",
    )


def _f200(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["sloos"]
    values = _numeric_matrix(
        source,
        columns=(
            "standards_large_mid",
            "demand_large_mid",
            "standards_small",
            "demand_small",
            "term_credit_line_cost",
            "term_covenants",
            "term_maximum_size",
            "term_collateral",
            "term_spreads",
        ),
        label="sloos",
    )
    supply = values.loc[:, ["standards_large_mid", "standards_small"]]
    demand = values.loc[:, ["demand_large_mid", "demand_small"]]
    terms = values.loc[
        :,
        [
            "term_credit_line_cost",
            "term_covenants",
            "term_maximum_size",
            "term_collateral",
            "term_spreads",
        ],
    ]
    term_tightness = terms.mean(axis=1)
    choices = {
        "standards_large_mid": values["standards_large_mid"],
        "demand_large_mid": values["demand_large_mid"],
        "standards_small": values["standards_small"],
        "demand_small": values["demand_small"],
        "term_tightness": term_tightness,
        "supply_breadth": _breadth(pd.concat([supply, terms], axis=1)),
        "demand_breadth": _breadth(demand),
        "supply_demand_gap": supply.mean(axis=1) - demand.mean(axis=1),
        "composite_tightness": pd.concat([supply, terms], axis=1).mean(axis=1)
        - demand.mean(axis=1),
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="supply_demand_gap",
        window=_positive(parameters, "window", 8),
        label="sloos_f200",
    )


_EVALUATORS: Mapping[
    str,
    Callable[[pd.DataFrame, Mapping[str, pd.DataFrame], Mapping[str, Any]], pd.DataFrame],
] = {
    "F191": _f191,
    "F192": _f192,
    "F193": _f193,
    "F194": _f194,
    "F195": _f195,
    "F196": _f196,
    "F197": _f197,
    "F198": _f198,
    "F199": _f199,
    "F200": _f200,
}


_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F191": {"statistic": "output_growth", "window": 8},
    "F192": {"statistic": "household_breadth", "window": 8},
    "F193": {"statistic": "housing_investment_composite", "window": 24, "lag": 3},
    "F194": {"statistic": "inflation_breadth", "window": 24},
    "F195": {"statistic": "labor_composite", "window": 126},
    "F196": {"statistic": "production_breadth", "window": 24, "lag": 3},
    "F197": {"statistic": "macro_outlook_composite", "window": 8},
    "F198": {"statistic": "macro_disagreement", "window": 8},
    "F199": {"statistic": "rolling_absolute_error", "window": 8},
    "F200": {"statistic": "supply_demand_gap", "window": 8},
}


def evaluate_realtime_survey_lane(
    lane_id: str,
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F191-F200 lane on train-only causal panels."""

    try:
        evaluator = _EVALUATORS[lane_id]
    except KeyError as exc:
        raise RealtimeSurveyFeatureEngineError(f"UNKNOWN_LANE:{lane_id}") from exc
    market_valid = _validated(market, label="market")
    required = _LANE_SOURCES[lane_id]
    missing = sorted(set(required) - set(panels))
    if missing:
        raise RealtimeSurveyFeatureEngineError(
            f"MISSING_REQUIRED_PANELS:{lane_id}:{','.join(missing)}"
        )
    validated_panels = {
        name: _validated(panels[name], label=name)
        for name in required
    }
    result = evaluator(market_valid, validated_panels, parameters)
    if tuple(result.columns) != ("date", "observed_at", "available_at", "value"):
        raise RealtimeSurveyFeatureEngineError(f"INVALID_OUTPUT_COLUMNS:{lane_id}")
    return result


def evaluate_realtime_survey_family_batch(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate the frozen representative configuration for every F191-F200 lane."""

    return {
        lane_id: evaluate_realtime_survey_lane(
            lane_id,
            market,
            panels,
            {
                **parameters,
                "normalization": "raw",
                "change_lag": 1,
                "direction": "continuation",
            },
        )
        for lane_id, parameters in _BATCH_PARAMETERS.items()
    }


__all__ = [
    "RealtimeSurveyFeatureEngineError",
    "evaluate_realtime_survey_family_batch",
    "evaluate_realtime_survey_lane",
]
