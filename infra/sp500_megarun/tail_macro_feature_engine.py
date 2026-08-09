"""Causal tail-risk, rates and macro kernels for lanes F091-F100."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class TailMacroFeatureEngineError(ValueError):
    """Raised when a tail/macro input violates the frozen train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_EPSILON = 1e-12


def _validated_panel(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = ("date", "observed_at", "available_at")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise TailMacroFeatureEngineError(
            f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}"
        )
    panel = frame.copy()
    for column in required:
        panel[column] = (
            pd.to_datetime(panel[column], errors="coerce")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
    if panel[list(required)].isna().any().any():
        raise TailMacroFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(
        _TRAIN_END
    ).any():
        raise TailMacroFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any():
        raise TailMacroFeatureEngineError(f"PANEL_NOT_AVAILABLE_AT_DECISION:{name}")
    if panel["observed_at"].gt(panel["available_at"]).any():
        raise TailMacroFeatureEngineError(
            f"PANEL_OBSERVED_AFTER_AVAILABILITY:{name}"
        )
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise TailMacroFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _required_panel(
    panels: Mapping[str, pd.DataFrame], name: str
) -> pd.DataFrame:
    if name not in panels:
        raise TailMacroFeatureEngineError(f"TAIL_MACRO_PANELS_MISSING:{name}")
    return _validated_panel(name, panels[name])


def _numeric(panel: pd.DataFrame, column: str, *, panel_name: str) -> pd.Series:
    if column not in panel:
        raise TailMacroFeatureEngineError(
            f"PANEL_VALUE_MISSING:{panel_name}:{column}"
        )
    return pd.to_numeric(panel[column], errors="coerce")


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise TailMacroFeatureEngineError(
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
) -> float:
    value = float(parameters.get(name, default))
    if not lower < value < upper:
        raise TailMacroFeatureEngineError(
            f"INVALID_BOUNDED_PARAMETER:{name}:{value}"
        )
    return value


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    deviation = values.rolling(window, min_periods=window).std(ddof=0)
    return (values - mean) / deviation.replace(0.0, np.nan)


def _align(master: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    left = master.loc[:, ["date"]].sort_values("date", kind="mergesort")
    right = updates.sort_values("date", kind="mergesort")
    aligned = pd.merge_asof(left, right, on="date", direction="backward")
    stale_future = aligned["available_at"].gt(aligned["date"])
    if stale_future.fillna(False).any():
        raise TailMacroFeatureEngineError("FORWARD_FILLED_FUTURE_TAIL_MACRO_INPUT")
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


def _statistic(
    parameters: Mapping[str, Any],
    lane_id: str,
    choices: Mapping[str, pd.Series],
    default: str,
) -> pd.Series:
    name = str(parameters.get("statistic", default))
    try:
        return choices[name]
    except KeyError as exc:
        raise TailMacroFeatureEngineError(
            f"{lane_id}_UNKNOWN_STATISTIC:{name}"
        ) from exc


def _tail_components(
    spy: pd.DataFrame,
    *,
    window: int,
    tail_quantile: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    close = _numeric(spy, "close", panel_name="spy")
    returns = np.log(close).diff()
    threshold = returns.shift(1).rolling(
        window, min_periods=window
    ).quantile(tail_quantile)
    tail_squared = returns.pow(2).where(returns.le(threshold), 0.0)
    tail_squared = tail_squared.where(threshold.notna() & returns.notna())
    realized_tail = np.sqrt(
        252.0 * tail_squared.rolling(window, min_periods=window).mean()
    )
    realized_variance = 252.0 * returns.pow(2).rolling(
        window, min_periods=window
    ).mean()
    tail_share = (
        252.0
        * tail_squared.rolling(window, min_periods=window).mean()
        / realized_variance.replace(0.0, np.nan)
    ).clip(0.0, 1.0)
    return returns, realized_tail, tail_share


def _f091(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    vol = _align(spy, _required_panel(panels, "vol"))
    window = _positive_int(parameters, "window", 126)
    tail_quantile = _bounded_float(
        parameters,
        "tail_quantile",
        0.1,
        lower=0.0,
        upper=0.5,
    )
    vix = _numeric(vol, "vix_close", panel_name="vol")
    vxo = _numeric(vol, "vxo_close", panel_name="vol")
    vol_of_vol = np.sqrt(252.0) * np.log(vix).diff().rolling(
        window, min_periods=window
    ).std(ddof=0)
    disagreement = np.log(vix / vxo)
    _, realized_tail, _ = _tail_components(
        spy, window=window, tail_quantile=tail_quantile
    )
    vol_state = _rolling_z(vol_of_vol, window)
    tail_state = _rolling_z(realized_tail, window)
    disagreement_state = _rolling_z(disagreement.abs(), window)
    convexity_interaction = vol_state * (
        1.0
        + 0.5 * np.tanh(tail_state)
        + 0.5 * np.tanh(disagreement_state)
    )
    value = _statistic(
        parameters,
        "F091",
        {
            "vol_of_vol": vol_of_vol,
            "methodology_disagreement": disagreement,
            "realized_tail": realized_tail,
            "convexity_interaction": convexity_interaction.clip(-20.0, 20.0),
        },
        "convexity_interaction",
    )
    return _output(spy, value, observed_panels=(spy, vol))


def _f092(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    vol = _align(spy, _required_panel(panels, "vol"))
    window = _positive_int(parameters, "window", 63)
    returns = np.log(_numeric(spy, "close", panel_name="spy")).diff()
    realized_variance = 252.0 * returns.pow(2).rolling(
        window, min_periods=window
    ).mean()
    bipower_variance = 252.0 * (np.pi / 2.0) * (
        returns.abs() * returns.shift(1).abs()
    ).rolling(window, min_periods=window).mean()
    jump_variance = (realized_variance - bipower_variance).clip(lower=0.0)
    jump_share = (
        jump_variance / realized_variance.replace(0.0, np.nan)
    ).clip(0.0, 1.0)
    implied_variance = (_numeric(vol, "vix_close", panel_name="vol") / 100.0).pow(
        2
    )
    variance_premium = implied_variance - realized_variance
    continuous_premium = implied_variance - bipower_variance
    risk_compensation = _rolling_z(variance_premium, window) * (1.0 + jump_share)
    value = _statistic(
        parameters,
        "F092",
        {
            "variance_premium": variance_premium,
            "continuous_premium": continuous_premium,
            "jump_share": jump_share,
            "risk_compensation": risk_compensation.clip(-20.0, 20.0),
        },
        "risk_compensation",
    )
    return _output(spy, value, observed_panels=(spy, vol))


def _f093(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    vol = _align(spy, _required_panel(panels, "vol"))
    cftc = _required_panel(panels, "cftc")
    window = _positive_int(parameters, "window", 126)
    positioning_window = _positive_int(parameters, "positioning_window", 26)
    tail_quantile = _bounded_float(
        parameters,
        "tail_quantile",
        0.1,
        lower=0.0,
        upper=0.5,
    )
    _, realized_tail, tail_realization = _tail_components(
        spy, window=window, tail_quantile=tail_quantile
    )
    vix = _numeric(vol, "vix_close", panel_name="vol") / 100.0
    implied_downside_gap = np.log(
        vix.clip(lower=_EPSILON) / realized_tail.clip(lower=_EPSILON)
    )
    positioning_gap = _numeric(
        cftc, "noncommercial_net_pct_oi_combined", panel_name="cftc"
    ) - _numeric(cftc, "noncommercial_net_pct_oi", panel_name="cftc")
    positioning_updates = cftc.loc[
        :, ["date", "observed_at", "available_at"]
    ].copy()
    positioning_updates["positioning_pressure"] = _rolling_z(
        positioning_gap.abs(), positioning_window
    )
    aligned_positioning = _align(spy, positioning_updates)
    positioning_pressure = _numeric(
        aligned_positioning,
        "positioning_pressure",
        panel_name="cftc",
    )
    gap_state = _rolling_z(implied_downside_gap, window)
    insurance_interaction = gap_state * (
        1.0
        + 0.5 * np.tanh(positioning_pressure)
        + 0.5 * tail_realization
    )
    value = _statistic(
        parameters,
        "F093",
        {
            "implied_downside_gap": implied_downside_gap,
            "positioning_pressure": positioning_pressure,
            "tail_realization": tail_realization,
            "insurance_interaction": insurance_interaction.clip(-20.0, 20.0),
        },
        "insurance_interaction",
    )
    return _output(
        spy,
        value,
        observed_panels=(spy, vol, aligned_positioning),
    )


def _f094(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    spy = _required_panel(panels, "spy")
    vol = _align(spy, _required_panel(panels, "vol"))
    calendar = _align(spy, _required_panel(panels, "calendar"))
    window = _positive_int(parameters, "window", 63)
    event_window = _positive_int(parameters, "event_window", 5)
    sessions_until = _numeric(
        calendar,
        "sessions_until_standard_expiry",
        panel_name="calendar",
    )
    event_weight = ((event_window - sessions_until) / float(event_window)).clip(
        0.0, 1.0
    )
    high = _numeric(spy, "high", panel_name="spy")
    low = _numeric(spy, "low", panel_name="spy")
    open_ = _numeric(spy, "open", panel_name="spy")
    close = _numeric(spy, "close", panel_name="spy")
    bar_range = np.log(high / low)
    range_compression = -_rolling_z(bar_range, window)
    vix_state = _rolling_z(
        _numeric(vol, "vix_close", panel_name="vol"), window
    )
    absolute_return_state = _rolling_z(np.log(close).diff().abs(), window)
    expiry_pinning = event_weight * range_compression
    convexity_pressure = event_weight * vix_state * (
        1.0 + 0.5 * np.tanh(absolute_return_state)
    )
    quarterly_pressure = expiry_pinning * _numeric(
        calendar, "is_quarterly_expiry", panel_name="calendar"
    ).clip(0.0, 1.0)
    overnight_return = np.log(open_ / close.shift(1))
    intraday_return = np.log(close / open_)
    reversal = -np.sign(overnight_return) * intraday_return
    reversal_pressure = event_weight * _rolling_z(reversal, window)
    value = _statistic(
        parameters,
        "F094",
        {
            "expiry_pinning": expiry_pinning,
            "convexity_pressure": convexity_pressure.clip(-20.0, 20.0),
            "quarterly_pressure": quarterly_pressure,
            "reversal_pressure": reversal_pressure,
        },
        "expiry_pinning",
    )
    return _output(spy, value, observed_panels=(spy, vol, calendar))


def _f095(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    rates = _required_panel(panels, "rates")
    vol = _align(rates, _required_panel(panels, "vol"))
    window = _positive_int(parameters, "window", 63)
    change_lag = _positive_int(parameters, "change_lag", 5)
    yield_columns = [column for column in rates if column.startswith("yield_")]
    if len(yield_columns) < 2:
        raise TailMacroFeatureEngineError("F095_INSUFFICIENT_RATE_MATURITIES")
    yields = rates[yield_columns].apply(pd.to_numeric, errors="coerce") / 100.0
    daily_curve_move = np.sqrt(yields.diff().pow(2).mean(axis=1))
    rate_volatility = np.sqrt(
        252.0
        * daily_curve_move.pow(2).rolling(window, min_periods=window).mean()
    )
    equity_volatility = _numeric(vol, "vix_close", panel_name="vol") / 100.0
    volatility_ratio = np.log(
        rate_volatility.clip(lower=_EPSILON)
        / equity_volatility.clip(lower=_EPSILON)
    )
    divergence = _rolling_z(rate_volatility, window) - _rolling_z(
        equity_volatility, window
    )
    shock = _rolling_z(rate_volatility.diff(change_lag), window) - _rolling_z(
        equity_volatility.diff(change_lag), window
    )
    value = _statistic(
        parameters,
        "F095",
        {
            "rate_volatility": rate_volatility,
            "volatility_ratio": volatility_ratio,
            "divergence": divergence,
            "shock": shock,
        },
        "divergence",
    )
    return _output(rates, value, observed_panels=(rates, vol))


def _growth_score(values: pd.Series, *, lag: int, window: int) -> tuple[pd.Series, pd.Series]:
    growth = np.log(values.where(values.gt(0.0))).diff(lag)
    return growth, _rolling_z(growth, window)


def _f096(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    liquidity = _required_panel(panels, "liquidity")
    policy = _align(liquidity, _required_panel(panels, "policy"))
    window = _positive_int(parameters, "window", 26)
    growth_lag = _positive_int(parameters, "growth_lag", 13)
    _, base_score = _growth_score(
        _numeric(liquidity, "monetary_base", panel_name="liquidity"),
        lag=growth_lag,
        window=window,
    )
    _, reserve_score = _growth_score(
        _numeric(liquidity, "total_reserves", panel_name="liquidity"),
        lag=growth_lag,
        window=window,
    )
    _, money_score = _growth_score(
        _numeric(liquidity, "m2", panel_name="liquidity"),
        lag=growth_lag,
        window=window,
    )
    policy_change = _numeric(
        policy, "effective_fed_funds", panel_name="policy"
    ).diff(growth_lag)
    policy_score = -_rolling_z(policy_change, window)
    components = pd.DataFrame(
        {
            "base": base_score,
            "reserves": reserve_score,
            "money": money_score,
            "policy": policy_score,
        }
    )
    net_liquidity = components.mean(axis=1).where(components.notna().all(axis=1))
    money_impulse = components[["base", "money"]].mean(axis=1).where(
        components[["base", "money"]].notna().all(axis=1)
    )
    policy_adjusted = components[["reserves", "money", "policy"]].mean(
        axis=1
    ).where(components[["reserves", "money", "policy"]].notna().all(axis=1))
    value = _statistic(
        parameters,
        "F096",
        {
            "net_liquidity": net_liquidity,
            "reserve_impulse": reserve_score,
            "money_impulse": money_impulse,
            "policy_adjusted": policy_adjusted,
        },
        "policy_adjusted",
    )
    return _output(liquidity, value, observed_panels=(liquidity, policy))


def _f097(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    credit = _required_panel(panels, "credit_money")
    window = _positive_int(parameters, "window", 26)
    growth_lag = _positive_int(parameters, "growth_lag", 13)
    growth: dict[str, pd.Series] = {}
    scores: dict[str, pd.Series] = {}
    for name in ("bank_credit", "loans_and_leases", "m2", "commercial_paper"):
        growth[name], scores[name] = _growth_score(
            _numeric(credit, name, panel_name="credit_money"),
            lag=growth_lag,
            window=window,
        )
    growth_frame = pd.DataFrame(growth)
    score_frame = pd.DataFrame(scores)
    growth_breadth = np.sign(growth_frame).mean(axis=1).where(
        growth_frame.notna().all(axis=1)
    )
    credit_columns = ["bank_credit", "loans_and_leases", "commercial_paper"]
    credit_impulse = score_frame[credit_columns].mean(axis=1).where(
        score_frame[credit_columns].notna().all(axis=1)
    )
    contraction_pressure = (-score_frame[credit_columns].clip(upper=0.0)).mean(
        axis=1
    ).where(score_frame[credit_columns].notna().all(axis=1))
    money_credit_gap = score_frame["m2"] - credit_impulse
    value = _statistic(
        parameters,
        "F097",
        {
            "growth_breadth": growth_breadth,
            "credit_impulse": credit_impulse,
            "contraction_pressure": contraction_pressure,
            "money_credit_gap": money_credit_gap,
        },
        "growth_breadth",
    )
    return _output(credit, value, observed_panels=(credit,))


def _release_states(
    panel: pd.DataFrame,
    columns: Sequence[str],
    *,
    forecast_window: int,
    scale_window: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    levels = pd.DataFrame(index=panel.index, dtype=float)
    surprises = pd.DataFrame(index=panel.index, dtype=float)
    trends = pd.DataFrame(index=panel.index, dtype=float)
    accelerations = pd.DataFrame(index=panel.index, dtype=float)
    for column in columns:
        values = _numeric(panel, column, panel_name="macro")
        native = values.loc[values.notna()]
        if native.empty:
            levels[column] = np.nan
            surprises[column] = np.nan
            trends[column] = np.nan
            accelerations[column] = np.nan
            continue
        changes = native.diff()
        prior_drift = changes.shift(1).rolling(
            forecast_window, min_periods=forecast_window
        ).mean()
        forecast = native.shift(1) + prior_drift
        error = native - forecast
        scale = error.shift(1).rolling(
            scale_window, min_periods=scale_window
        ).std(ddof=0)
        surprise = error / scale.replace(0.0, np.nan)
        trend = changes.rolling(
            forecast_window, min_periods=forecast_window
        ).mean()
        acceleration = trend.diff()
        levels[column] = values
        surprises[column] = surprise.reindex(panel.index)
        trends[column] = trend.reindex(panel.index)
        accelerations[column] = acceleration.reindex(panel.index)
    return (
        levels.ffill(),
        surprises.ffill(),
        trends.ffill(),
        accelerations.ffill(),
    )


def _f098(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    macro = _required_panel(panels, "macro")
    forecast_window = _positive_int(parameters, "forecast_window", 6)
    scale_window = _positive_int(parameters, "scale_window", 12)
    growth_columns = (
        "payroll_first",
        "industrial_production_first",
        "housing_starts_first",
        "output_first",
        "consumption_first",
    )
    _, surprises, _, _ = _release_states(
        macro,
        growth_columns,
        forecast_window=forecast_window,
        scale_window=scale_window,
    )
    available = surprises.notna().sum(axis=1)
    surprise_breadth = np.sign(surprises).mean(axis=1).where(available.ge(2))
    surprise_magnitude = surprises.abs().mean(axis=1).where(available.ge(2))
    growth_surprise = surprises.mean(axis=1).where(available.ge(2))
    dispersion = surprises.std(axis=1, ddof=0).where(available.ge(2))
    value = _statistic(
        parameters,
        "F098",
        {
            "surprise_breadth": surprise_breadth,
            "surprise_magnitude": surprise_magnitude,
            "growth_surprise": growth_surprise,
            "dispersion": dispersion,
        },
        "surprise_breadth",
    )
    return _output(macro, value, observed_panels=(macro,))


def _f099(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    macro = _required_panel(panels, "macro")
    forecast_window = _positive_int(parameters, "forecast_window", 6)
    scale_window = _positive_int(parameters, "scale_window", 12)
    inflation_columns = ("cpi_first", "core_cpi_first", "core_pce_first")
    levels, surprises, trends, accelerations = _release_states(
        macro,
        inflation_columns,
        forecast_window=forecast_window,
        scale_window=scale_window,
    )
    inflation_level = levels.mean(axis=1).where(levels.notna().any(axis=1))
    inflation_surprise = surprises.mean(axis=1).where(
        surprises.notna().any(axis=1)
    )
    inflation_trend = trends.mean(axis=1).where(trends.notna().any(axis=1))
    inflation_acceleration = accelerations.mean(axis=1).where(
        accelerations.notna().any(axis=1)
    )
    value = _statistic(
        parameters,
        "F099",
        {
            "inflation_level": inflation_level,
            "inflation_surprise": inflation_surprise,
            "inflation_trend": inflation_trend,
            "inflation_acceleration": inflation_acceleration,
        },
        "inflation_level",
    )
    return _output(macro, value, observed_panels=(macro,))


def _macro_state_for_events(macro: pd.DataFrame) -> pd.DataFrame:
    state = macro.copy()
    value_columns = [
        column
        for column in state
        if column not in {"date", "observed_at", "available_at"}
    ]
    state[value_columns] = state[value_columns].apply(
        pd.to_numeric, errors="coerce"
    ).ffill()
    return state


def _f100(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    fomc = _required_panel(panels, "fomc")
    policy = _align(fomc, _required_panel(panels, "policy"))
    macro = _align(
        fomc,
        _macro_state_for_events(_required_panel(panels, "macro")),
    )
    normalization_window = _positive_int(
        parameters, "normalization_window", 20
    )
    inflation_target = float(parameters.get("inflation_target", 2.0))
    if not np.isfinite(inflation_target):
        raise TailMacroFeatureEngineError(
            f"F100_INVALID_INFLATION_TARGET:{inflation_target}"
        )
    fed_funds = _numeric(policy, "effective_fed_funds", panel_name="policy")
    policy_change = fed_funds.diff()
    inflation_columns = ("cpi_first", "core_cpi_first", "core_pce_first")
    inflation = macro[list(inflation_columns)].apply(
        pd.to_numeric, errors="coerce"
    ).mean(axis=1)
    growth = macro[["output_first", "consumption_first"]].apply(
        pd.to_numeric, errors="coerce"
    ).mean(axis=1)
    real_rate = fed_funds - inflation
    rule_rate = (
        2.0
        + inflation
        + 0.5 * (inflation - inflation_target)
        + 0.5 * (growth - 2.0)
    )
    rule_gap = fed_funds - rule_rate
    event_weight = (
        1.0
        + 0.25
        * _numeric(fomc, "statement_count", panel_name="fomc").clip(0.0, 1.0)
        + 0.5
        * _numeric(fomc, "conference_call", panel_name="fomc").clip(0.0, 1.0)
    )
    event_interaction = 0.5 * (
        _rolling_z(policy_change, normalization_window)
        + _rolling_z(rule_gap, normalization_window)
    ) * event_weight
    value = _statistic(
        parameters,
        "F100",
        {
            "policy_change": policy_change,
            "real_rate": real_rate,
            "rule_gap": rule_gap,
            "event_interaction": event_interaction.clip(-20.0, 20.0),
        },
        "event_interaction",
    )
    return _output(fomc, value, observed_panels=(fomc, policy, macro))


def evaluate_tail_macro_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one F091-F100 formula using only published train information."""

    evaluators = {
        "F091": _f091,
        "F092": _f092,
        "F093": _f093,
        "F094": _f094,
        "F095": _f095,
        "F096": _f096,
        "F097": _f097,
        "F098": _f098,
        "F099": _f099,
        "F100": _f100,
    }
    try:
        evaluator = evaluators[lane_id]
    except KeyError as exc:
        raise TailMacroFeatureEngineError(
            f"TAIL_MACRO_LANE_NOT_IMPLEMENTED:{lane_id}"
        ) from exc
    return evaluator(input_panels, parameters)


_TAIL_MACRO_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F091": {
        "statistic": "convexity_interaction",
        "window": 126,
        "tail_quantile": 0.1,
    },
    "F092": {"statistic": "risk_compensation", "window": 63},
    "F093": {
        "statistic": "insurance_interaction",
        "window": 126,
        "positioning_window": 26,
        "tail_quantile": 0.1,
    },
    "F094": {"statistic": "expiry_pinning", "window": 63, "event_window": 5},
    "F095": {"statistic": "divergence", "window": 63, "change_lag": 5},
    "F096": {
        "statistic": "policy_adjusted",
        "window": 26,
        "growth_lag": 13,
    },
    "F097": {
        "statistic": "growth_breadth",
        "window": 26,
        "growth_lag": 13,
    },
    "F098": {
        "statistic": "surprise_breadth",
        "forecast_window": 6,
        "scale_window": 12,
    },
    "F099": {
        "statistic": "inflation_level",
        "forecast_window": 6,
        "scale_window": 12,
    },
    "F100": {
        "statistic": "event_interaction",
        "normalization_window": 20,
        "inflation_target": 2.0,
    },
}


def evaluate_tail_macro_family_batch(
    input_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for every F091-F100 lane."""

    return {
        lane_id: evaluate_tail_macro_lane(lane_id, input_panels, parameters)
        for lane_id, parameters in _TAIL_MACRO_BATCH_PARAMETERS.items()
    }


__all__ = [
    "TailMacroFeatureEngineError",
    "evaluate_tail_macro_family_batch",
    "evaluate_tail_macro_lane",
]
