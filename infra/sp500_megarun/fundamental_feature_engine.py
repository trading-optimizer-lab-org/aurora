"""Causal aggregate fundamental and cross-asset kernels for F101-F110."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class FundamentalFeatureEngineError(ValueError):
    """Raised when a fundamental input violates the frozen train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_EPSILON = 1e-12


def _validated_panel(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = ("date", "observed_at", "available_at")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise FundamentalFeatureEngineError(
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
        raise FundamentalFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(
        _TRAIN_END
    ).any():
        raise FundamentalFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any():
        raise FundamentalFeatureEngineError(
            f"PANEL_NOT_AVAILABLE_AT_DECISION:{name}"
        )
    if panel["observed_at"].gt(panel["available_at"]).any():
        raise FundamentalFeatureEngineError(
            f"PANEL_OBSERVED_AFTER_AVAILABILITY:{name}"
        )
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise FundamentalFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _required_panel(
    panels: Mapping[str, pd.DataFrame], name: str
) -> pd.DataFrame:
    if name not in panels:
        raise FundamentalFeatureEngineError(f"FUNDAMENTAL_PANELS_MISSING:{name}")
    return _validated_panel(name, panels[name])


def _numeric(panel: pd.DataFrame, column: str, *, panel_name: str) -> pd.Series:
    if column not in panel:
        raise FundamentalFeatureEngineError(
            f"PANEL_VALUE_MISSING:{panel_name}:{column}"
        )
    return pd.to_numeric(panel[column], errors="coerce")


def _positive_int(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise FundamentalFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
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
        raise FundamentalFeatureEngineError("FORWARD_FILLED_FUTURE_FUNDAMENTAL_INPUT")
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
        raise FundamentalFeatureEngineError(
            f"{lane_id}_UNKNOWN_STATISTIC:{name}"
        ) from exc


def _seasonal_prior(values: pd.Series, seasons: int) -> pd.Series:
    prior = pd.concat(
        [values.shift(12 * season) for season in range(1, seasons + 1)],
        axis=1,
    )
    return prior.mean(axis=1).where(prior.notna().sum(axis=1).ge(1))


def _f101(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    valuation = _required_panel(panels, "valuation")
    calendar = _align(valuation, _required_panel(panels, "calendar"))
    window = _positive_int(parameters, "window", 36)
    seasonal_window = _positive_int(parameters, "seasonal_window", 3)
    earnings_change = np.log(
        _numeric(valuation, "aggregate_earnings", panel_name="valuation").where(
            lambda values: values.gt(0.0)
        )
    ).diff()
    dividend_change = np.log(
        _numeric(valuation, "aggregate_dividends", panel_name="valuation").where(
            lambda values: values.gt(0.0)
        )
    ).diff()
    earnings_news = earnings_change - _seasonal_prior(
        earnings_change, seasonal_window
    )
    dividend_news = dividend_change - _seasonal_prior(
        dividend_change, seasonal_window
    )
    earnings_state = _rolling_z(earnings_news, window)
    dividend_state = _rolling_z(dividend_news, window)
    news_seasonality = 0.5 * (earnings_state + dividend_state)
    quarter = _numeric(calendar, "quarter", panel_name="calendar")
    quarterly_cycle = news_seasonality * np.cos(2.0 * np.pi * (quarter - 1.0) / 4.0)
    value = _statistic(
        parameters,
        "F101",
        {
            "news_seasonality": news_seasonality,
            "earnings_news": earnings_news,
            "dividend_news": dividend_news,
            "quarterly_cycle": quarterly_cycle,
        },
        "news_seasonality",
    )
    return _output(valuation, value, observed_panels=(valuation, calendar))


def _f102(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    valuation = _required_panel(panels, "valuation")
    window = _positive_int(parameters, "window", 36)
    momentum_lag = _positive_int(parameters, "momentum_lag", 6)
    earnings_momentum = np.log(
        _numeric(valuation, "aggregate_earnings", panel_name="valuation").where(
            lambda values: values.gt(0.0)
        )
    ).diff(momentum_lag)
    earnings_yield_change = _numeric(
        valuation, "earnings_yield", panel_name="valuation"
    ).diff(momentum_lag)
    acceleration = earnings_momentum.diff(momentum_lag)
    composite = pd.concat(
        [
            _rolling_z(earnings_momentum, window),
            _rolling_z(earnings_yield_change, window),
            _rolling_z(acceleration, window),
        ],
        axis=1,
    ).mean(axis=1)
    value = _statistic(
        parameters,
        "F102",
        {
            "earnings_momentum": earnings_momentum,
            "earnings_yield_change": earnings_yield_change,
            "acceleration": acceleration,
            "composite": composite,
        },
        "composite",
    )
    return _output(valuation, value, observed_panels=(valuation,))


def _f103(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    valuation = _required_panel(panels, "valuation")
    window = _positive_int(parameters, "window", 36)
    growth_lag = _positive_int(parameters, "growth_lag", 12)
    earnings_growth = np.log(
        _numeric(valuation, "aggregate_earnings", panel_name="valuation").where(
            lambda values: values.gt(0.0)
        )
    ).diff(growth_lag)
    dividend_growth = np.log(
        _numeric(valuation, "aggregate_dividends", panel_name="valuation").where(
            lambda values: values.gt(0.0)
        )
    ).diff(growth_lag)
    payout_change = _numeric(
        valuation, "payout_ratio", panel_name="valuation"
    ).diff(growth_lag)
    decomposition = pd.concat(
        [
            _rolling_z(earnings_growth, window),
            _rolling_z(dividend_growth, window),
            -_rolling_z(payout_change.abs(), window),
        ],
        axis=1,
    ).mean(axis=1)
    value = _statistic(
        parameters,
        "F103",
        {
            "earnings_growth": earnings_growth,
            "dividend_growth": dividend_growth,
            "payout_change": payout_change,
            "decomposition": decomposition,
        },
        "decomposition",
    )
    return _output(valuation, value, observed_panels=(valuation,))


def _f104(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    market = _required_panel(panels, "market_issuance")
    issuance = _align(market, _required_panel(panels, "issuance"))
    window = _positive_int(parameters, "window", 24)
    change_lag = _positive_int(parameters, "change_lag", 4)
    market_issuance = _rolling_z(
        _numeric(market, "net_equity_issuance", panel_name="market_issuance"),
        window,
    )
    z1_change = _numeric(
        issuance, "corporate_equity_net_issuance", panel_name="issuance"
    ).diff(change_lag)
    z1_issuance = _rolling_z(z1_change, window)
    agreement = 0.5 * (market_issuance + z1_issuance)
    retirement_pressure = 0.5 * (
        (-market_issuance).clip(lower=0.0) + (-z1_issuance).clip(lower=0.0)
    )
    value = _statistic(
        parameters,
        "F104",
        {
            "market_issuance": market_issuance,
            "z1_issuance": z1_issuance,
            "agreement": agreement,
            "retirement_pressure": retirement_pressure,
        },
        "agreement",
    )
    return _output(market, value, observed_panels=(market, issuance))


def _f105(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    credit_money = _required_panel(panels, "credit_money")
    financial = _align(credit_money, _required_panel(panels, "financial"))
    credit = _align(credit_money, _required_panel(panels, "credit"))
    window = _positive_int(parameters, "window", 26)
    growth_lag = _positive_int(parameters, "growth_lag", 13)
    growth_states = []
    for column in ("bank_credit", "loans_and_leases", "commercial_paper"):
        growth = np.log(
            _numeric(credit_money, column, panel_name="credit_money").where(
                lambda values: values.gt(0.0)
            )
        ).diff(growth_lag)
        growth_states.append(_rolling_z(growth, window))
    credit_impulse = pd.concat(growth_states, axis=1).mean(axis=1)
    financial_stress = _rolling_z(
        _numeric(
            financial, "financial_conditions_score", panel_name="financial"
        ),
        window,
    )
    spread_stress = _rolling_z(
        _numeric(credit, "baa_aaa_spread", panel_name="credit"), window
    )
    funding_stress = 0.5 * (financial_stress + spread_stress)
    balance_sheet_capacity = credit_impulse - funding_stress
    capacity_disagreement = credit_impulse + funding_stress
    value = _statistic(
        parameters,
        "F105",
        {
            "balance_sheet_capacity": balance_sheet_capacity,
            "credit_impulse": credit_impulse,
            "funding_stress": funding_stress,
            "capacity_disagreement": capacity_disagreement,
        },
        "balance_sheet_capacity",
    )
    return _output(
        credit_money,
        value,
        observed_panels=(credit_money, financial, credit),
    )


def _f106(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    uncertainty = _required_panel(panels, "uncertainty")
    financial = _align(uncertainty, _required_panel(panels, "financial"))
    window = _positive_int(parameters, "window", 126)
    persistence_window = _positive_int(parameters, "persistence_window", 20)
    uncertainty_level = _rolling_z(
        _numeric(uncertainty, "uncertainty_score", panel_name="uncertainty"),
        window,
    )
    volatility_state = _rolling_z(
        _numeric(uncertainty, "volatility_level", panel_name="uncertainty"),
        window,
    )
    rate_shock_state = _rolling_z(
        _numeric(
            uncertainty, "absolute_rate_change", panel_name="uncertainty"
        ),
        window,
    )
    financial_state = _rolling_z(
        _numeric(
            financial, "financial_conditions_score", panel_name="financial"
        ),
        window,
    )
    stress_composite = pd.concat(
        [uncertainty_level, volatility_state, rate_shock_state, financial_state],
        axis=1,
    ).mean(axis=1)
    disagreement = uncertainty_level - financial_state
    persistence = stress_composite.rolling(
        persistence_window, min_periods=persistence_window
    ).mean()
    value = _statistic(
        parameters,
        "F106",
        {
            "uncertainty_level": uncertainty_level,
            "stress_composite": stress_composite,
            "disagreement": disagreement,
            "persistence": persistence,
        },
        "stress_composite",
    )
    return _output(uncertainty, value, observed_panels=(uncertainty, financial))


def _f107(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    cycle = _required_panel(panels, "cycle")
    rates = _align(cycle, _required_panel(panels, "rates"))
    macro = _align(cycle, _required_panel(panels, "macro"))
    window = _positive_int(parameters, "window", 12)
    realtime_growth_state = _rolling_z(
        _numeric(cycle, "realtime_output_growth", panel_name="cycle"), window
    )
    release_growth_state = pd.concat(
        [
            _rolling_z(_numeric(macro, column, panel_name="macro"), window)
            for column in (
                "industrial_production_first",
                "output_first",
                "consumption_first",
            )
        ],
        axis=1,
    ).mean(axis=1)
    growth_state = 0.5 * (realtime_growth_state + release_growth_state)
    labor_pressure = _numeric(
        cycle, "realtime_unemployment", panel_name="cycle"
    ) + _numeric(cycle, "unemployment_change", panel_name="cycle")
    labor_state = -_rolling_z(labor_pressure, window)
    curve = _numeric(rates, "yield_10y", panel_name="rates") - _numeric(
        rates, "yield_3m", panel_name="rates"
    )
    curve_state = _rolling_z(curve, window)
    recession_pressure = -(growth_state + labor_state + curve_state) / 3.0
    value = _statistic(
        parameters,
        "F107",
        {
            "recession_pressure": recession_pressure,
            "growth_state": growth_state,
            "labor_state": labor_state,
            "curve_state": curve_state,
        },
        "recession_pressure",
    )
    return _output(cycle, value, observed_panels=(cycle, rates, macro))


def _f108(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    macro = _required_panel(panels, "macro")
    uncertainty = _align(macro, _required_panel(panels, "uncertainty"))
    window = _positive_int(parameters, "window", 24)
    trend_window = _positive_int(parameters, "trend_window", 6)
    activity_states = []
    for column in (
        "payroll_first",
        "industrial_production_first",
        "housing_starts_first",
        "output_first",
        "consumption_first",
    ):
        activity_states.append(
            _rolling_z(_numeric(macro, column, panel_name="macro"), window)
        )
    activity_state = pd.concat(activity_states, axis=1).mean(axis=1)
    uncertainty_state = _rolling_z(
        _numeric(uncertainty, "uncertainty_score", panel_name="uncertainty"),
        window,
    )
    expected_activity = activity_state.shift(1).rolling(
        trend_window, min_periods=trend_window
    ).mean()
    expectation_proxy = expected_activity - uncertainty_state
    deterioration = -(activity_state - activity_state.shift(trend_window))
    disagreement = expectation_proxy - activity_state
    value = _statistic(
        parameters,
        "F108",
        {
            "expectation_proxy": expectation_proxy,
            "activity_state": activity_state,
            "deterioration": deterioration,
            "disagreement": disagreement,
        },
        "disagreement",
    )
    return _output(macro, value, observed_panels=(macro, uncertainty))


def _f109(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    balance = _required_panel(panels, "balance")
    uncertainty = _align(balance, _required_panel(panels, "uncertainty"))
    cftc = _align(balance, _required_panel(panels, "cftc"))
    vol = _align(balance, _required_panel(panels, "vol"))
    window = _positive_int(parameters, "window", 20)
    allocation_state = pd.concat(
        [
            _rolling_z(
                _numeric(
                    balance, "household_equity_share", panel_name="balance"
                ),
                window,
            ),
            _rolling_z(
                _numeric(
                    balance, "mutual_fund_equity_share", panel_name="balance"
                ),
                window,
            ),
        ],
        axis=1,
    ).mean(axis=1)
    positioning_state = pd.concat(
        [
            _rolling_z(
                _numeric(cftc, "noncommercial_net_pct_oi", panel_name="cftc"),
                window,
            ),
            _rolling_z(
                _numeric(
                    cftc,
                    "noncommercial_net_pct_oi_combined",
                    panel_name="cftc",
                ),
                window,
            ),
        ],
        axis=1,
    ).mean(axis=1)
    uncertainty_state = -_rolling_z(
        _numeric(uncertainty, "uncertainty_score", panel_name="uncertainty"),
        window,
    )
    volatility_state = -_rolling_z(
        _numeric(vol, "vix_close", panel_name="vol"), window
    )
    components = pd.concat(
        [allocation_state, positioning_state, uncertainty_state, volatility_state],
        axis=1,
    )
    sentiment_composite = components.mean(axis=1)
    disagreement = components.std(axis=1, ddof=0)
    value = _statistic(
        parameters,
        "F109",
        {
            "sentiment_composite": sentiment_composite,
            "allocation_state": allocation_state,
            "positioning_state": positioning_state,
            "disagreement": disagreement,
        },
        "sentiment_composite",
    )
    return _output(
        balance,
        value,
        observed_panels=(balance, uncertainty, cftc, vol),
    )


def _f110(
    panels: Mapping[str, pd.DataFrame], parameters: Mapping[str, Any]
) -> pd.DataFrame:
    commodities = _required_panel(panels, "commodities")
    window = _positive_int(parameters, "window", 36)
    momentum_lag = _positive_int(parameters, "momentum_lag", 6)
    oil = _numeric(commodities, "oil", panel_name="commodities").where(
        lambda values: values.gt(0.0)
    )
    gold = _numeric(commodities, "gold", panel_name="commodities").where(
        lambda values: values.gt(0.0)
    )
    oil_gold_ratio = np.log((oil / gold).clip(lower=_EPSILON))
    oil_momentum = np.log(oil).diff(momentum_lag)
    gold_momentum = np.log(gold).diff(momentum_lag)
    relative_momentum = oil_momentum - gold_momentum
    inflation_impulse = _rolling_z(oil_momentum, window)
    shock_divergence = _rolling_z(oil_momentum, window) - _rolling_z(
        gold_momentum, window
    )
    value = _statistic(
        parameters,
        "F110",
        {
            "oil_gold_ratio": oil_gold_ratio,
            "relative_momentum": relative_momentum,
            "inflation_impulse": inflation_impulse,
            "shock_divergence": shock_divergence,
        },
        "relative_momentum",
    )
    return _output(commodities, value, observed_panels=(commodities,))


def evaluate_fundamental_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one F101-F110 formula using published train information only."""

    evaluators = {
        "F101": _f101,
        "F102": _f102,
        "F103": _f103,
        "F104": _f104,
        "F105": _f105,
        "F106": _f106,
        "F107": _f107,
        "F108": _f108,
        "F109": _f109,
        "F110": _f110,
    }
    try:
        evaluator = evaluators[lane_id]
    except KeyError as exc:
        raise FundamentalFeatureEngineError(
            f"FUNDAMENTAL_LANE_NOT_IMPLEMENTED:{lane_id}"
        ) from exc
    return evaluator(input_panels, parameters)


_FUNDAMENTAL_BATCH_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F101": {"statistic": "news_seasonality", "window": 24, "seasonal_window": 3},
    "F102": {"statistic": "composite", "window": 24, "momentum_lag": 6},
    "F103": {"statistic": "decomposition", "window": 24, "growth_lag": 12},
    "F104": {"statistic": "agreement", "window": 12, "change_lag": 4},
    "F105": {
        "statistic": "balance_sheet_capacity",
        "window": 26,
        "growth_lag": 13,
    },
    "F106": {
        "statistic": "stress_composite",
        "window": 63,
        "persistence_window": 20,
    },
    "F107": {"statistic": "recession_pressure", "window": 12},
    "F108": {"statistic": "disagreement", "window": 12, "trend_window": 6},
    "F109": {"statistic": "sentiment_composite", "window": 26},
    "F110": {"statistic": "relative_momentum", "window": 24, "momentum_lag": 6},
}


def evaluate_fundamental_family_batch(
    input_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Run one deterministic smoke configuration for every F101-F110 lane."""

    return {
        lane_id: evaluate_fundamental_lane(lane_id, input_panels, parameters)
        for lane_id, parameters in _FUNDAMENTAL_BATCH_PARAMETERS.items()
    }


__all__ = [
    "FundamentalFeatureEngineError",
    "evaluate_fundamental_family_batch",
    "evaluate_fundamental_lane",
]
