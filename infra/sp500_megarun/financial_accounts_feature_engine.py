"""Causal financial-account kernels for SP500 lanes F201-F210."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


class FinancialAccountsFeatureEngineError(ValueError):
    """Raised when a financial-account input or parameter breaks the contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    **{f"F{index:03d}": ("financial_accounts",) for index in range(201, 209)},
    "F209": ("financial_accounts", "tic"),
    "F210": ("financial_accounts",),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise FinancialAccountsFeatureEngineError(
            f"MISSING_TIMESTAMP_COLUMNS:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result[list(_TIMESTAMPS)].isna().any().any():
        raise FinancialAccountsFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(_TRAIN_END).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise FinancialAccountsFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise FinancialAccountsFeatureEngineError(f"OBSERVED_AFTER_AVAILABILITY:{label}")
    if result["available_at"].gt(result["date"]).any():
        raise FinancialAccountsFeatureEngineError(f"AVAILABLE_AFTER_PANEL_DATE:{label}")
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise FinancialAccountsFeatureEngineError(f"DATES_NOT_STRICTLY_ORDERED:{label}")
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise FinancialAccountsFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
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
        raise FinancialAccountsFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _numeric(frame: pd.DataFrame, columns: Sequence[str], *, label: str) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise FinancialAccountsFeatureEngineError(
            f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}"
        )
    return (
        frame.loc[:, list(columns)]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0.0, np.nan)


def _growth(value: pd.Series, lag: int = 1) -> pd.Series:
    positive = value.where(value.gt(0.0))
    return np.log(positive).diff(lag)


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


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(
        parameters, "direction", ("continuation", "reversal"), "continuation"
    )
    return value if direction == "continuation" else -value


def _align_panel(market: pd.DataFrame, panel: pd.DataFrame, *, label: str) -> pd.DataFrame:
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
        raise FinancialAccountsFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{label}")
    return aligned


def _event_output(
    market: pd.DataFrame,
    source: pd.DataFrame,
    value: pd.Series,
    *,
    label: str,
) -> pd.DataFrame:
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["value"] = pd.to_numeric(value, errors="coerce")
    aligned = _align_panel(market, derived, label=label)
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": aligned["source_observed_at"].fillna(market["observed_at"]),
            "available_at": aligned["source_available_at"].fillna(market["available_at"]),
            "value": pd.to_numeric(aligned["value"], errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _event_lane(
    market: pd.DataFrame,
    source: pd.DataFrame,
    choices: Mapping[str, pd.Series],
    parameters: Mapping[str, Any],
    *,
    default: str,
    label: str,
) -> pd.DataFrame:
    window = _positive(parameters, "window", 8)
    statistic = _choice(parameters, "statistic", tuple(choices), default)
    value = _direction(
        _normalize(choices[statistic], parameters, window=window), parameters
    )
    return _event_output(market, source, value, label=label)


def _financial_values(source: pd.DataFrame) -> pd.DataFrame:
    return _numeric(
        source,
        (
            "household_equity",
            "household_financial_assets",
            "household_liabilities",
            "household_checkable",
            "household_time_deposits",
            "household_mmf",
            "corporate_financial_assets",
            "corporate_liabilities",
            "corporate_checkable",
            "corporate_time_deposits",
            "corporate_mmf",
            "corporate_debt",
            "corporate_net_issuance",
            "mutual_fund_total_assets",
            "mutual_fund_equity",
            "mutual_fund_flow",
            "etf_total_assets",
            "etf_equity",
            "etf_flow",
            "mmf_total_assets",
            "mmf_flow",
            "mmf_treasury",
            "mmf_commercial_paper",
            "broker_total_assets",
            "broker_liabilities",
            "broker_repo_assets",
            "broker_repo_liabilities",
            "foreign_treasury_purchases",
            "foreign_bond_purchases",
            "foreign_equity_purchases",
            "foreign_mutual_fund_purchases",
        ),
        label="financial_accounts",
    ).ffill()


def _f201(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    liquid = values[["household_checkable", "household_time_deposits", "household_mmf"]].sum(axis=1)
    equity_share = _safe_ratio(values["household_equity"], values["household_financial_assets"])
    liquid_share = _safe_ratio(liquid, values["household_financial_assets"])
    window = _positive(parameters, "window", 8)
    choices = {
        "household_equity_share": equity_share,
        "household_liquid_share": liquid_share,
        "equity_liquidity_ratio": _safe_ratio(values["household_equity"], liquid),
        "equity_share_change": equity_share.diff(_positive(parameters, "change_lag", 1)),
        "risk_appetite": _rolling_zscore(equity_share, window)
        - _rolling_zscore(liquid_share, window),
    }
    return _event_lane(
        market, source, choices, parameters, default="household_equity_share", label="f201"
    )


def _f202(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    liquid = values[["household_checkable", "household_time_deposits", "household_mmf"]].sum(axis=1)
    leverage = _safe_ratio(values["household_liabilities"], values["household_financial_assets"])
    liability_growth = _growth(values["household_liabilities"])
    liquidity_growth = _growth(liquid)
    window = _positive(parameters, "window", 8)
    choices = {
        "household_leverage": leverage,
        "liquid_assets_to_liabilities": _safe_ratio(liquid, values["household_liabilities"]),
        "liabilities_growth": liability_growth,
        "liquidity_growth": liquidity_growth,
        "household_balance_composite": _rolling_zscore(liquidity_growth, window)
        - _rolling_zscore(liability_growth, window),
    }
    return _event_lane(
        market, source, choices, parameters, default="household_leverage", label="f202"
    )


def _f203(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    liquid = values[["corporate_checkable", "corporate_time_deposits", "corporate_mmf"]].sum(axis=1)
    leverage = _safe_ratio(values["corporate_liabilities"], values["corporate_financial_assets"])
    liquid_share = _safe_ratio(liquid, values["corporate_financial_assets"])
    liquidity_change = _growth(liquid)
    window = _positive(parameters, "window", 8)
    choices = {
        "corporate_leverage": leverage,
        "corporate_liquid_share": liquid_share,
        "corporate_debt_share": _safe_ratio(values["corporate_debt"], values["corporate_liabilities"]),
        "corporate_liquidity_change": liquidity_change,
        "corporate_balance_composite": _rolling_zscore(liquid_share, window)
        - _rolling_zscore(leverage, window),
    }
    return _event_lane(
        market, source, choices, parameters, default="corporate_leverage", label="f203"
    )


def _f204(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    issuance = values["corporate_net_issuance"]
    ratio = _safe_ratio(issuance, values["corporate_financial_assets"])
    window = _positive(parameters, "window", 8)
    choices = {
        "corporate_net_issuance": issuance,
        "issuance_to_assets": ratio,
        "issuance_change": issuance.diff(_positive(parameters, "change_lag", 1)),
        "issuance_pressure": _rolling_zscore(ratio, window),
    }
    return _event_lane(
        market, source, choices, parameters, default="issuance_to_assets", label="f204"
    )


def _f205(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    equity_share = _safe_ratio(values["mutual_fund_equity"], values["mutual_fund_total_assets"])
    flow_rate = _safe_ratio(values["mutual_fund_flow"] / 4.0, values["mutual_fund_total_assets"].shift(1))
    assets_growth = _growth(values["mutual_fund_total_assets"])
    choices = {
        "mutual_fund_equity_share": equity_share,
        "mutual_fund_flow_rate": flow_rate,
        "mutual_fund_assets_growth": assets_growth,
        "equity_flow_interaction": equity_share * flow_rate,
    }
    return _event_lane(
        market, source, choices, parameters, default="mutual_fund_flow_rate", label="f205"
    )


def _f206(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    equity_share = _safe_ratio(values["etf_equity"], values["etf_total_assets"])
    flow_rate = _safe_ratio(values["etf_flow"] / 4.0, values["etf_total_assets"].shift(1))
    assets_growth = _growth(values["etf_total_assets"])
    mutual_growth = _growth(values["mutual_fund_total_assets"])
    choices = {
        "etf_equity_share": equity_share,
        "etf_flow_rate": flow_rate,
        "etf_assets_growth": assets_growth,
        "etf_mutual_growth_spread": assets_growth - mutual_growth,
    }
    return _event_lane(
        market, source, choices, parameters, default="etf_flow_rate", label="f206"
    )


def _f207(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    assets = values["mmf_total_assets"]
    treasury_share = _safe_ratio(values["mmf_treasury"], assets)
    paper_share = _safe_ratio(values["mmf_commercial_paper"], assets)
    choices = {
        "mmf_flow_rate": _safe_ratio(values["mmf_flow"] / 4.0, assets.shift(1)),
        "mmf_assets_growth": _growth(assets),
        "treasury_share": treasury_share,
        "commercial_paper_share": paper_share,
        "liquidity_preference": treasury_share - paper_share,
    }
    return _event_lane(
        market, source, choices, parameters, default="mmf_flow_rate", label="f207"
    )


def _f208(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    assets = values["broker_total_assets"]
    leverage = _safe_ratio(values["broker_liabilities"], assets)
    assets_growth = _growth(assets)
    window = _positive(parameters, "window", 8)
    choices = {
        "broker_leverage": leverage,
        "repo_funding_share": _safe_ratio(values["broker_repo_liabilities"], assets),
        "repo_asset_share": _safe_ratio(values["broker_repo_assets"], assets),
        "broker_assets_growth": assets_growth,
        "dealer_capacity": _rolling_zscore(assets_growth, window)
        - _rolling_zscore(leverage, window),
    }
    return _event_lane(
        market, source, choices, parameters, default="dealer_capacity", label="f208"
    )


def _foreign_event_panel(financial: pd.DataFrame, tic: pd.DataFrame) -> pd.DataFrame:
    financial_values = _financial_values(financial)
    z1 = financial.loc[:, list(_TIMESTAMPS)].copy()
    z1["z1_foreign_flow"] = financial_values[
        [
            "foreign_treasury_purchases",
            "foreign_bond_purchases",
            "foreign_equity_purchases",
            "foreign_mutual_fund_purchases",
        ]
    ].sum(axis=1)
    right = z1.rename(
        columns={
            "date": "z1_date",
            "observed_at": "z1_observed_at",
            "available_at": "z1_available_at",
        }
    )
    combined = pd.merge_asof(
        tic,
        right,
        left_on="date",
        right_on="z1_date",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="z1_date")
    combined["observed_at"] = pd.concat(
        [combined["observed_at"], combined["z1_observed_at"]], axis=1
    ).max(axis=1)
    combined["available_at"] = pd.concat(
        [combined["available_at"], combined["z1_available_at"]], axis=1
    ).max(axis=1)
    return combined.drop(columns=["z1_observed_at", "z1_available_at"])


def _f209(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = _foreign_event_panel(panels["financial_accounts"], panels["tic"])
    values = _numeric(
        source,
        (
            "tic_treasury_net_purchases",
            "tic_equity_net_purchases",
            "z1_foreign_flow",
        ),
        label="foreign_flow",
    )
    tic_total = values["tic_treasury_net_purchases"] + values["tic_equity_net_purchases"]
    window = _positive(parameters, "window", 8)
    choices = {
        "tic_treasury_flow": values["tic_treasury_net_purchases"],
        "tic_equity_flow": values["tic_equity_net_purchases"],
        "tic_total_flow": tic_total,
        "z1_foreign_flow": values["z1_foreign_flow"],
        "combined_foreign_flow": (
            _rolling_zscore(tic_total, window)
            + _rolling_zscore(values["z1_foreign_flow"], window)
        )
        / 2.0,
        "equity_treasury_divergence": values["tic_equity_net_purchases"]
        - values["tic_treasury_net_purchases"],
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="combined_foreign_flow",
        label="f209",
    )


def _f210(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["financial_accounts"]
    values = _financial_values(source)
    household_to_fund = _safe_ratio(values["household_mmf"], values["mutual_fund_total_assets"])
    fund_to_broker = _safe_ratio(values["mutual_fund_total_assets"], values["broker_total_assets"])
    broker_to_business = _safe_ratio(values["broker_total_assets"], values["corporate_liabilities"])
    repo_share = _safe_ratio(values["broker_repo_liabilities"], values["broker_total_assets"])
    window = _positive(parameters, "window", 8)
    standardized = pd.concat(
        [
            _rolling_zscore(household_to_fund, window),
            _rolling_zscore(fund_to_broker, window),
            _rolling_zscore(broker_to_business, window),
        ],
        axis=1,
    )
    repo_window_count = repo_share.rolling(window, min_periods=window).count()
    repo_score = _rolling_zscore(repo_share, window).fillna(0.0)
    repo_score = repo_score.where(repo_window_count.eq(window))
    choices = {
        "household_to_fund": household_to_fund,
        "fund_to_broker": fund_to_broker,
        "broker_to_business": broker_to_business,
        "interconnection_mean": standardized.mean(axis=1),
        "interconnection_max": standardized.max(axis=1),
        "interconnection_composite": standardized.mean(axis=1)
        + 0.5 * repo_score,
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="interconnection_composite",
        label="f210",
    )


_LANE_KERNELS: Mapping[
    str,
    Callable[[pd.DataFrame, Mapping[str, pd.DataFrame], Mapping[str, Any]], pd.DataFrame],
] = {
    "F201": _f201,
    "F202": _f202,
    "F203": _f203,
    "F204": _f204,
    "F205": _f205,
    "F206": _f206,
    "F207": _f207,
    "F208": _f208,
    "F209": _f209,
    "F210": _f210,
}


def evaluate_financial_accounts_lane(
    lane_id: str,
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F201-F210 lane using only released train rows."""

    if lane_id not in _LANE_KERNELS:
        raise FinancialAccountsFeatureEngineError(f"UNKNOWN_LANE:{lane_id}")
    validated_market = _validated(market, label="market")
    required = _LANE_SOURCES[lane_id]
    missing = sorted(set(required) - set(panels))
    if missing:
        raise FinancialAccountsFeatureEngineError(
            f"SOURCE_PANEL_MISSING:{lane_id}:{','.join(missing)}"
        )
    validated_panels = {
        name: _validated(panels[name], label=name)
        for name in required
    }
    return _LANE_KERNELS[lane_id](validated_market, validated_panels, parameters)


def evaluate_financial_accounts_family_batch(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate one representative, preregistered configuration per lane."""

    defaults: Mapping[str, str] = {
        "F201": "household_equity_share",
        "F202": "household_leverage",
        "F203": "corporate_leverage",
        "F204": "issuance_to_assets",
        "F205": "mutual_fund_flow_rate",
        "F206": "etf_flow_rate",
        "F207": "mmf_flow_rate",
        "F208": "dealer_capacity",
        "F209": "combined_foreign_flow",
        "F210": "interconnection_composite",
    }
    return {
        lane: evaluate_financial_accounts_lane(
            lane,
            market,
            panels,
            {
                "statistic": statistic,
                "window": 8,
                "change_lag": 1,
                "normalization": "raw",
                "direction": "continuation",
            },
        )
        for lane, statistic in defaults.items()
    }


__all__ = [
    "FinancialAccountsFeatureEngineError",
    "evaluate_financial_accounts_family_batch",
    "evaluate_financial_accounts_lane",
]
