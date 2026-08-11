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


def _rolling_percentile(values: pd.Series, window: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.rolling(window, min_periods=window).rank(pct=True) - 0.5


def _normalize(values: pd.Series, window: int, kind: str) -> pd.Series:
    if kind == "none":
        return pd.to_numeric(values, errors="coerce")
    if kind == "rolling_z":
        return _rolling_z(values, window)
    if kind == "rolling_percentile":
        return _rolling_percentile(values, window)
    raise MarketFeatureEngineError(f"UNKNOWN_NORMALIZATION:{kind}")


def _orient(values: pd.Series, direction: str) -> pd.Series:
    if direction == "continuation":
        return values
    if direction in {"reversal", "contrarian"}:
        return -values
    raise MarketFeatureEngineError(f"UNKNOWN_DIRECTION:{direction}")


_LANE_PARAMETERS: Mapping[str, frozenset[str]] = {
    "F021": frozenset({"window", "statistic", "normalization", "direction"}),
    "F022": frozenset({"window", "tail", "statistic", "direction"}),
    "F023": frozenset({"window", "form", "normalization"}),
    "F024": frozenset({"window", "statistic", "normalization", "direction"}),
    "F025": frozenset({"window", "statistic", "direction"}),
    "F026": frozenset({"window", "form", "normalization"}),
    "F027": frozenset({"window", "form", "normalization", "direction"}),
    "F028": frozenset({"window", "statistic", "direction"}),
    "F029": frozenset({"window", "statistic", "direction"}),
    "F030": frozenset({"window", "statistic", "normalization"}),
    "F031": frozenset({"window", "form", "normalization"}),
}


def _validate_parameters(lane_id: str, parameters: Mapping[str, Any]) -> None:
    allowed = _LANE_PARAMETERS.get(lane_id)
    if allowed is None:
        raise MarketFeatureEngineError(f"MARKET_LANE_NOT_IMPLEMENTED:{lane_id}")
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise MarketFeatureEngineError(
            f"UNKNOWN_PARAMETER:{lane_id}:{','.join(unknown)}"
        )


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

    _validate_parameters(lane_id, parameters)
    panels = _aligned_panels(input_panels)
    spy = panels["spy"]
    cboe = panels["cboe"]
    cftc = panels["cftc"]
    rates = panels["rates"]
    close = pd.to_numeric(spy["close"], errors="coerce")
    returns = close.pct_change(fill_method=None)
    window = int(parameters.get("window", 63))
    inputs: Sequence[str]

    if lane_id == "F021":
        vix = pd.to_numeric(cboe["vix_close"], errors="coerce")
        statistic = str(parameters.get("statistic", "level"))
        normalization = str(parameters.get("normalization", "rolling_z"))
        if statistic == "level":
            raw = (
                vix.rolling(window, min_periods=window).mean()
                if normalization == "none"
                else vix
            )
        elif statistic == "change":
            raw = vix.diff()
        elif statistic == "momentum":
            raw = vix.pct_change(window, fill_method=None)
        elif statistic == "percentile":
            raw = _rolling_percentile(vix, window)
        elif statistic == "shock":
            raw = vix.pct_change(fill_method=None).abs()
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F021:{statistic}")
        value = _orient(
            _normalize(raw, window, normalization),
            str(parameters.get("direction", "continuation")),
        )
        inputs = ("cboe",)
    elif lane_id == "F022":
        tail = float(parameters.get("tail", 0.05))
        if not 0.0 < tail < 0.5:
            raise MarketFeatureEngineError(f"INVALID_TAIL:F022:{tail}")
        vix_change = pd.to_numeric(
            cboe["vix_close"], errors="coerce"
        ).pct_change(fill_method=None)
        losses = -returns
        vix_cutoff = vix_change.rolling(window, min_periods=window).quantile(1.0 - tail)
        loss_cutoff = losses.rolling(window, min_periods=window).quantile(1.0 - tail)
        extreme = vix_change.ge(vix_cutoff) | losses.ge(loss_cutoff)
        statistic = str(parameters.get("statistic", "frequency"))
        if statistic == "frequency":
            raw = extreme.astype(float).rolling(window, min_periods=window).mean()
        elif statistic == "magnitude":
            raw = (
                _rolling_z(vix_change, window) + _rolling_z(losses, window)
            ).where(extreme, 0.0)
        elif statistic == "duration":
            groups = (~extreme).cumsum()
            raw = extreme.astype(float).groupby(groups).cumsum()
        elif statistic == "recovery":
            raw = (returns - vix_change).where(extreme.shift(1, fill_value=False), 0.0)
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F022:{statistic}")
        value = _orient(
            raw,
            str(parameters.get("direction", "continuation")),
        )
        inputs = ("spy", "cboe")
    elif lane_id == "F023":
        vix = pd.to_numeric(cboe["vix_close"], errors="coerce")
        vxo = pd.to_numeric(cboe["vxo_close"], errors="coerce")
        ratio = np.log(vix / vxo.replace(0.0, np.nan))
        form = str(parameters.get("form", "slope"))
        if form == "level":
            raw = ratio.rolling(window, min_periods=window).mean()
        elif form == "slope":
            raw = (vix - vxo).rolling(window, min_periods=window).mean()
        elif form == "curvature":
            raw = ratio.diff().diff().rolling(window, min_periods=window).sum()
        elif form == "butterfly":
            midpoint = (vix + vxo) / 2.0
            raw = (midpoint - np.sqrt(vix * vxo)).rolling(
                window, min_periods=window
            ).mean()
        elif form == "change":
            raw = ratio.diff(window)
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_FORM:F023:{form}")
        value = _normalize(
            raw, window, str(parameters.get("normalization", "rolling_z"))
        )
        inputs = ("cboe",)
    elif lane_id == "F024":
        vix = pd.to_numeric(cboe["vix_close"], errors="coerce")
        vxo = pd.to_numeric(cboe["vxo_close"], errors="coerce")
        ratio = np.log(vix / vxo.replace(0.0, np.nan))
        statistic = str(parameters.get("statistic", "convexity"))
        if statistic == "convexity":
            raw = ratio.diff().diff().rolling(window, min_periods=window).sum()
        elif statistic == "divergence":
            raw = _rolling_z(vix.pct_change(fill_method=None), window) - _rolling_z(
                returns, window
            )
        elif statistic == "relative_change":
            raw = vix.pct_change(window, fill_method=None) - vxo.pct_change(
                window, fill_method=None
            )
        elif statistic == "ratio_momentum":
            raw = ratio.diff(window)
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F024:{statistic}")
        value = _orient(
            _normalize(
                raw, window, str(parameters.get("normalization", "none"))
            ),
            str(parameters.get("direction", "continuation")),
        )
        inputs = ("spy", "cboe")
    elif lane_id == "F025":
        futures = pd.to_numeric(cftc["noncommercial_net_pct_oi"], errors="coerce")
        combined_column = cftc.get("noncommercial_net_pct_oi_combined")
        if combined_column is None:
            positioning = futures
        else:
            combined = pd.to_numeric(combined_column, errors="coerce")
            positioning = (futures - combined).where(combined.notna(), futures)
        commercial = pd.to_numeric(cftc["commercial_net_pct_oi"], errors="coerce")
        concentration = pd.to_numeric(cftc["top4_net_concentration"], errors="coerce")
        statistic = str(parameters.get("statistic", "net"))
        if statistic == "net":
            raw = positioning.rolling(window, min_periods=window).mean()
        elif statistic == "percent_open_interest":
            raw = _rolling_percentile(positioning, window)
        elif statistic == "change":
            raw = positioning.diff(window)
        elif statistic == "concentration":
            raw = concentration.rolling(window, min_periods=window).mean()
        elif statistic == "breadth":
            raw = (
                positioning.gt(0.0).astype(float)
                - commercial.gt(0.0).astype(float)
            ).rolling(window, min_periods=window).mean()
        elif statistic == "divergence":
            raw = _rolling_z(positioning, window) - _rolling_z(
                close.pct_change(window, fill_method=None), window
            )
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F025:{statistic}")
        value = _orient(raw, str(parameters.get("direction", "continuation")))
        inputs = ("spy", "cftc")
    elif lane_id == "F026":
        implied_variance = (
            pd.to_numeric(cboe["vix_close"], errors="coerce") / 100.0
        ).pow(2)
        realized_variance = returns.pow(2).rolling(
            window, min_periods=window
        ).mean() * 252.0
        form = str(parameters.get("form", "implied_realized"))
        if form == "difference":
            raw = implied_variance - realized_variance
        elif form == "ratio":
            raw = implied_variance / realized_variance.replace(0.0, np.nan) - 1.0
        elif form == "correlation":
            raw = implied_variance.rolling(window, min_periods=window).corr(
                realized_variance
            )
        elif form == "divergence":
            raw = _rolling_z(implied_variance, window) - _rolling_z(
                realized_variance, window
            )
        elif form == "implied_realized":
            raw = np.sqrt(implied_variance) - np.sqrt(realized_variance)
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_FORM:F026:{form}")
        value = _normalize(
            raw, window, str(parameters.get("normalization", "rolling_z"))
        )
        inputs = ("spy", "cboe")
    elif lane_id == "F027":
        positioning = pd.to_numeric(
            cftc["noncommercial_net_pct_oi"], errors="coerce"
        )
        price_momentum = close.pct_change(window, fill_method=None)
        form = str(parameters.get("form", "divergence"))
        if form == "difference":
            raw = positioning - price_momentum
        elif form == "ratio":
            raw = positioning / price_momentum.abs().replace(0.0, np.nan)
        elif form == "correlation":
            raw = positioning.diff().rolling(window, min_periods=window).corr(returns)
        elif form == "divergence":
            raw = _rolling_z(positioning, window) - _rolling_z(
                price_momentum, window
            )
        elif form == "implied_realized":
            raw = positioning.rolling(window, min_periods=window).std(ddof=0) - returns.abs().rolling(
                window, min_periods=window
            ).mean()
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_FORM:F027:{form}")
        value = _orient(
            _normalize(
                raw, window, str(parameters.get("normalization", "rolling_z"))
            ),
            str(parameters.get("direction", "continuation")),
        )
        inputs = ("spy", "cftc")
    elif lane_id == "F028":
        open_interest = pd.to_numeric(cftc["open_interest"], errors="coerce")
        concentration = pd.to_numeric(cftc["top4_net_concentration"], errors="coerce")
        positioning = pd.to_numeric(cftc["noncommercial_net_pct_oi"], errors="coerce")
        commercial = pd.to_numeric(cftc["commercial_net_pct_oi"], errors="coerce")
        statistic = str(parameters.get("statistic", "net"))
        if statistic == "net":
            raw = np.log(open_interest).rolling(window, min_periods=window).mean()
        elif statistic == "percent_open_interest":
            raw = _rolling_percentile(open_interest, window)
        elif statistic == "change":
            raw = open_interest.pct_change(window, fill_method=None)
        elif statistic == "concentration":
            raw = concentration.rolling(window, min_periods=window).mean()
        elif statistic == "breadth":
            raw = (
                positioning.gt(0.0).astype(float)
                + commercial.gt(0.0).astype(float)
                - 1.0
            ).rolling(window, min_periods=window).mean()
        elif statistic == "divergence":
            raw = _rolling_z(open_interest.pct_change(fill_method=None), window) - _rolling_z(
                returns, window
            )
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F028:{statistic}")
        value = _orient(raw, str(parameters.get("direction", "continuation")))
        inputs = ("spy", "cftc")
    elif lane_id == "F029":
        commercial = pd.to_numeric(cftc["commercial_net_pct_oi"], errors="coerce")
        noncommercial = pd.to_numeric(
            cftc["noncommercial_net_pct_oi"], errors="coerce"
        )
        concentration = pd.to_numeric(
            cftc["top4_net_concentration"], errors="coerce"
        )
        statistic = str(parameters.get("statistic", "net"))
        spread = noncommercial - commercial
        if statistic == "net":
            raw = spread.rolling(window, min_periods=window).mean()
        elif statistic == "percent_open_interest":
            raw = noncommercial.rolling(window, min_periods=window).mean()
        elif statistic == "change":
            raw = spread.diff(window)
        elif statistic == "concentration":
            raw = concentration.rolling(window, min_periods=window).mean()
        elif statistic == "breadth":
            raw = (
                noncommercial.gt(0.0).astype(float)
                - commercial.gt(0.0).astype(float)
            ).rolling(window, min_periods=window).mean()
        elif statistic == "divergence":
            raw = _rolling_z(spread, window) - _rolling_percentile(
                concentration, window
            )
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F029:{statistic}")
        value = _orient(raw, str(parameters.get("direction", "continuation")))
        inputs = ("cftc",)
    elif lane_id == "F030":
        three_month = pd.to_numeric(rates["yield_3m"], errors="coerce")
        two_year = pd.to_numeric(rates["yield_2y"], errors="coerce")
        ten_year = pd.to_numeric(rates["yield_10y"], errors="coerce")
        statistic = str(parameters.get("statistic", "change"))
        if statistic == "level":
            raw = ten_year.rolling(window, min_periods=window).mean()
        elif statistic == "change":
            raw = ten_year.diff(window)
        elif statistic == "momentum":
            raw = (
                ten_year - (0.25 * three_month + 0.25 * two_year + 0.5 * ten_year).rolling(
                    window, min_periods=window
                ).mean()
            )
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_STATISTIC:F030:{statistic}")
        value = _normalize(
            raw, window, str(parameters.get("normalization", "rolling_z"))
        )
        inputs = ("rates",)
    elif lane_id == "F031":
        three_month = pd.to_numeric(rates["yield_3m"], errors="coerce")
        two_year = pd.to_numeric(rates["yield_2y"], errors="coerce")
        ten_year = pd.to_numeric(rates["yield_10y"], errors="coerce")
        form = str(parameters.get("form", "slope"))
        if form == "level":
            raw = ten_year.rolling(window, min_periods=window).mean()
        elif form == "slope":
            raw = ten_year - three_month
        elif form == "curvature":
            raw = 2.0 * two_year - three_month - ten_year
        elif form == "butterfly":
            raw = (ten_year - two_year) - (two_year - three_month)
        elif form == "change":
            raw = (ten_year - three_month).diff(window)
        else:
            raise MarketFeatureEngineError(f"UNKNOWN_FORM:F031:{form}")
        value = _normalize(
            raw, window, str(parameters.get("normalization", "rolling_z"))
        )
        inputs = ("rates",)
    else:
        raise MarketFeatureEngineError(f"MARKET_LANE_NOT_IMPLEMENTED:{lane_id}")
    return _output(panels, value, input_names=inputs)


_MARKET_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F021": {"window": 63, "statistic": "level", "normalization": "rolling_z", "direction": "continuation"},
    "F022": {"window": 63, "tail": 0.05, "statistic": "magnitude", "direction": "continuation"},
    "F023": {"window": 63, "form": "slope", "normalization": "rolling_z"},
    "F024": {"window": 63, "statistic": "divergence", "normalization": "none", "direction": "continuation"},
    "F025": {"window": 13, "statistic": "divergence", "direction": "contrarian"},
    "F026": {"window": 20, "form": "implied_realized", "normalization": "rolling_z"},
    "F027": {"window": 63, "form": "divergence", "normalization": "none", "direction": "continuation"},
    "F028": {"window": 13, "statistic": "change", "direction": "continuation"},
    "F029": {"window": 13, "statistic": "concentration", "direction": "contrarian"},
    "F030": {"window": 63, "statistic": "change", "normalization": "rolling_z"},
    "F031": {"window": 63, "form": "curvature", "normalization": "rolling_z"},
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
