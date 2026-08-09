"""Causal execution kernels for SP500 macro families beginning at F032."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class MacroFeatureEngineError(ValueError):
    """Raised when a macro input is incomplete, non-causal or non-train."""


_TRAIN_END = pd.Timestamp("2010-12-31")


def _validated_panel(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "observed_at", "available_at"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MacroFeatureEngineError(f"PANEL_COLUMNS_MISSING:{name}:{','.join(missing)}")
    panel = frame.copy()
    for column in required:
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.normalize()
    if panel[list(required)].isna().any().any():
        raise MacroFeatureEngineError(f"INVALID_PANEL_DATE:{name}")
    if panel["date"].gt(_TRAIN_END).any() or panel["available_at"].gt(_TRAIN_END).any():
        raise MacroFeatureEngineError(f"NON_TRAIN_PANEL_ROW:{name}")
    if panel["available_at"].gt(panel["date"]).any():
        raise MacroFeatureEngineError(f"PANEL_NOT_AVAILABLE_AT_DECISION:{name}")
    if panel["observed_at"].gt(panel["available_at"]).any():
        raise MacroFeatureEngineError(f"PANEL_OBSERVED_AFTER_AVAILABILITY:{name}")
    if panel["date"].duplicated().any() or not panel["date"].is_monotonic_increasing:
        raise MacroFeatureEngineError(f"PANEL_DATES_NOT_ORDERED:{name}")
    return panel.reset_index(drop=True)


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    deviation = values.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    return (values - mean) / deviation


def _required_panel(
    input_panels: Mapping[str, pd.DataFrame],
    name: str,
) -> pd.DataFrame:
    if name not in input_panels:
        raise MacroFeatureEngineError(f"MACRO_PANELS_MISSING:{name}")
    return _validated_panel(name, input_panels[name])


def _align_state(master: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(master["date"])
    aligned = updates.set_index("date").reindex(calendar)
    aligned.index.name = "date"
    aligned = aligned.ffill().reset_index()
    stale_future = aligned["available_at"].gt(aligned["date"])
    if stale_future.fillna(False).any():
        raise MacroFeatureEngineError("FORWARD_FILLED_FUTURE_MACRO_INPUT")
    return aligned


def _max_observed(panels: Sequence[pd.DataFrame]) -> pd.Series:
    return pd.concat([panel["observed_at"] for panel in panels], axis=1).max(axis=1)


def _output(
    master: pd.DataFrame,
    value: pd.Series,
    *,
    observed_panels: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": master["date"],
            "observed_at": _max_observed(observed_panels),
            "available_at": master["date"],
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _numeric(panel: pd.DataFrame, column: str, *, panel_name: str) -> pd.Series:
    if column not in panel:
        raise MacroFeatureEngineError(f"PANEL_VALUE_MISSING:{panel_name}:{column}")
    return pd.to_numeric(panel[column], errors="coerce")


def _log_return(level: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(level, errors="coerce").where(lambda item: item.gt(0.0))
    return np.log(numeric).diff()


def _rolling_log_momentum(level: pd.Series, window: int) -> pd.Series:
    return _log_return(level).rolling(window, min_periods=window).sum()


def _industry_columns(panel: pd.DataFrame) -> list[str]:
    excluded = {"date", "observed_at", "available_at"}
    return [column for column in panel.columns if column not in excluded]


def evaluate_macro_lane(
    lane_id: str,
    input_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen macro formula on data available by each decision date."""

    window = int(parameters.get("window", 252))
    change_lag = int(parameters.get("change_lag", 5))
    if lane_id == "F032":
        credit = _required_panel(input_panels, "credit")
        spread = _numeric(credit, "baa_aaa_spread", panel_name="credit")
        change = spread.diff(change_lag)
        acceleration = change.diff(change_lag)
        value = _rolling_z(change + acceleration, window)
        return _output(credit, value, observed_panels=(credit,))

    if lane_id == "F033":
        financial = _required_panel(input_panels, "financial")
        realtime = _align_state(
            financial,
            _required_panel(input_panels, "realtime"),
        )
        conditions = _numeric(
            financial,
            "financial_conditions_score",
            panel_name="financial",
        )
        realtime_growth = _numeric(
            realtime,
            "realtime_output_growth",
            panel_name="realtime",
        )
        value = (
            _rolling_z(conditions, window)
            + _rolling_z(conditions.diff(change_lag), window)
            - _rolling_z(realtime_growth, window)
        )
        return _output(financial, value, observed_panels=(financial, realtime))

    if lane_id == "F034":
        rates = _required_panel(input_panels, "rates")
        macro = _align_state(rates, _required_panel(input_panels, "macro"))
        nominal = _numeric(rates, "yield_10y", panel_name="rates")
        inflation = _numeric(macro, "cpi_first", panel_name="macro")
        real_rate = nominal - inflation
        value = _rolling_z(real_rate, window) + 0.5 * _rolling_z(
            real_rate.diff(change_lag), window
        )
        return _output(rates, value, observed_panels=(rates, macro))

    if lane_id in {"F035", "F036", "F037"}:
        macro = _required_panel(input_panels, "macro")
        macro_state = macro.copy()
        value_columns = [
            column
            for column in macro_state.columns
            if column not in {"date", "observed_at", "available_at"}
        ]
        macro_state[value_columns] = macro_state[value_columns].ffill()
        if lane_id == "F035":
            realtime = _align_state(
                macro_state,
                _required_panel(input_panels, "realtime"),
            )
            growth = pd.concat(
                [
                    _numeric(macro_state, "output_first", panel_name="macro"),
                    _numeric(macro_state, "consumption_first", panel_name="macro"),
                    _numeric(
                        realtime,
                        "realtime_output_growth",
                        panel_name="realtime",
                    ),
                ],
                axis=1,
            ).mean(axis=1)
            change = growth.diff()
            value = (
                _rolling_z(growth, window)
                + 0.5 * _rolling_z(change, window)
                + 0.25 * _rolling_z(change.diff(), window)
            )
            return _output(macro_state, value, observed_panels=(macro_state, realtime))
        if lane_id == "F036":
            payroll = _numeric(macro_state, "payroll_first", panel_name="macro")
            revision = _numeric(
                macro_state,
                "payroll_revision",
                panel_name="macro",
            )
            value = _rolling_z(payroll, window) + 0.5 * _rolling_z(
                revision, window
            )
            return _output(macro_state, value, observed_panels=(macro_state,))
        industrial = _numeric(
            macro_state,
            "industrial_production_first",
            panel_name="macro",
        )
        housing = _numeric(
            macro_state,
            "housing_starts_first",
            panel_name="macro",
        ).pct_change(fill_method=None) * 100.0
        consumption = _numeric(
            macro_state,
            "consumption_first",
            panel_name="macro",
        )
        value = pd.concat(
            [
                _rolling_z(industrial, window),
                _rolling_z(housing, window),
                _rolling_z(consumption, window),
            ],
            axis=1,
        ).mean(axis=1, skipna=False)
        return _output(macro_state, value, observed_panels=(macro_state,))

    if lane_id == "F038":
        calendar = _required_panel(input_panels, "calendar")
        macro = _required_panel(input_panels, "macro")
        fomc = _required_panel(input_panels, "fomc")
        calendar_index = pd.DatetimeIndex(calendar["date"])
        macro_value_columns = [
            column
            for column in macro.columns
            if column.endswith("_first") or column.endswith("_revision")
        ]
        macro_count = macro[macro_value_columns].notna().sum(axis=1).astype(float)
        macro_events = pd.Series(
            macro_count.to_numpy(), index=pd.DatetimeIndex(macro["date"])
        ).reindex(calendar_index, fill_value=0.0)
        fomc_events = pd.Series(
            _numeric(fomc, "fomc_event_count", panel_name="fomc").to_numpy(),
            index=pd.DatetimeIndex(fomc["date"]),
        ).reindex(calendar_index, fill_value=0.0)
        positions = pd.Series(np.arange(len(calendar), dtype=float), index=calendar_index)
        last_macro = positions.where(macro_events.gt(0.0)).ffill()
        last_fomc = positions.where(fomc_events.gt(0.0)).ffill()
        days_since_macro = (positions - last_macro).fillna(float(len(calendar)))
        days_since_fomc = (positions - last_fomc).fillna(float(len(calendar)))
        event_window = int(parameters.get("event_window", 20))
        density = (macro_events + fomc_events).rolling(
            event_window, min_periods=1
        ).sum() / float(event_window)
        raw_state = (
            1.0 / (1.0 + days_since_macro)
            + 1.0 / (1.0 + days_since_fomc)
            + density
        )
        normalization_window = int(parameters.get("normalization_window", 252))
        value = _rolling_z(raw_state.reset_index(drop=True), normalization_window)
        macro_state = _align_state(calendar, macro)
        fomc_state = _align_state(calendar, fomc)
        return _output(calendar, value, observed_panels=(calendar, macro_state, fomc_state))

    if lane_id == "F039":
        rates = _required_panel(input_panels, "rates")
        valuation = _align_state(
            rates,
            _required_panel(input_panels, "valuation"),
        )
        cheapness = pd.concat(
            [
                _rolling_z(
                    _numeric(valuation, "dividend_yield", panel_name="valuation"),
                    window,
                ),
                _rolling_z(
                    _numeric(valuation, "earnings_yield", panel_name="valuation"),
                    window,
                ),
                _rolling_z(
                    _numeric(valuation, "book_to_market", panel_name="valuation"),
                    window,
                ),
                _rolling_z(
                    _numeric(valuation, "inverse_cape", panel_name="valuation"),
                    window,
                ),
            ],
            axis=1,
        ).mean(axis=1, skipna=False)
        nominal_yield = _numeric(rates, "yield_10y", panel_name="rates")
        value = cheapness - 0.5 * _rolling_z(nominal_yield, window)
        return _output(rates, value, observed_panels=(rates, valuation))

    if lane_id == "F040":
        valuation = _required_panel(input_panels, "valuation")
        earnings_lag = int(parameters.get("earnings_lag", 12))
        issuance = -_numeric(
            valuation,
            "net_equity_issuance",
            panel_name="valuation",
        )
        payout = _numeric(valuation, "payout_ratio", panel_name="valuation")
        earnings_growth = _numeric(
            valuation,
            "aggregate_earnings",
            panel_name="valuation",
        ).pct_change(earnings_lag, fill_method=None)
        value = pd.concat(
            [
                _rolling_z(issuance, window),
                _rolling_z(payout, window),
                _rolling_z(earnings_growth, window),
            ],
            axis=1,
        ).mean(axis=1, skipna=False)
        return _output(valuation, value, observed_panels=(valuation,))

    if lane_id in {"F041", "F049"}:
        market = _required_panel(input_panels, "market")
        balance = _required_panel(input_panels, "balance")
        margin = _required_panel(input_panels, "margin")
        positioning = _required_panel(input_panels, "positioning")
        slow_window = int(parameters.get("slow_window", 12))
        margin_window = int(parameters.get("margin_window", 24))
        positioning_window = int(parameters.get("positioning_window", 52))

        household_share = _numeric(
            balance, "household_equity_share", panel_name="balance"
        )
        mutual_share = _numeric(
            balance, "mutual_fund_equity_share", panel_name="balance"
        )
        debit = _numeric(margin, "margin_debit", panel_name="margin")
        margin_ratio = _numeric(
            margin, "margin_debit_to_credit", panel_name="margin"
        )
        open_interest = _numeric(
            positioning, "open_interest", panel_name="positioning"
        )
        noncommercial = _numeric(
            positioning, "noncommercial_net_pct_oi", panel_name="positioning"
        )
        commercial = _numeric(
            positioning, "commercial_net_pct_oi", panel_name="positioning"
        )

        balance_state = balance.copy()
        margin_state = margin.copy()
        positioning_state = positioning.copy()
        if lane_id == "F041":
            balance_state["state"] = pd.concat(
                [
                    _rolling_z(household_share, slow_window),
                    _rolling_z(household_share.diff(), slow_window),
                ],
                axis=1,
            ).mean(axis=1, skipna=False)
            margin_state["state"] = _rolling_z(
                np.log(margin_ratio), margin_window
            ) + 0.5 * _rolling_z(np.log(margin_ratio).diff(), margin_window)
            disagreement = (noncommercial + commercial).abs()
            positioning_state["state"] = _rolling_z(
                noncommercial, positioning_window
            ) - 0.5 * _rolling_z(disagreement, positioning_window)
        else:
            balance_state["state"] = _rolling_z(
                mutual_share.pct_change(fill_method=None), slow_window
            )
            margin_state["state"] = _rolling_z(
                debit.pct_change(fill_method=None), margin_window
            )
            positioning_state["state"] = _rolling_z(
                noncommercial.diff(), positioning_window
            ) + 0.5 * _rolling_z(
                open_interest.pct_change(fill_method=None), positioning_window
            )

        aligned_balance = _align_state(market, balance_state)
        aligned_margin = _align_state(market, margin_state)
        aligned_positioning = _align_state(market, positioning_state)
        value = pd.concat(
            [
                _numeric(aligned_balance, "state", panel_name="balance"),
                _numeric(aligned_margin, "state", panel_name="margin"),
                _numeric(aligned_positioning, "state", panel_name="positioning"),
            ],
            axis=1,
        ).mean(axis=1, skipna=False)
        return _output(
            market,
            value,
            observed_panels=(
                market,
                aligned_balance,
                aligned_margin,
                aligned_positioning,
            ),
        )

    if lane_id == "F042":
        market = _required_panel(input_panels, "market")
        rates = _align_state(market, _required_panel(input_panels, "rates"))
        duration = float(parameters.get("duration", 7))
        equity_return = _log_return(_numeric(market, "close", panel_name="market"))
        yield_change = _numeric(rates, "yield_10y", panel_name="rates").diff() / 100.0
        bond_return = -duration * yield_change
        relative_momentum = (
            bond_return.rolling(window, min_periods=window).sum()
            - equity_return.rolling(window, min_periods=window).sum()
        )
        correlation = equity_return.rolling(window, min_periods=window).corr(
            bond_return
        )
        value = relative_momentum - 0.25 * correlation
        return _output(market, value, observed_panels=(market, rates))

    if lane_id == "F043":
        market = _required_panel(input_panels, "market")
        fx = _align_state(market, _required_panel(input_panels, "fx"))
        commodities = _align_state(
            market, _required_panel(input_panels, "commodities")
        )
        equity_momentum = _rolling_log_momentum(
            _numeric(market, "close", panel_name="market"), window
        )
        dollar_momentum = _rolling_log_momentum(
            _numeric(fx, "broad_dollar", panel_name="fx"), window
        )
        gold_momentum = _rolling_log_momentum(
            _numeric(commodities, "gold", panel_name="commodities"), window
        )
        oil_momentum = _rolling_log_momentum(
            _numeric(commodities, "oil", panel_name="commodities"), window
        )
        equity_volatility = _log_return(
            _numeric(market, "close", panel_name="market")
        ).rolling(window, min_periods=window).std(ddof=0)
        cross_asset_volatility = pd.concat(
            [
                _log_return(_numeric(fx, "broad_dollar", panel_name="fx")),
                _log_return(
                    _numeric(commodities, "gold", panel_name="commodities")
                ),
                _log_return(
                    _numeric(commodities, "oil", panel_name="commodities")
                ),
            ],
            axis=1,
        ).std(axis=1).rolling(window, min_periods=window).mean()
        shock_ratio = cross_asset_volatility / equity_volatility.replace(0.0, np.nan)
        value = pd.concat(
            [
                gold_momentum - equity_momentum,
                dollar_momentum - equity_momentum,
                oil_momentum - equity_momentum,
                shock_ratio,
            ],
            axis=1,
        ).mean(axis=1, skipna=False)
        return _output(
            market, value, observed_panels=(market, fx, commodities)
        )

    if lane_id in {"F044", "F046", "F047", "F048"}:
        industries = _required_panel(input_panels, "industries")
        columns = _industry_columns(industries)
        returns = industries[columns].apply(pd.to_numeric, errors="coerce")
        if returns.shape[1] < 2:
            raise MacroFeatureEngineError("INDUSTRY_PANEL_TOO_NARROW")

        if lane_id == "F044":
            factors = _align_state(
                industries, _required_panel(input_panels, "factors")
            )
            cyclical_names = {
                "Autos", "Cnstr", "Steel", "Mach", "Chips", "Fin", "Rtail", "Trans"
            }
            defensive_names = {"Food", "Beer", "Smoke", "Hlth", "Drugs", "Util"}
            cyclicals = [column for column in columns if column in cyclical_names]
            defensives = [column for column in columns if column in defensive_names]
            if not cyclicals or not defensives:
                raise MacroFeatureEngineError("INDUSTRY_LEADERSHIP_GROUPS_MISSING")
            sector_leadership = (
                returns[cyclicals].mean(axis=1)
                - returns[defensives].mean(axis=1)
            ).rolling(window, min_periods=window).sum()
            size_leadership = _numeric(factors, "smb", panel_name="factors").rolling(
                window, min_periods=window
            ).sum()
            style_leadership = _numeric(factors, "hml", panel_name="factors").rolling(
                window, min_periods=window
            ).sum()
            value = pd.concat(
                [size_leadership, style_leadership, sector_leadership], axis=1
            ).mean(axis=1, skipna=False)
            return _output(
                industries, value, observed_panels=(industries, factors)
            )

        if lane_id == "F046":
            threshold = float(parameters.get("threshold", 0.0))
            daily_breadth = returns.gt(threshold).mean(axis=1) - returns.lt(
                -threshold
            ).mean(axis=1)
            value = daily_breadth.rolling(window, min_periods=window).mean()
            return _output(industries, value, observed_panels=(industries,))

        if lane_id == "F047":
            wealth = (1.0 + returns).cumprod()
            rolling_high = wealth.rolling(window, min_periods=window).max()
            rolling_low = wealth.rolling(window, min_periods=window).min()
            moving_average = wealth.rolling(window, min_periods=window).mean()
            high_breadth = wealth.ge(rolling_high).mean(axis=1)
            low_breadth = wealth.le(rolling_low).mean(axis=1)
            average_breadth = wealth.gt(moving_average).mean(axis=1) - 0.5
            value = high_breadth - low_breadth + average_breadth
            value.loc[rolling_high.isna().all(axis=1)] = np.nan
            return _output(industries, value, observed_panels=(industries,))

        dispersion = returns.std(axis=1, ddof=0)
        equal_weight_return = returns.mean(axis=1)
        common_correlation = pd.concat(
            [
                returns[column].rolling(window, min_periods=window).corr(
                    equal_weight_return
                )
                for column in columns
            ],
            axis=1,
        ).mean(axis=1)
        absolute = returns.abs()
        shares = absolute.div(absolute.sum(axis=1).replace(0.0, np.nan), axis=0)
        concentration = shares.pow(2).sum(axis=1)
        value = (
            _rolling_z(dispersion, window)
            - _rolling_z(common_correlation, window)
            - _rolling_z(concentration, window)
        )
        return _output(industries, value, observed_panels=(industries,))

    if lane_id == "F045":
        fx = _required_panel(input_panels, "fx")
        currency_columns = [
            column for column in fx.columns if column.startswith("fx_")
        ]
        if len(currency_columns) < 3:
            raise MacroFeatureEngineError("FX_CONTAGION_PANEL_TOO_NARROW")
        returns = fx[currency_columns].apply(_log_return)
        standardized = returns.apply(lambda series: _rolling_z(series, window))
        threshold = float(parameters.get("shock_threshold", 2.0))
        stress = standardized.abs().mean(axis=1)
        breadth = standardized.abs().gt(threshold).mean(axis=1)
        disagreement = standardized.std(axis=1, ddof=0)
        value = -(stress + breadth + 0.5 * disagreement)
        value.loc[standardized.isna().any(axis=1)] = np.nan
        return _output(fx, value, observed_panels=(fx,))

    if lane_id == "F050":
        calendar = _required_panel(input_panels, "calendar")
        rule = str(parameters.get("calendar_rule", "turn_of_month"))
        hold = int(parameters.get("hold", 3))
        weekday = _numeric(calendar, "weekday", panel_name="calendar").astype(int)
        month = _numeric(calendar, "month", panel_name="calendar").astype(int)
        session_of_month = _numeric(
            calendar, "session_of_month", panel_name="calendar"
        )
        remaining = _numeric(
            calendar, "sessions_remaining_month", panel_name="calendar"
        )
        if rule == "turn_of_month":
            active = session_of_month.le(hold) | remaining.lt(hold)
        elif rule == "month_end":
            active = remaining.lt(hold)
        elif rule == "quarter_end":
            active = month.mod(3).eq(0) & remaining.lt(hold)
        elif rule == "weekday":
            active = weekday.eq(int(parameters.get("target_weekday", 0)))
        elif rule == "month":
            active = month.eq(int(parameters.get("target_month", 1)))
        elif rule == "sell_in_may":
            value = pd.Series(np.where(month.isin([11, 12, 1, 2, 3, 4]), 1.0, -1.0))
            return _output(calendar, value, observed_panels=(calendar,))
        else:
            raise MacroFeatureEngineError(f"UNKNOWN_CALENDAR_RULE:{rule}")
        value = active.astype(float).mul(2.0).sub(1.0)
        return _output(calendar, value, observed_panels=(calendar,))

    raise MacroFeatureEngineError(f"MACRO_LANE_NOT_IMPLEMENTED:{lane_id}")


__all__ = ["MacroFeatureEngineError", "evaluate_macro_lane"]
