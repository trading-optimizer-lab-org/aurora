"""Causal execution kernels for SP500 market-state families F021-F031."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class MarketFeatureEngineError(ValueError):
    """Raised when a market feature input crosses the train-only boundary."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_PANEL_NAMES = ("spy", "cboe", "cftc", "rates")


def _validated_panel(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MarketFeatureEngineError(f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}")
    panel = frame.copy()
    for column in ("date", "observed_at", "available_at"):
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.normalize()
    if panel[["date", "observed_at", "available_at"]].isna().any().any():
        raise MarketFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(_TRAIN_END).any():
        raise MarketFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any():
        raise MarketFeatureEngineError(f"PANEL_NOT_AVAILABLE_AT_DECISION:{name}")
    if panel["observed_at"].gt(panel["available_at"]).any():
        raise MarketFeatureEngineError(f"PANEL_OBSERVED_AFTER_AVAILABILITY:{name}")
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise MarketFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _aligned_panels(panels: Mapping[str, pd.DataFrame]) -> Mapping[str, pd.DataFrame]:
    missing = sorted(set(_PANEL_NAMES) - set(panels))
    if missing:
        raise MarketFeatureEngineError(f"MARKET_PANELS_MISSING:{','.join(missing)}")
    validated = {name: _validated_panel(name, panels[name]) for name in _PANEL_NAMES}
    if "close" not in validated["spy"]:
        raise MarketFeatureEngineError("SPY_CLOSE_MISSING")
    calendar = pd.DatetimeIndex(validated["spy"]["date"])
    aligned: dict[str, pd.DataFrame] = {"spy": validated["spy"]}
    for name in ("cboe", "cftc", "rates"):
        panel = validated[name].set_index("date").reindex(calendar).ffill()
        panel.index.name = "date"
        panel = panel.reset_index()
        stale_future = panel["available_at"].gt(panel["date"])
        if stale_future.fillna(False).any():
            raise MarketFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{name}")
        aligned[name] = panel
    return aligned


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    deviation = values.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    return (values - mean) / deviation


def _observed_at(
    panels: Mapping[str, pd.DataFrame],
    names: Sequence[str],
) -> pd.Series:
    observations = pd.concat(
        [panels[name]["observed_at"] for name in names],
        axis=1,
    )
    return observations.max(axis=1)


def _output(
    panels: Mapping[str, pd.DataFrame],
    value: pd.Series,
    *,
    input_names: Sequence[str],
) -> pd.DataFrame:
    dates = panels["spy"]["date"]
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": _observed_at(panels, input_names),
            "available_at": dates,
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def evaluate_market_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F021-F031 formula at each causal decision session."""

    panels = _aligned_panels(input_panels)
    spy = panels["spy"]
    cboe = panels["cboe"]
    cftc = panels["cftc"]
    rates = panels["rates"]
    close = pd.to_numeric(spy["close"], errors="coerce")
    returns = close.pct_change(fill_method=None)
    window = int(parameters.get("window", 63))

    if lane_id == "F021":
        value = _rolling_z(pd.to_numeric(cboe["vix_close"], errors="coerce"), window)
        inputs = ("cboe",)
    elif lane_id == "F022":
        vix_state = _rolling_z(pd.to_numeric(cboe["vix_close"], errors="coerce"), window)
        return_state = _rolling_z(returns, window)
        value = vix_state - return_state
        inputs = ("spy", "cboe")
    elif lane_id == "F023":
        ratio = np.log(
            pd.to_numeric(cboe["vix_close"], errors="coerce")
            / pd.to_numeric(cboe["vxo_close"], errors="coerce").replace(0.0, np.nan)
        )
        value = _rolling_z(ratio, window)
        inputs = ("cboe",)
    elif lane_id == "F024":
        relative_change = pd.to_numeric(
            cboe["vix_close"], errors="coerce"
        ).pct_change(fill_method=None) - pd.to_numeric(
            cboe["vxo_close"], errors="coerce"
        ).pct_change(fill_method=None)
        value = _rolling_z(relative_change, window)
        inputs = ("cboe",)
    elif lane_id == "F025":
        futures = pd.to_numeric(cftc["noncommercial_net_pct_oi"], errors="coerce")
        combined_column = cftc.get("noncommercial_net_pct_oi_combined")
        if combined_column is None:
            positioning = futures
        else:
            combined = pd.to_numeric(combined_column, errors="coerce")
            positioning = (futures - combined).where(combined.notna(), futures)
        value = -_rolling_z(positioning, window)
        inputs = ("cftc",)
    elif lane_id == "F026":
        implied_variance = (
            pd.to_numeric(cboe["vix_close"], errors="coerce") / 100.0
        ).pow(2)
        realized_variance = returns.pow(2).rolling(
            window, min_periods=window
        ).mean() * 252.0
        value = _rolling_z(implied_variance - realized_variance, window)
        inputs = ("spy", "cboe")
    elif lane_id == "F027":
        positioning = pd.to_numeric(
            cftc["noncommercial_net_pct_oi"], errors="coerce"
        )
        price_momentum = close.pct_change(20, fill_method=None)
        value = _rolling_z(positioning, window) - _rolling_z(price_momentum, window)
        inputs = ("spy", "cftc")
    elif lane_id == "F028":
        open_interest = pd.to_numeric(cftc["open_interest"], errors="coerce")
        value = _rolling_z(open_interest.pct_change(5, fill_method=None), window)
        inputs = ("cftc",)
    elif lane_id == "F029":
        commercial = pd.to_numeric(cftc["commercial_net_pct_oi"], errors="coerce")
        noncommercial = pd.to_numeric(
            cftc["noncommercial_net_pct_oi"], errors="coerce"
        )
        concentration = pd.to_numeric(
            cftc["top4_net_concentration"], errors="coerce"
        )
        value = _rolling_z(commercial - noncommercial + concentration, window)
        inputs = ("cftc",)
    elif lane_id == "F030":
        ten_year = pd.to_numeric(rates["yield_10y"], errors="coerce")
        value = _rolling_z(ten_year.diff(5), window)
        inputs = ("rates",)
    elif lane_id == "F031":
        three_month = pd.to_numeric(rates["yield_3m"], errors="coerce")
        two_year = pd.to_numeric(rates["yield_2y"], errors="coerce")
        ten_year = pd.to_numeric(rates["yield_10y"], errors="coerce")
        slope = ten_year - two_year
        curvature = 2.0 * two_year - three_month - ten_year
        value = _rolling_z(slope + 0.5 * curvature, window)
        inputs = ("rates",)
    else:
        raise MarketFeatureEngineError(f"MARKET_LANE_NOT_IMPLEMENTED:{lane_id}")
    return _output(panels, value, input_names=inputs)


_MARKET_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F021": {"window": 63},
    "F022": {"window": 63},
    "F023": {"window": 63},
    "F024": {"window": 63},
    "F025": {"window": 63},
    "F026": {"window": 20},
    "F027": {"window": 63},
    "F028": {"window": 63},
    "F029": {"window": 63},
    "F030": {"window": 63},
    "F031": {"window": 63},
}


def evaluate_market_family_batch(
    input_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for F021-F031."""

    return {
        lane_id: evaluate_market_lane(lane_id, input_panels, parameters)
        for lane_id, parameters in _MARKET_BATCH_PARAMETERS.items()
    }


__all__ = [
    "MarketFeatureEngineError",
    "evaluate_market_family_batch",
    "evaluate_market_lane",
]
