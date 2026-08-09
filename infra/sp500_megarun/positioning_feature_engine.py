"""Causal financing, positioning and volatility kernels for lanes F081-F090."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class PositioningFeatureEngineError(ValueError):
    """Raised when a positioning input violates the frozen train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_EPSILON = 1e-12


def _validated_panel(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PositioningFeatureEngineError(
            f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}"
        )
    panel = frame.copy()
    for column in required:
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.normalize()
    if panel[list(required)].isna().any().any():
        raise PositioningFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(_TRAIN_END).any():
        raise PositioningFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any():
        raise PositioningFeatureEngineError(
            f"PANEL_NOT_AVAILABLE_AT_DECISION:{name}"
        )
    if panel["observed_at"].gt(panel["available_at"]).any():
        raise PositioningFeatureEngineError(
            f"PANEL_OBSERVED_AFTER_AVAILABILITY:{name}"
        )
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise PositioningFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _required_panel(
    panels: Mapping[str, pd.DataFrame], name: str
) -> pd.DataFrame:
    if name not in panels:
        raise PositioningFeatureEngineError(f"POSITIONING_PANELS_MISSING:{name}")
    return _validated_panel(name, panels[name])


def _numeric(panel: pd.DataFrame, column: str, *, panel_name: str) -> pd.Series:
    if column not in panel:
        raise PositioningFeatureEngineError(
            f"PANEL_VALUE_MISSING:{panel_name}:{column}"
        )
    return pd.to_numeric(panel[column], errors="coerce")


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise PositioningFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    deviation = values.rolling(window, min_periods=window).std(ddof=0)
    return (values - mean) / deviation.replace(0.0, np.nan)


def _causal_percentile(values: pd.Series, window: int) -> pd.Series:
    def midrank(segment: np.ndarray) -> float:
        if not np.isfinite(segment).all():
            return np.nan
        current = segment[-1]
        return float(
            np.mean(segment < current) + 0.5 * np.mean(segment == current)
        )

    return values.rolling(window, min_periods=window).apply(midrank, raw=True)


def _align(master: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    left = master.loc[:, ["date"]].sort_values("date", kind="mergesort")
    right = updates.sort_values("date", kind="mergesort")
    aligned = pd.merge_asof(left, right, on="date", direction="backward")
    stale_future = aligned["available_at"].gt(aligned["date"])
    if stale_future.fillna(False).any():
        raise PositioningFeatureEngineError("FORWARD_FILLED_FUTURE_POSITIONING_INPUT")
    return aligned


def _max_observed(panels: Sequence[pd.DataFrame]) -> pd.Series:
    return pd.concat([panel["observed_at"] for panel in panels], axis=1).max(axis=1)


def _output(
    master: pd.DataFrame,
    value: pd.Series | np.ndarray,
    *,
    observed_panels: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": master["date"],
            "observed_at": _max_observed(observed_panels),
            "available_at": master["date"],
            "value": pd.to_numeric(
                pd.Series(value, index=master.index), errors="coerce"
            ).replace([np.inf, -np.inf], np.nan),
        }
    )


def _score_update(
    panel: pd.DataFrame,
    values: pd.Series,
    *,
    lag: int,
    window: int,
) -> pd.DataFrame:
    scored = panel.loc[:, ["date", "observed_at", "available_at"]].copy()
    scored["score"] = _rolling_z(values.diff(lag), window)
    return scored


def _f081(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    balance = _required_panel(panels, "balance")
    margin = _required_panel(panels, "finra_margin")
    daily_window = _positive_int(parameters, "daily_window", 63)
    balance_lag = _positive_int(parameters, "balance_lag", 1)
    balance_window = _positive_int(parameters, "balance_window", 4)
    margin_lag = _positive_int(parameters, "margin_lag", 1)
    margin_window = _positive_int(parameters, "margin_window", 6)
    close = _numeric(spy, "close", panel_name="spy")
    volume = _numeric(spy, "volume", panel_name="spy")
    returns = np.log(close).diff()
    volume_score = np.sign(returns) * _rolling_z(
        np.log(close * volume), daily_window
    )
    balance_level = 0.5 * (
        _numeric(balance, "household_equity_share", panel_name="balance")
        + _numeric(balance, "mutual_fund_equity_share", panel_name="balance")
    )
    balance_score = _score_update(
        balance,
        balance_level,
        lag=balance_lag,
        window=balance_window,
    )
    margin_level = np.log(
        _numeric(margin, "margin_debit_to_credit", panel_name="margin")
    )
    margin_score = _score_update(
        margin,
        margin_level,
        lag=margin_lag,
        window=margin_window,
    )
    aligned_balance = _align(spy, balance_score)
    aligned_margin = _align(spy, margin_score)
    components = pd.DataFrame(
        {
            "volume": volume_score,
            "balance": aligned_balance["score"],
            "margin": aligned_margin["score"],
        }
    )
    aggregation = str(parameters.get("aggregation", "equal"))
    weights = {
        "equal": np.array([1.0, 1.0, 1.0]) / 3.0,
        "financing": np.array([0.25, 0.25, 0.5]),
        "allocation": np.array([0.25, 0.5, 0.25]),
    }.get(aggregation)
    if weights is None:
        raise PositioningFeatureEngineError(
            f"F081_UNKNOWN_AGGREGATION:{aggregation}"
        )
    value = components @ weights
    value = value.where(components.notna().all(axis=1))
    return _output(
        spy,
        value,
        observed_panels=(spy, aligned_balance, aligned_margin),
    )


def _f082(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    margin = _required_panel(panels, "margin")
    window = _positive_int(parameters, "window", 12)
    lag = _positive_int(parameters, "lag", 1)
    ratio = np.log(
        _numeric(margin, "margin_debit_to_credit", panel_name="margin")
    )
    statistic = str(parameters.get("statistic", "level"))
    if statistic == "level":
        value = _rolling_z(ratio, window)
    elif statistic == "change":
        value = _rolling_z(ratio.diff(lag), window)
    elif statistic == "debit_growth":
        debit = np.log(_numeric(margin, "margin_debit", panel_name="margin"))
        value = _rolling_z(debit.diff(lag), window)
    elif statistic == "percentile":
        value = 2.0 * _causal_percentile(ratio, window) - 1.0
    else:
        raise PositioningFeatureEngineError(f"F082_UNKNOWN_STATISTIC:{statistic}")
    direction = str(parameters.get("direction", "continuation"))
    if direction == "contrarian":
        value = -value
    elif direction != "continuation":
        raise PositioningFeatureEngineError(f"F082_UNKNOWN_DIRECTION:{direction}")
    return _output(margin, value, observed_panels=(margin,))


def _f083(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    cftc = _required_panel(panels, "cftc")
    window = _positive_int(parameters, "window", 26)
    lag = _positive_int(parameters, "lag", 1)
    noncommercial = _numeric(
        cftc, "noncommercial_short_pct_oi", panel_name="cftc"
    )
    reportable = _numeric(cftc, "reportable_short_pct_oi", panel_name="cftc")
    statistic = str(parameters.get("statistic", "short_pressure"))
    if statistic == "noncommercial_short":
        pressure = _rolling_z(noncommercial, window)
    elif statistic == "reportable_short":
        pressure = _rolling_z(reportable, window)
    elif statistic == "short_pressure":
        pressure = _rolling_z((noncommercial + reportable).diff(lag) / 2.0, window)
    else:
        raise PositioningFeatureEngineError(f"F083_UNKNOWN_STATISTIC:{statistic}")
    direction = str(parameters.get("direction", "contrarian"))
    if direction == "continuation":
        value = -pressure
    elif direction == "contrarian":
        value = pressure
    else:
        raise PositioningFeatureEngineError(f"F083_UNKNOWN_DIRECTION:{direction}")
    return _output(cftc, value, observed_panels=(cftc,))


def _f084(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    balance = _required_panel(panels, "balance")
    margin = _required_panel(panels, "finra_margin")
    cftc = _required_panel(panels, "legacy_cftc")
    balance_window = _positive_int(parameters, "balance_window", 4)
    margin_window = _positive_int(parameters, "margin_window", 6)
    positioning_window = _positive_int(parameters, "positioning_window", 26)
    balance_level = 0.5 * (
        _numeric(balance, "household_equity_share", panel_name="balance")
        + _numeric(balance, "mutual_fund_equity_share", panel_name="balance")
    )
    balance_update = _score_update(
        balance, balance_level, lag=1, window=balance_window
    )
    margin_update = _score_update(
        margin,
        np.log(_numeric(margin, "margin_debit_to_credit", panel_name="margin")),
        lag=1,
        window=margin_window,
    )
    positioning = _rolling_z(
        _numeric(cftc, "noncommercial_net_pct_oi", panel_name="cftc").diff(),
        positioning_window,
    )
    aligned_balance = _align(cftc, balance_update)
    aligned_margin = _align(cftc, margin_update)
    components = pd.DataFrame(
        {
            "balance": aligned_balance["score"],
            "margin": aligned_margin["score"],
            "positioning": positioning,
        }
    )
    statistic = str(parameters.get("statistic", "aggregate_flow"))
    if statistic == "aggregate_flow":
        value = components.mean(axis=1)
    elif statistic == "financing_pressure":
        value = components[["margin", "positioning"]].mean(axis=1)
    elif statistic == "allocation_pressure":
        value = components[["balance", "positioning"]].mean(axis=1)
    elif statistic == "disagreement":
        agreement = (1.0 - components.std(axis=1, ddof=0).clip(0.0, 2.0) / 2.0)
        value = components.mean(axis=1) * agreement
    else:
        raise PositioningFeatureEngineError(f"F084_UNKNOWN_STATISTIC:{statistic}")
    value = value.where(components.notna().all(axis=1))
    return _output(
        cftc,
        value,
        observed_panels=(cftc, aligned_balance, aligned_margin),
    )


def _f085(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    window = _positive_int(parameters, "window", 63)
    high = _numeric(spy, "high", panel_name="spy")
    low = _numeric(spy, "low", panel_name="spy")
    close = _numeric(spy, "close", panel_name="spy")
    volume = _numeric(spy, "volume", panel_name="spy")
    bar_range = (high - low).clip(lower=_EPSILON)
    close_location = (2.0 * close - high - low) / bar_range
    range_score = _rolling_z(np.log(bar_range), window)
    volume_score = _rolling_z(np.log(volume), window)
    statistic = str(parameters.get("statistic", "close_location"))
    if statistic == "close_location":
        value = close_location
    elif statistic == "range_volume_pressure":
        value = close_location * np.tanh(0.5 * (range_score + volume_score))
    elif statistic == "signed_volume_shock":
        value = close_location * volume_score.abs()
    elif statistic == "persistence":
        value = close_location.rolling(window, min_periods=window).mean()
    else:
        raise PositioningFeatureEngineError(f"F085_UNKNOWN_STATISTIC:{statistic}")
    return _output(spy, value.clip(-10.0, 10.0), observed_panels=(spy,))


def _f086(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    cftc = _required_panel(panels, "cftc")
    spy = _align(cftc, _required_panel(panels, "spy"))
    window = _positive_int(parameters, "window", 26)
    lag = _positive_int(parameters, "lag", 1)
    futures = _numeric(cftc, "open_interest", panel_name="cftc")
    combined = _numeric(cftc, "open_interest_combined", panel_name="cftc")
    gap = ((combined - futures) / combined.replace(0.0, np.nan)).clip(0.0, 1.0)
    statistic = str(parameters.get("statistic", "participation_gap"))
    if statistic == "participation_gap":
        value = gap
    elif statistic == "change":
        value = _rolling_z(gap.diff(lag), window)
    elif statistic == "volume_scaled":
        gap_score = _rolling_z(gap.diff(lag), window)
        volume_score = _rolling_z(
            np.log(_numeric(spy, "volume", panel_name="spy")), window
        )
        value = gap_score * (1.0 + 0.5 * np.tanh(volume_score))
    else:
        raise PositioningFeatureEngineError(f"F086_UNKNOWN_STATISTIC:{statistic}")
    return _output(cftc, value, observed_panels=(cftc, spy))


def _f087(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    cftc = _required_panel(panels, "cftc")
    window = _positive_int(parameters, "window", 26)
    lag = _positive_int(parameters, "lag", 1)
    noncommercial_gap = _numeric(
        cftc, "noncommercial_net_pct_oi_combined", panel_name="cftc"
    ) - _numeric(cftc, "noncommercial_net_pct_oi", panel_name="cftc")
    commercial_gap = _numeric(
        cftc, "commercial_net_pct_oi_combined", panel_name="cftc"
    ) - _numeric(cftc, "commercial_net_pct_oi", panel_name="cftc")
    futures = _numeric(cftc, "open_interest", panel_name="cftc")
    combined = _numeric(cftc, "open_interest_combined", panel_name="cftc")
    statistic = str(parameters.get("statistic", "noncommercial_gap"))
    if statistic == "noncommercial_gap":
        value = noncommercial_gap
    elif statistic == "commercial_gap":
        value = commercial_gap
    elif statistic == "gap_change":
        value = _rolling_z(noncommercial_gap.diff(lag), window)
    elif statistic == "open_interest_share":
        value = ((combined - futures) / combined.replace(0.0, np.nan)).clip(
            0.0, 1.0
        )
    else:
        raise PositioningFeatureEngineError(f"F087_UNKNOWN_STATISTIC:{statistic}")
    direction = str(parameters.get("direction", "continuation"))
    if direction == "contrarian":
        value = -value
    elif direction != "continuation":
        raise PositioningFeatureEngineError(f"F087_UNKNOWN_DIRECTION:{direction}")
    return _output(cftc, value, observed_panels=(cftc,))


def _f088(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    cftc = _required_panel(panels, "cftc")
    window = _positive_int(parameters, "window", 26)
    lag = _positive_int(parameters, "lag", 1)
    top4 = _numeric(cftc, "top4_net_concentration", panel_name="cftc").abs()
    top8 = _numeric(cftc, "top8_net_concentration", panel_name="cftc").abs()
    top4_combined = _numeric(
        cftc, "top4_net_concentration_combined", panel_name="cftc"
    ).abs()
    top8_combined = _numeric(
        cftc, "top8_net_concentration_combined", panel_name="cftc"
    ).abs()
    statistic = str(parameters.get("statistic", "top4_top8_share"))
    if statistic == "top4_level":
        value = _rolling_z(top4_combined, window)
    elif statistic == "top8_level":
        value = _rolling_z(top8_combined, window)
    elif statistic == "top4_top8_share":
        value = (top4_combined / top8_combined.replace(0.0, np.nan)).clip(0.0, 2.0)
    elif statistic == "combined_gap":
        value = _rolling_z(top4_combined - top4, window)
    elif statistic == "change":
        value = _rolling_z((top8_combined - top8).diff(lag), window)
    else:
        raise PositioningFeatureEngineError(f"F088_UNKNOWN_STATISTIC:{statistic}")
    return _output(cftc, value, observed_panels=(cftc,))


def _f089(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    vol = _align(spy, _required_panel(panels, "vol"))
    window = _positive_int(parameters, "window", 63)
    change_lag = _positive_int(parameters, "change_lag", 5)
    vix = _numeric(vol, "vix_close", panel_name="vol")
    vxo = _numeric(vol, "vxo_close", panel_name="vol")
    disagreement = np.log(vix / vxo)
    disagreement_state = _rolling_z(
        disagreement + disagreement.diff(change_lag), window
    )
    returns = np.log(_numeric(spy, "close", panel_name="spy")).diff()
    squared = returns.pow(2)
    downside = squared.where(returns.lt(0.0), 0.0).where(returns.notna()).rolling(
        window, min_periods=window
    ).sum()
    upside = squared.where(returns.ge(0.0), 0.0).where(returns.notna()).rolling(
        window, min_periods=window
    ).sum()
    asymmetry = (downside - upside) / (downside + upside + _EPSILON)
    asymmetry_state = _rolling_z(asymmetry, window)
    statistic = str(parameters.get("statistic", "composite"))
    if statistic == "vix_vxo_disagreement":
        value = disagreement_state
    elif statistic == "realized_asymmetry":
        value = asymmetry
    elif statistic == "composite":
        value = 0.5 * (disagreement_state + asymmetry_state)
    elif statistic == "divergence":
        value = disagreement_state - asymmetry_state
    else:
        raise PositioningFeatureEngineError(f"F089_UNKNOWN_STATISTIC:{statistic}")
    direction = str(parameters.get("direction", "contrarian"))
    if direction == "contrarian":
        value = -value
    elif direction != "continuation":
        raise PositioningFeatureEngineError(f"F089_UNKNOWN_DIRECTION:{direction}")
    return _output(spy, value.clip(-20.0, 20.0), observed_panels=(spy, vol))


def _f090(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    vol = _align(spy, _required_panel(panels, "vol"))
    industries = _align(spy, _required_panel(panels, "industries"))
    window = _positive_int(parameters, "window", 63)
    excluded = {"date", "observed_at", "available_at"}
    industry_columns = [
        column for column in industries.columns if column not in excluded
    ]
    if len(industry_columns) < 2:
        raise PositioningFeatureEngineError("F090_INSUFFICIENT_INDUSTRIES")
    returns = industries[industry_columns].apply(pd.to_numeric, errors="coerce")
    rolling_minimum = max(2, int(np.ceil(0.9 * window)))
    mean = returns.rolling(window, min_periods=rolling_minimum).mean()
    deviation = returns.rolling(window, min_periods=rolling_minimum).std(ddof=0)
    standardized = (returns - mean) / deviation.replace(0.0, np.nan)
    available_count = standardized.notna().sum(axis=1).astype(float)
    minimum_industries = max(2, int(np.ceil(0.8 * len(industry_columns))))
    daily_pair_product = (
        standardized.sum(axis=1).pow(2) - standardized.pow(2).sum(axis=1)
    ) / (available_count * (available_count - 1.0))
    daily_pair_product = daily_pair_product.where(
        available_count.ge(float(minimum_industries))
    )
    common_correlation = daily_pair_product.rolling(
        window, min_periods=rolling_minimum
    ).mean().clip(-1.0, 1.0)
    # Preserve the original two-complete-window warm-up on uninterrupted data;
    # the relaxed counts above apply only to later isolated source gaps.
    warmup_rows = min(len(common_correlation), 2 * window - 2)
    common_correlation.iloc[:warmup_rows] = np.nan
    vix = _numeric(vol, "vix_close", panel_name="vol")
    spy_return = np.log(_numeric(spy, "close", panel_name="spy")).diff()
    realized_variance = 252.0 * spy_return.pow(2).rolling(
        window, min_periods=window
    ).mean()
    variance_gap = (vix / 100.0).pow(2) - realized_variance
    correlation_state = _rolling_z(common_correlation, window)
    variance_state = _rolling_z(variance_gap, window)
    statistic = str(parameters.get("statistic", "common_correlation"))
    if statistic == "common_correlation":
        value = common_correlation
    elif statistic == "variance_gap":
        value = variance_state
    elif statistic == "correlation_gap":
        value = correlation_state - variance_state
    elif statistic == "interaction":
        value = (correlation_state * variance_state).clip(-20.0, 20.0)
    else:
        raise PositioningFeatureEngineError(f"F090_UNKNOWN_STATISTIC:{statistic}")
    return _output(
        spy,
        value,
        observed_panels=(spy, vol, industries),
    )


def evaluate_positioning_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one F081-F090 formula using only published train information."""

    evaluators = {
        "F081": _f081,
        "F082": _f082,
        "F083": _f083,
        "F084": _f084,
        "F085": _f085,
        "F086": _f086,
        "F087": _f087,
        "F088": _f088,
        "F089": _f089,
        "F090": _f090,
    }
    try:
        evaluator = evaluators[lane_id]
    except KeyError as exc:
        raise PositioningFeatureEngineError(
            f"POSITIONING_LANE_NOT_IMPLEMENTED:{lane_id}"
        ) from exc
    return evaluator(input_panels, parameters)


_POSITIONING_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F081": {
        "daily_window": 126,
        "balance_lag": 1,
        "balance_window": 4,
        "margin_lag": 1,
        "margin_window": 6,
        "aggregation": "equal",
    },
    "F082": {
        "statistic": "change",
        "window": 6,
        "lag": 1,
        "direction": "continuation",
    },
    "F083": {
        "statistic": "short_pressure",
        "window": 13,
        "lag": 1,
        "direction": "contrarian",
    },
    "F084": {
        "statistic": "aggregate_flow",
        "balance_window": 4,
        "margin_window": 6,
        "positioning_window": 13,
    },
    "F085": {"statistic": "signed_volume_shock", "window": 126},
    "F086": {"statistic": "participation_gap", "window": 26, "lag": 1},
    "F087": {
        "statistic": "noncommercial_gap",
        "window": 26,
        "lag": 1,
        "direction": "continuation",
    },
    "F088": {"statistic": "top4_top8_share", "window": 26, "lag": 1},
    "F089": {
        "statistic": "composite",
        "window": 126,
        "change_lag": 5,
        "direction": "contrarian",
    },
    "F090": {"statistic": "interaction", "window": 126},
}


def evaluate_positioning_family_batch(
    input_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for every F081-F090 lane."""

    return {
        lane_id: evaluate_positioning_lane(lane_id, input_panels, parameters)
        for lane_id, parameters in _POSITIONING_BATCH_PARAMETERS.items()
    }


__all__ = [
    "PositioningFeatureEngineError",
    "evaluate_positioning_family_batch",
    "evaluate_positioning_lane",
]
