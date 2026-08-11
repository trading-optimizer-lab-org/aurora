"""Causal cross-section and state-combination kernels for F111-F120."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class CrossSectionFeatureEngineError(ValueError):
    """Raised when a cross-section input violates the train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_CYCLICAL = ("Autos", "BldMt", "Cnstr", "Steel", "Mach", "ElcEq", "Aero", "Ships", "Mines", "Coal", "Oil", "Rtail")
_DEFENSIVE = ("Food", "Soda", "Beer", "Smoke", "Hshld", "Hlth", "MedEq", "Drugs", "Util")


def _validated(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = ("date", "observed_at", "available_at")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise CrossSectionFeatureEngineError(f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}")
    panel = frame.copy()
    for column in required:
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.normalize().astype("datetime64[ns]")
    if panel[list(required)].isna().any().any():
        raise CrossSectionFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(_TRAIN_END).any():
        raise CrossSectionFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any() or panel["observed_at"].gt(panel["available_at"]).any():
        raise CrossSectionFeatureEngineError(f"NON_CAUSAL_PANEL_ROW:{name}")
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise CrossSectionFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _required(panels: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
    if name not in panels:
        raise CrossSectionFeatureEngineError(f"CROSS_SECTION_PANELS_MISSING:{name}")
    return _validated(name, panels[name])


def _numeric(panel: pd.DataFrame, column: str, name: str) -> pd.Series:
    if column not in panel:
        raise CrossSectionFeatureEngineError(f"PANEL_VALUE_MISSING:{name}:{column}")
    return pd.to_numeric(panel[column], errors="coerce")


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise CrossSectionFeatureEngineError(f"INVALID_POSITIVE_PARAMETER:{name}:{value}")
    return value


def _z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    std = values.rolling(window, min_periods=window).std(ddof=0)
    return (values - mean) / std.replace(0.0, np.nan)


def _align(master: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    aligned = pd.merge_asof(
        master[["date"]].sort_values("date"),
        updates.sort_values("date"),
        on="date",
        direction="backward",
    )
    if aligned["available_at"].gt(aligned["date"]).fillna(False).any():
        raise CrossSectionFeatureEngineError("FORWARD_FILLED_FUTURE_CROSS_SECTION_INPUT")
    return aligned


def _output(master: pd.DataFrame, value: pd.Series | np.ndarray, observed: Sequence[pd.DataFrame]) -> pd.DataFrame:
    observed_at = pd.concat([item["observed_at"] for item in observed], axis=1).max(axis=1)
    return pd.DataFrame(
        {
            "date": master["date"],
            "observed_at": observed_at,
            "available_at": master["date"],
            "value": pd.to_numeric(pd.Series(value, index=master.index), errors="coerce").replace([np.inf, -np.inf], np.nan),
        }
    )


def _pick(parameters: Mapping[str, Any], lane: str, choices: Mapping[str, pd.Series], default: str) -> pd.Series:
    statistic = str(parameters.get("statistic", default))
    if statistic not in choices:
        raise CrossSectionFeatureEngineError(f"{lane}_UNKNOWN_STATISTIC:{statistic}")
    return choices[statistic]


def _industry_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in panel if column not in {"date", "observed_at", "available_at"}]
    values = panel[columns].apply(pd.to_numeric, errors="coerce")
    if values.shape[1] < 2:
        raise CrossSectionFeatureEngineError("INSUFFICIENT_INDUSTRIES")
    return values


def _leadership_components(industries: pd.DataFrame, window: int) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    values = _industry_matrix(industries)
    cyclical = [column for column in _CYCLICAL if column in values]
    defensive = [column for column in _DEFENSIVE if column in values]
    if len(cyclical) < 2 or len(defensive) < 2:
        raise CrossSectionFeatureEngineError("CYCLICAL_DEFENSIVE_GROUPS_INCOMPLETE")
    cyclical_return = values[cyclical].mean(axis=1)
    defensive_return = values[defensive].mean(axis=1)
    spread = (cyclical_return - defensive_return).rolling(window, min_periods=window).sum()
    daily_breadth = np.sign(values[cyclical]).mean(axis=1) - np.sign(values[defensive]).mean(axis=1)
    breadth = daily_breadth.rolling(window, min_periods=window).mean()
    rotation = _z(cyclical_return, window) - _z(defensive_return, window)
    dispersion_gap = values[cyclical].std(axis=1, ddof=0).rolling(window, min_periods=window).mean() - values[defensive].std(axis=1, ddof=0).rolling(window, min_periods=window).mean()
    return spread, breadth, rotation, dispersion_gap


def _f111(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    industries = _required(panels, "industries")
    window = _positive(parameters, "window", 63)
    spread, breadth, rotation, dispersion = _leadership_components(industries, window)
    value = _pick(parameters, "F111", {"cyclical_defensive_spread": spread, "leadership_breadth": breadth, "rotation": rotation, "dispersion_gap": dispersion}, "cyclical_defensive_spread")
    return _output(industries, value, (industries,))


def _f112(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    factors = _required(panels, "factors")
    window = _positive(parameters, "window", 63)
    market = _numeric(factors, "market_excess", "factors")
    smb = _numeric(factors, "smb", "factors")
    hml = _numeric(factors, "hml", "factors")
    size = smb.rolling(window, min_periods=window).sum()
    value_state = hml.rolling(window, min_periods=window).sum()
    rotation = _z(smb, window) - _z(hml, window)
    confirmation = _z(market, window) * np.sign(0.5 * (size + value_state))
    value = _pick(parameters, "F112", {"size_leadership": size, "value_leadership": value_state, "factor_rotation": rotation, "market_confirmation": confirmation}, "factor_rotation")
    return _output(factors, value, (factors,))


def _f113(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    spy = _required(panels, "spy")
    rates = _align(spy, _required(panels, "rates"))
    window = _positive(parameters, "window", 63)
    lag = _positive(parameters, "momentum_lag", 20)
    stock = np.log(_numeric(spy, "close", "spy")).diff()
    y10 = _numeric(rates, "yield_10y", "rates") / 100.0
    y3 = _numeric(rates, "yield_3m", "rates") / 100.0
    bond = -7.0 * y10.diff()
    correlation = stock.rolling(window, min_periods=window).corr(bond)
    curve_momentum = (y10 - y3).diff(lag)
    duration_momentum = bond.rolling(lag, min_periods=lag).sum()
    joint_shock = _z(stock, window) + _z(bond, window)
    value = _pick(parameters, "F113", {"stock_bond_correlation": correlation, "curve_momentum": curve_momentum, "duration_momentum": duration_momentum, "joint_shock": joint_shock}, "stock_bond_correlation")
    return _output(spy, value, (spy, rates))


def _f114(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    rates = _required(panels, "rates")
    window = _positive(parameters, "window", 63)
    y3 = _numeric(rates, "yield_3m", "rates")
    y10 = _numeric(rates, "yield_10y", "rates")
    aaa = _numeric(rates, "aaa_yield", "rates")
    baa = _numeric(rates, "baa_yield", "rates")
    policy = _numeric(rates, "effective_fed_funds", "rates")
    credit = _z(baa - aaa, window)
    funding = _z(baa - y10, window)
    policy_pressure = _z(y3 - policy, window)
    composite = (credit + funding + policy_pressure) / 3.0
    value = _pick(parameters, "F114", {"credit_stress": credit, "funding_stress": funding, "policy_pressure": policy_pressure, "stress_composite": composite}, "stress_composite")
    return _output(rates, value, (rates,))


def _f115(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    fx = _required(panels, "fx")
    window = _positive(parameters, "window", 63)
    lag = _positive(parameters, "momentum_lag", 20)
    changes = pd.DataFrame({column: np.log(_numeric(fx, column, "fx")).diff(lag) for column in ("broad_dollar", "fx_cad", "fx_jpy", "fx_chf", "fx_gbp")})
    dollar = _z(changes["broad_dollar"], window)
    safe = 0.5 * (_z(changes["fx_jpy"], window) + _z(changes["fx_chf"], window))
    cyclical = 0.5 * (_z(changes["fx_cad"], window) + _z(changes["fx_gbp"], window))
    dispersion = changes.std(axis=1, ddof=0)
    value = _pick(parameters, "F115", {"dollar_momentum": dollar, "safe_haven_rotation": safe, "cyclical_rotation": cyclical, "dispersion": dispersion}, "dollar_momentum")
    return _output(fx, value, (fx,))


def _f116(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    industries = _required(panels, "industries")
    window = _positive(parameters, "window", 63)
    values = _industry_matrix(industries)
    common_mode = values.mean(axis=1)
    common_variance = common_mode.rolling(window, min_periods=window).var(ddof=0)
    average_variance = values.rolling(window, min_periods=window).var(ddof=0).mean(axis=1)
    common_share = (common_variance / average_variance.replace(0.0, np.nan)).clip(0.0, 1.0)
    count = float(values.shape[1])
    average_correlation = ((count * common_share - 1.0) / (count - 1.0)).clip(-1.0, 1.0)
    dispersion = values.std(axis=1, ddof=0).rolling(window, min_periods=window).mean()
    value = _pick(parameters, "F116", {"common_mode": common_mode, "common_share": common_share, "average_correlation": average_correlation, "dispersion": dispersion}, "common_share")
    return _output(industries, value, (industries,))


def _f117(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    industries = _required(panels, "industries")
    spy = _align(industries, _required(panels, "spy"))
    window = _positive(parameters, "window", 63)
    lag = _positive(parameters, "change_lag", 10)
    values = _industry_matrix(industries)
    breadth = np.sign(values).mean(axis=1).rolling(window, min_periods=window).mean()
    acceleration = breadth.diff(lag)
    spy_momentum = np.log(_numeric(spy, "close", "spy")).diff(window)
    divergence = _z(breadth, window) - _z(spy_momentum, window)
    failure = -np.sign(spy_momentum) * acceleration
    value = _pick(parameters, "F117", {"breadth": breadth, "acceleration": acceleration, "divergence": divergence, "failure_pressure": failure}, "divergence")
    return _output(industries, value, (industries, spy))


def _f118(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    valuation = _required(panels, "valuation")
    industries = _required(panels, "industries")
    window = _positive(parameters, "window", 24)
    lag = _positive(parameters, "growth_lag", 12)
    spread, breadth, _, _ = _leadership_components(industries, 20)
    updates = industries[["date", "observed_at", "available_at"]].copy()
    updates["industry_signal"] = 0.5 * (spread + breadth)
    aligned = _align(valuation, updates)
    earnings_growth = np.log(_numeric(valuation, "aggregate_earnings", "valuation")).diff(lag)
    earnings_state = _z(earnings_growth, window)
    industry_state = _z(_numeric(aligned, "industry_signal", "industries"), window)
    alignment = 0.5 * (earnings_state + industry_state)
    gap = industry_state - earnings_state
    value = _pick(parameters, "F118", {"earnings_state": earnings_state, "industry_state": industry_state, "alignment": alignment, "leadership_gap": gap}, "alignment")
    return _output(valuation, value, (valuation, aligned))


def _approved_states(panels: Mapping[str, pd.DataFrame], window: int) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    spy = _required(panels, "spy")
    industries = _align(spy, _required(panels, "industries"))
    factors = _align(spy, _required(panels, "factors"))
    rates = _align(spy, _required(panels, "rates"))
    financial = _align(spy, _required(panels, "financial"))
    vol = _align(spy, _required(panels, "vol"))
    macro = _align(spy, _required(panels, "macro"))
    returns = np.log(_numeric(spy, "close", "spy")).diff()
    industry_values = _industry_matrix(industries)
    macro_level = pd.concat([_numeric(macro, column, "macro") for column in ("industrial_production_first", "output_first", "consumption_first")], axis=1).mean(axis=1)
    states = pd.DataFrame(
        {
            "trend": _z(returns.rolling(20, min_periods=20).sum(), window),
            "breadth": _z(np.sign(industry_values).mean(axis=1).rolling(20, min_periods=20).mean(), window),
            "factor": _z(_numeric(factors, "market_excess", "factors").rolling(20, min_periods=20).sum(), window),
            "curve": _z(_numeric(rates, "yield_10y", "rates") - _numeric(rates, "yield_3m", "rates"), window),
            "conditions": -_z(_numeric(financial, "financial_conditions_score", "financial"), window),
            "macro": _z(macro_level, window),
            "volatility": -_z(_numeric(vol, "vix_close", "vol"), window),
        }
    )
    return states, [spy, industries, factors, rates, financial, vol, macro]


def _f119(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    window = _positive(parameters, "window", 63)
    states, observed = _approved_states(panels, window)
    mean = states.mean(axis=1).where(states.notna().all(axis=1))
    median = states.median(axis=1).where(states.notna().all(axis=1))
    consensus = np.sign(states).mean(axis=1).where(states.notna().all(axis=1))
    disagreement = states.std(axis=1, ddof=0).where(states.notna().all(axis=1))
    value = _pick(parameters, "F119", {"mean_forecast": mean, "median_forecast": median, "consensus": consensus, "disagreement": disagreement}, "mean_forecast")
    return _output(observed[0], value, observed)


def _f120(panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    window = _positive(parameters, "state_window", 63)
    neighbors = _positive(parameters, "neighbors", 20)
    feature_count = _positive(parameters, "features", 5)
    embargo = _positive(parameters, "embargo", 20)
    horizon = _positive(parameters, "horizon", 5)
    if embargo < horizon:
        raise CrossSectionFeatureEngineError("F120_EMBARGO_SHORTER_THAN_HORIZON")
    states, observed = _approved_states(panels, window)
    if feature_count > states.shape[1]:
        raise CrossSectionFeatureEngineError("F120_TOO_MANY_FEATURES")
    state_values = states.iloc[:, :feature_count].to_numpy(dtype=float)
    close = _numeric(observed[0], "close", "spy")
    targets = np.log(close.shift(-horizon) / close).to_numpy(dtype=float)
    results = {name: np.full(len(states), np.nan) for name in ("neighbor_mean", "neighbor_median", "up_probability", "neighbor_dispersion")}
    for index in range(len(states)):
        last = min(index - embargo, index - horizon)
        if last < 0 or not np.isfinite(state_values[index]).all():
            continue
        candidates = np.arange(last + 1)
        valid = np.isfinite(state_values[candidates]).all(axis=1) & np.isfinite(targets[candidates])
        candidates = candidates[valid]
        if len(candidates) < neighbors:
            continue
        distances = np.square(state_values[candidates] - state_values[index]).sum(axis=1)
        selected = candidates[np.argpartition(distances, neighbors - 1)[:neighbors]]
        outcomes = targets[selected]
        results["neighbor_mean"][index] = float(np.mean(outcomes))
        results["neighbor_median"][index] = float(np.median(outcomes))
        results["up_probability"][index] = float(np.mean(outcomes > 0.0))
        results["neighbor_dispersion"][index] = float(np.std(outcomes, ddof=0))
    choices = {name: pd.Series(values, index=states.index) for name, values in results.items()}
    value = _pick(parameters, "F120", choices, "neighbor_mean")
    return _output(observed[0], value, observed)


def evaluate_cross_section_lane(lane_id: str, input_panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]) -> pd.DataFrame:
    evaluators = {"F111": _f111, "F112": _f112, "F113": _f113, "F114": _f114, "F115": _f115, "F116": _f116, "F117": _f117, "F118": _f118, "F119": _f119, "F120": _f120}
    if lane_id not in evaluators:
        raise CrossSectionFeatureEngineError(f"CROSS_SECTION_LANE_NOT_IMPLEMENTED:{lane_id}")
    return evaluators[lane_id](input_panels, parameters)


_BATCH: Mapping[str, Mapping[str, Any]] = {
    "F111": {"statistic": "cyclical_defensive_spread", "window": 63},
    "F112": {"statistic": "factor_rotation", "window": 63},
    "F113": {"statistic": "stock_bond_correlation", "window": 63, "momentum_lag": 20},
    "F114": {"statistic": "stress_composite", "window": 63},
    "F115": {"statistic": "dollar_momentum", "window": 63, "momentum_lag": 20},
    "F116": {"statistic": "common_share", "window": 63},
    "F117": {"statistic": "divergence", "window": 63, "change_lag": 20},
    "F118": {"statistic": "alignment", "window": 24, "growth_lag": 12},
    "F119": {"statistic": "mean_forecast", "window": 63},
    "F120": {"statistic": "neighbor_mean", "state_window": 63, "neighbors": 20, "features": 5, "embargo": 20, "horizon": 5},
}


def evaluate_cross_section_family_batch(input_panels: Mapping[str, pd.DataFrame]) -> Mapping[str, pd.DataFrame]:
    return {lane: evaluate_cross_section_lane(lane, input_panels, parameters) for lane, parameters in _BATCH.items()}


__all__ = ["CrossSectionFeatureEngineError", "evaluate_cross_section_family_batch", "evaluate_cross_section_lane"]
