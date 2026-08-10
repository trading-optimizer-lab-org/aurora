"""Causal characteristic-portfolio kernels for SP500 lanes F151-F160."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


class CharacteristicFeatureEngineError(ValueError):
    """Raised when characteristic inputs or parameters break the frozen contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_STANDARD_ENDPOINTS = {
    3: ("Lo 30", "Hi 30"),
    5: ("Lo 20", "Hi 20"),
    10: ("Lo 10", "Hi 10"),
}
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F151": ("size_daily",),
    "F152": ("book_to_market_daily",),
    "F153": ("profitability_daily",),
    "F154": ("investment_daily",),
    "F155": ("momentum_10_daily",),
    "F156": ("short_reversal_10_daily",),
    "F157": ("long_reversal_10_daily",),
    "F158": ("beta_monthly",),
    "F159": ("variance_monthly", "residual_variance_monthly"),
    "F160": ("accruals_monthly", "net_share_issues_monthly"),
}
_STATISTICS = {
    "mean_spread",
    "t_stat",
    "cumulative_log_spread",
    "win_rate",
}
_EPSILON = 1e-12


def _timestamps(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CharacteristicFeatureEngineError(
            f"MISSING_TIMESTAMP_COLUMNS:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in required:
        result[column] = pd.to_datetime(
            result[column], errors="coerce"
        ).dt.normalize()
    if result[list(required)].isna().any().any():
        raise CharacteristicFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(
        _TRAIN_END
    ).any():
        row_kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise CharacteristicFeatureEngineError(f"NON_TRAIN_{row_kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise CharacteristicFeatureEngineError(
            f"OBSERVED_AFTER_AVAILABILITY:{label}"
        )
    if result["available_at"].gt(result["date"]).any():
        raise CharacteristicFeatureEngineError(f"AVAILABLE_AFTER_PANEL_DATE:{label}")
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise CharacteristicFeatureEngineError(f"DATES_NOT_STRICTLY_ORDERED:{label}")
    return result.reset_index(drop=True)


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise CharacteristicFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _bins(parameters: Mapping[str, Any]) -> int:
    bins = int(parameters.get("bins", 10))
    if bins not in _STANDARD_ENDPOINTS:
        raise CharacteristicFeatureEngineError(f"UNKNOWN_PORTFOLIO_BINS:{bins}")
    return bins


def _standard_endpoints(
    panel: pd.DataFrame,
    *,
    bins: int,
    resource_id: str,
) -> tuple[str, str]:
    low, high = _STANDARD_ENDPOINTS[bins]
    missing = [column for column in (low, high) if column not in panel]
    if missing:
        raise CharacteristicFeatureEngineError(
            f"MISSING_PORTFOLIO_ENDPOINTS:{resource_id}:{bins}:{','.join(missing)}"
        )
    return low, high


def _prior_endpoints(panel: pd.DataFrame, *, resource_id: str) -> tuple[str, str]:
    alternatives = (
        ("Lo PRIOR", "Hi PRIOR"),
        ("Lo 10", "Hi 10"),
    )
    for low, high in alternatives:
        if low in panel and high in panel:
            return low, high
    raise CharacteristicFeatureEngineError(
        f"MISSING_PRIOR_RETURN_ENDPOINTS:{resource_id}"
    )


def _numeric(panel: pd.DataFrame, column: str, resource_id: str) -> pd.Series:
    values = pd.to_numeric(panel[column], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    if values.notna().sum() < 2:
        raise CharacteristicFeatureEngineError(
            f"EMPTY_PORTFOLIO_COLUMN:{resource_id}:{column}"
        )
    return values


def _spread_statistic(
    panel: pd.DataFrame,
    *,
    long_column: str,
    short_column: str,
    resource_id: str,
    parameters: Mapping[str, Any],
) -> pd.Series:
    window = _positive_int(parameters, "window", 63)
    statistic = str(parameters.get("statistic", "t_stat"))
    if statistic not in _STATISTICS:
        raise CharacteristicFeatureEngineError(
            f"UNKNOWN_SPREAD_STATISTIC:{statistic}"
        )
    long_return = _numeric(panel, long_column, resource_id)
    short_return = _numeric(panel, short_column, resource_id)
    spread = long_return - short_return
    rolling = spread.rolling(window, min_periods=window)
    mean = rolling.mean()
    if statistic == "mean_spread":
        return mean
    if statistic == "t_stat":
        standard_error = rolling.std(ddof=0) / np.sqrt(float(window))
        return mean / standard_error.where(standard_error.abs().gt(_EPSILON))
    if statistic == "cumulative_log_spread":
        valid = long_return.gt(-1.0) & short_return.gt(-1.0)
        relative_log_return = pd.Series(np.nan, index=panel.index, dtype=float)
        relative_log_return.loc[valid] = (
            np.log1p(long_return.loc[valid]) - np.log1p(short_return.loc[valid])
        )
        return relative_log_return.rolling(window, min_periods=window).sum()
    wins = spread.gt(0.0).where(spread.notna())
    return wins.rolling(window, min_periods=window).mean() - 0.5


def _project_to_market(
    market: pd.DataFrame,
    panel: pd.DataFrame,
    value: pd.Series,
) -> pd.DataFrame:
    right = pd.DataFrame(
        {
            "source_date": panel["date"],
            "source_observed_at": panel["observed_at"],
            "source_available_at": panel["available_at"],
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    ).sort_values("source_date", kind="mergesort")
    joined = pd.merge_asof(
        market.loc[:, ["date", "observed_at", "available_at"]],
        right,
        left_on="date",
        right_on="source_date",
        direction="backward",
        allow_exact_matches=True,
    )
    return pd.DataFrame(
        {
            "date": joined["date"],
            "observed_at": joined["source_observed_at"].fillna(
                joined["observed_at"]
            ),
            "available_at": joined["source_available_at"].fillna(
                joined["available_at"]
            ),
            "value": joined["value"],
        }
    )


def _single_spread(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    *,
    resource_id: str,
    long_side: str,
    prior_returns: bool,
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    panel = panels[resource_id]
    low, high = (
        _prior_endpoints(panel, resource_id=resource_id)
        if prior_returns
        else _standard_endpoints(
            panel, bins=_bins(parameters), resource_id=resource_id
        )
    )
    if long_side == "low":
        long_column, short_column = low, high
    elif long_side == "high":
        long_column, short_column = high, low
    else:  # pragma: no cover - only frozen internal calls use this helper
        raise CharacteristicFeatureEngineError(f"UNKNOWN_LONG_SIDE:{long_side}")
    value = _spread_statistic(
        panel,
        long_column=long_column,
        short_column=short_column,
        resource_id=resource_id,
        parameters=parameters,
    )
    return _project_to_market(market, panel, value)


def _combine(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    mode: str,
) -> pd.DataFrame:
    if not left["date"].equals(right["date"]):
        raise CharacteristicFeatureEngineError("COMPONENT_DATE_MISMATCH")
    if mode == "mean":
        value = pd.concat((left["value"], right["value"]), axis=1).mean(
            axis=1, skipna=False
        )
    elif mode == "disagreement":
        value = left["value"] - right["value"]
    else:
        raise CharacteristicFeatureEngineError(f"UNKNOWN_COMPONENT_MODE:{mode}")
    return pd.DataFrame(
        {
            "date": left["date"],
            "observed_at": pd.concat(
                (left["observed_at"], right["observed_at"]), axis=1
            ).max(axis=1),
            "available_at": pd.concat(
                (left["available_at"], right["available_at"]), axis=1
            ).max(axis=1),
            "value": value,
        }
    )


def evaluate_characteristic_lane(
    lane_id: str,
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen lane using only already-released portfolio returns."""

    if lane_id not in _LANE_SOURCES:
        raise CharacteristicFeatureEngineError(
            f"UNKNOWN_CHARACTERISTIC_LANE:{lane_id}"
        )
    market = _timestamps(market_frame, label="market")
    missing = [source for source in _LANE_SOURCES[lane_id] if source not in raw_panels]
    if missing:
        raise CharacteristicFeatureEngineError(
            f"MISSING_CHARACTERISTIC_PANEL:{lane_id}:{','.join(missing)}"
        )
    panels = {
        source: _timestamps(raw_panels[source], label=source)
        for source in _LANE_SOURCES[lane_id]
    }
    simple = {
        "F151": ("size_daily", "low", False),
        "F152": ("book_to_market_daily", "high", False),
        "F153": ("profitability_daily", "high", False),
        "F154": ("investment_daily", "low", False),
        "F155": ("momentum_10_daily", "high", True),
        "F156": ("short_reversal_10_daily", "low", True),
        "F157": ("long_reversal_10_daily", "low", True),
        "F158": ("beta_monthly", "high", False),
    }
    if lane_id in simple:
        resource_id, long_side, prior_returns = simple[lane_id]
        return _single_spread(
            market,
            panels,
            resource_id=resource_id,
            long_side=long_side,
            prior_returns=prior_returns,
            parameters=parameters,
        )

    if lane_id == "F159":
        left_name, right_name = "variance_monthly", "residual_variance_monthly"
        single_modes = {"total": left_name, "residual": right_name}
    else:
        left_name, right_name = "accruals_monthly", "net_share_issues_monthly"
        single_modes = {"accruals": left_name, "net_share_issues": right_name}
    long_side = "high" if lane_id == "F159" else "low"
    left = _single_spread(
        market,
        panels,
        resource_id=left_name,
        long_side=long_side,
        prior_returns=False,
        parameters=parameters,
    )
    right = _single_spread(
        market,
        panels,
        resource_id=right_name,
        long_side=long_side,
        prior_returns=False,
        parameters=parameters,
    )
    component = str(parameters.get("component", "mean"))
    if component in single_modes:
        return left if single_modes[component] == left_name else right
    return _combine(left, right, mode=component)


_DEFAULT_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F151": {"statistic": "t_stat", "window": 63, "bins": 10},
    "F152": {"statistic": "t_stat", "window": 63, "bins": 10},
    "F153": {"statistic": "t_stat", "window": 63, "bins": 10},
    "F154": {"statistic": "t_stat", "window": 63, "bins": 10},
    "F155": {"statistic": "t_stat", "window": 63},
    "F156": {"statistic": "t_stat", "window": 63},
    "F157": {"statistic": "t_stat", "window": 63},
    "F158": {"statistic": "t_stat", "window": 24, "bins": 10},
    "F159": {
        "statistic": "t_stat",
        "window": 24,
        "bins": 10,
        "component": "mean",
    },
    "F160": {
        "statistic": "t_stat",
        "window": 24,
        "bins": 10,
        "component": "mean",
    },
}


def evaluate_characteristic_family_batch(
    market_frame: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate the ten frozen characteristic defaults in stable lane order."""

    return {
        lane: evaluate_characteristic_lane(
            lane, market_frame, panels, parameters
        )
        for lane, parameters in _DEFAULT_PARAMETERS.items()
    }


__all__ = [
    "CharacteristicFeatureEngineError",
    "evaluate_characteristic_family_batch",
    "evaluate_characteristic_lane",
]
