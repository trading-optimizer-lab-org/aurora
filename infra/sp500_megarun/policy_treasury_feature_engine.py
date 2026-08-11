"""Causal train-only policy, Treasury and TIC kernels for F221-F230."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


class PolicyTreasuryFeatureEngineError(ValueError):
    """Raised when F221-F230 violate their frozen causal contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F221": ("decisions", "policy_rate"),
    "F222": ("statements",),
    "F223": ("minutes",),
    "F224": ("statements", "minutes"),
    "F225": ("auctions",),
    "F226": ("auctions",),
    "F227": ("auctions",),
    "F228": ("debt",),
    "F229": ("tic",),
    "F230": ("decisions", "monetary", "auctions", "tic"),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise PolicyTreasuryFeatureEngineError(
            f"TIMESTAMP_COLUMNS_MISSING:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result.loc[:, list(_TIMESTAMPS)].isna().any().any():
        raise PolicyTreasuryFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(_TRAIN_END).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise PolicyTreasuryFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise PolicyTreasuryFeatureEngineError(
            f"OBSERVED_AFTER_AVAILABILITY:{label}"
        )
    if result["available_at"].gt(result["date"]).any():
        raise PolicyTreasuryFeatureEngineError(
            f"AVAILABLE_AFTER_PANEL_DATE:{label}"
        )
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise PolicyTreasuryFeatureEngineError(
            f"DATES_NOT_STRICTLY_ORDERED:{label}"
        )
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise PolicyTreasuryFeatureEngineError(
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
        raise PolicyTreasuryFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _numeric(frame: pd.DataFrame, columns: Sequence[str], *, label: str) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise PolicyTreasuryFeatureEngineError(
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
    return np.log(value.where(value.gt(0.0))).diff(lag)


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
    mode = _choice(
        parameters,
        "normalization",
        ("raw", "change", "rolling_zscore"),
        "raw",
    )
    if mode == "change":
        return value.diff(_positive(parameters, "change_lag", 1))
    if mode == "rolling_zscore":
        return _rolling_zscore(value, window)
    return value


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(
        parameters,
        "direction",
        ("continuation", "reversal"),
        "continuation",
    )
    return value if direction == "continuation" else -value


def _align_panel(market: pd.DataFrame, panel: pd.DataFrame, *, label: str) -> pd.DataFrame:
    values = [column for column in panel if column not in _TIMESTAMPS]
    rename = {
        "date": f"{label}_source_date",
        "observed_at": f"{label}_source_observed_at",
        "available_at": f"{label}_source_available_at",
        **{column: f"{label}_{column}" for column in values},
    }
    right = panel.rename(columns=rename)
    aligned = pd.merge_asof(
        market.loc[:, ["date"]],
        right.sort_values(f"{label}_source_date", kind="mergesort"),
        left_on="date",
        right_on=f"{label}_source_date",
        direction="backward",
        allow_exact_matches=True,
    )
    if aligned[f"{label}_source_available_at"].gt(aligned["date"]).fillna(False).any():
        raise PolicyTreasuryFeatureEngineError(
            f"FORWARD_FILLED_FUTURE_INPUT:{label}"
        )
    return aligned


def _output(
    market: pd.DataFrame,
    alignments: Sequence[tuple[str, pd.DataFrame]],
    value: pd.Series,
) -> pd.DataFrame:
    observed = pd.concat(
        [aligned[f"{label}_source_observed_at"] for label, aligned in alignments],
        axis=1,
    ).max(axis=1)
    available = pd.concat(
        [aligned[f"{label}_source_available_at"] for label, aligned in alignments],
        axis=1,
    ).max(axis=1)
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": observed.fillna(market["observed_at"]),
            "available_at": available.fillna(market["available_at"]),
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _daily_choice(
    market: pd.DataFrame,
    alignments: Sequence[tuple[str, pd.DataFrame]],
    choices: Mapping[str, pd.Series],
    parameters: Mapping[str, Any],
    *,
    default: str,
) -> pd.DataFrame:
    window = _positive(parameters, "window", 13)
    statistic = _choice(parameters, "statistic", tuple(choices), default)
    value = _direction(
        _normalize(choices[statistic], parameters, window=window), parameters
    )
    return _output(market, alignments, value)


def _event_choice(
    market: pd.DataFrame,
    source: pd.DataFrame,
    choices: Mapping[str, pd.Series],
    parameters: Mapping[str, Any],
    *,
    default: str,
    label: str,
) -> pd.DataFrame:
    window = _positive(parameters, "window", 13)
    statistic = _choice(parameters, "statistic", tuple(choices), default)
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["feature"] = _direction(
        _normalize(choices[statistic], parameters, window=window), parameters
    )
    aligned = _align_panel(market, derived, label=label)
    return _output(market, [(label, aligned)], aligned[f"{label}_feature"])


def _f221(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    decisions = panels["decisions"]
    decision_values = _numeric(
        decisions,
        ("meeting_count", "statement_count", "conference_call"),
        label="decisions",
    )
    rates = panels["policy_rate"].rename(
        columns={
            "date": "rate_date",
            "observed_at": "rate_observed_at",
            "available_at": "rate_available_at",
        }
    )
    rate_values = _numeric(rates, ("effective_fed_funds",), label="policy_rate")
    rates = rates.assign(effective_fed_funds=rate_values["effective_fed_funds"])
    state = pd.merge_asof(
        decisions.copy(),
        rates.loc[
            :, ["rate_date", "rate_observed_at", "rate_available_at", "effective_fed_funds"]
        ].sort_values("rate_date", kind="mergesort"),
        left_on="date",
        right_on="rate_date",
        direction="backward",
    )
    state["observed_at"] = pd.concat(
        [state["observed_at"], state["rate_observed_at"]], axis=1
    ).max(axis=1)
    state["available_at"] = pd.concat(
        [state["available_at"], state["rate_available_at"]], axis=1
    ).max(axis=1)
    lag = _positive(parameters, "change_lag", 1)
    rate_change = state["effective_fed_funds"].diff(lag)
    state["decision_rate_change"] = rate_change
    state["decision_direction"] = np.sign(rate_change)
    state["decision_magnitude"] = rate_change.abs()
    state["meeting_statement_balance"] = (
        decision_values["meeting_count"] - decision_values["statement_count"]
    )
    state["conference_call"] = decision_values["conference_call"]
    state = state.loc[
        :,
        [
            "date",
            "observed_at",
            "available_at",
            "decision_rate_change",
            "decision_direction",
            "decision_magnitude",
            "meeting_statement_balance",
            "conference_call",
        ],
    ]
    aligned = _align_panel(market, state, label="decision")
    days_since = (aligned["date"] - aligned["decision_source_date"]).dt.days.astype(float)
    choices = {
        "decision_rate_change": aligned["decision_decision_rate_change"],
        "decision_direction": aligned["decision_decision_direction"],
        "decision_magnitude": aligned["decision_decision_magnitude"],
        "days_since_decision": days_since,
        "meeting_statement_balance": aligned["decision_meeting_statement_balance"],
        "conference_call": aligned["decision_conference_call"],
    }
    return _daily_choice(
        market,
        [("decision", aligned)],
        choices,
        parameters,
        default="decision_rate_change",
    )


def _f222(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["statements"]
    values = _numeric(source, ("gap_days", "frequency_per_year"), label="statements")
    gap = values["gap_days"]
    window = _positive(parameters, "window", 13)
    median = gap.rolling(window, min_periods=window).median()
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["statement_gap"] = gap
    derived["statement_gap_change"] = gap.diff(_positive(parameters, "change_lag", 1))
    derived["statement_gap_zscore"] = _rolling_zscore(gap, window)
    derived["statement_frequency"] = values["frequency_per_year"]
    derived["statement_irregularity"] = (gap - median).abs()
    aligned = _align_panel(market, derived, label="statement")
    choices = {
        name: aligned[f"statement_{name}"]
        for name in (
            "statement_gap",
            "statement_gap_change",
            "statement_gap_zscore",
            "statement_frequency",
            "statement_irregularity",
        )
    }
    choices["days_since_statement"] = (
        aligned["date"] - aligned["statement_source_date"]
    ).dt.days.astype(float)
    return _daily_choice(
        market,
        [("statement", aligned)],
        choices,
        parameters,
        default="statement_gap_zscore",
    )


def _f223(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["minutes"]
    values = _numeric(
        source,
        ("gap_days", "frequency_per_year", "decision_lag_days"),
        label="minutes",
    )
    window = _positive(parameters, "window", 13)
    lag = _positive(parameters, "change_lag", 1)
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["publication_lag"] = values["decision_lag_days"]
    derived["publication_lag_change"] = values["decision_lag_days"].diff(lag)
    derived["publication_lag_zscore"] = _rolling_zscore(
        values["decision_lag_days"], window
    )
    derived["minutes_gap"] = values["gap_days"]
    derived["minutes_gap_zscore"] = _rolling_zscore(values["gap_days"], window)
    derived["minutes_frequency"] = values["frequency_per_year"]
    aligned = _align_panel(market, derived, label="minutes")
    choices = {
        name: aligned[f"minutes_{name}"]
        for name in (
            "publication_lag",
            "publication_lag_change",
            "publication_lag_zscore",
            "minutes_gap",
            "minutes_gap_zscore",
            "minutes_frequency",
        )
    }
    choices["days_since_minutes"] = (
        aligned["date"] - aligned["minutes_source_date"]
    ).dt.days.astype(float)
    return _daily_choice(
        market,
        [("minutes", aligned)],
        choices,
        parameters,
        default="publication_lag_zscore",
    )


def _f224(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    statements = panels["statements"]
    minutes = panels["minutes"]
    statement_values = _numeric(statements, ("gap_days",), label="statements")
    minute_values = _numeric(
        minutes, ("gap_days", "decision_lag_days"), label="minutes"
    )
    window = _positive(parameters, "window", 13)
    statement_state = statements.loc[:, list(_TIMESTAMPS)].copy()
    statement_state["gap"] = statement_values["gap_days"]
    statement_state["gap_z"] = _rolling_zscore(statement_values["gap_days"], window)
    minute_state = minutes.loc[:, list(_TIMESTAMPS)].copy()
    minute_state["gap"] = minute_values["gap_days"]
    minute_state["gap_z"] = _rolling_zscore(minute_values["gap_days"], window)
    minute_state["decision_lag"] = minute_values["decision_lag_days"]
    statement_aligned = _align_panel(market, statement_state, label="statement")
    minute_aligned = _align_panel(market, minute_state, label="minutes")
    recency = (
        statement_aligned["statement_source_date"]
        - minute_aligned["minutes_source_date"]
    ).dt.days.astype(float)
    cadence_gap = statement_aligned["statement_gap"] - minute_aligned["minutes_gap"]
    choices = {
        "cadence_gap": cadence_gap,
        "cadence_disagreement": cadence_gap.abs(),
        "publication_recency_gap": recency.abs(),
        "publication_order": np.sign(recency),
        "joint_irregularity": (
            statement_aligned["statement_gap_z"].abs()
            + minute_aligned["minutes_gap_z"].abs()
            + _rolling_zscore(minute_aligned["minutes_decision_lag"], window).abs()
        ),
    }
    return _daily_choice(
        market,
        [("statement", statement_aligned), ("minutes", minute_aligned)],
        choices,
        parameters,
        default="cadence_disagreement",
    )


def _auction_values(source: pd.DataFrame) -> pd.DataFrame:
    return _numeric(
        source,
        (
            "auction_count",
            "offering_amount",
            "accepted_amount",
            "tendered_amount",
            "acceptance_to_offer",
            "bid_to_cover",
            "clearing_rate",
            "weighted_maturity_years",
            "bill_share",
            "note_bond_share",
            "long_term_share",
            "reopening_share",
            "maturity_hhi",
        ),
        label="auctions",
    )


def _f225(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["auctions"]
    values = _auction_values(source)
    choices = {
        "offering_amount": values["offering_amount"],
        "accepted_amount": values["accepted_amount"],
        "tendered_amount": values["tendered_amount"],
        "acceptance_to_offer": values["acceptance_to_offer"],
        "offer_growth": _growth(
            values["offering_amount"], _positive(parameters, "change_lag", 1)
        ),
        "accepted_minus_offering": (
            values["accepted_amount"] - values["offering_amount"]
        ),
    }
    return _event_choice(
        market, source, choices, parameters, default="offer_growth", label="auction_f225"
    )


def _f226(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["auctions"]
    values = _auction_values(source)
    window = _positive(parameters, "window", 13)
    lag = _positive(parameters, "change_lag", 1)
    choices = {
        "bid_to_cover": values["bid_to_cover"],
        "clearing_rate": values["clearing_rate"],
        "yield_change": values["clearing_rate"].diff(lag),
        "demand_change": values["bid_to_cover"].diff(lag),
        "demand_yield_balance": (
            _rolling_zscore(values["bid_to_cover"], window)
            - _rolling_zscore(values["clearing_rate"], window)
        ),
        "auction_count": values["auction_count"],
    }
    return _event_choice(
        market, source, choices, parameters, default="bid_to_cover", label="auction_f226"
    )


def _f227(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["auctions"]
    values = _auction_values(source)
    window = _positive(parameters, "window", 13)
    offering_z = _rolling_zscore(values["offering_amount"], window)
    choices = {
        "weighted_maturity": values["weighted_maturity_years"],
        "bill_share": values["bill_share"],
        "note_bond_share": values["note_bond_share"],
        "long_term_share": values["long_term_share"],
        "reopening_share": values["reopening_share"],
        "maturity_hhi": values["maturity_hhi"],
        "refinancing_pressure": offering_z * (
            values["bill_share"] + values["reopening_share"]
        ),
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="refinancing_pressure",
        label="auction_f227",
    )


def _f228(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["debt"]
    values = _numeric(
        source, ("total_debt", "public_debt", "intragov_debt"), label="debt"
    ).ffill()
    lag = _positive(parameters, "change_lag", 1)
    window = _positive(parameters, "window", 13)
    growth = _growth(values["total_debt"], lag)
    public_share = _safe_ratio(values["public_debt"], values["total_debt"])
    intragov_share = _safe_ratio(values["intragov_debt"], values["total_debt"])
    choices = {
        "total_debt": values["total_debt"],
        "debt_growth": growth,
        "debt_acceleration": growth.diff(lag),
        "public_debt_share": public_share,
        "intragov_share": intragov_share,
        "composition_change": public_share.diff(lag),
        "debt_growth_zscore": _rolling_zscore(growth, window),
    }
    return _event_choice(
        market, source, choices, parameters, default="debt_growth", label="debt_f228"
    )


def _f229(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["tic"]
    values = _numeric(
        source,
        (
            "tic_treasury_net_purchases",
            "tic_treasury_official",
            "tic_equity_net_purchases",
            "tic_equity_official",
        ),
        label="tic",
    )
    treasury = values["tic_treasury_net_purchases"]
    equity = values["tic_equity_net_purchases"]
    official = values["tic_treasury_official"] + values["tic_equity_official"]
    combined = treasury + equity
    absolute_total = treasury.abs() + equity.abs()
    choices = {
        "combined_net_purchases": combined,
        "official_combined_flow": official,
        "private_combined_flow": combined - official,
        "equity_flow_share": _safe_ratio(equity, absolute_total),
        "treasury_official_share": _safe_ratio(
            values["tic_treasury_official"], treasury.abs()
        ),
        "equity_official_share": _safe_ratio(
            values["tic_equity_official"], equity.abs()
        ),
        "foreign_allocation_tilt": _safe_ratio(equity - treasury, absolute_total),
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="foreign_allocation_tilt",
        label="tic_f229",
    )


def _f230(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    window = _positive(parameters, "window", 13)
    lag = _positive(parameters, "change_lag", 1)
    decisions = panels["decisions"]
    monetary = panels["monetary"]
    auctions = panels["auctions"]
    tic = panels["tic"]
    decision_values = _numeric(
        decisions, ("meeting_count", "statement_count"), label="decisions"
    )
    monetary_values = _numeric(
        monetary, ("monetary_base", "total_reserves", "m2"), label="monetary"
    )
    auction_values = _auction_values(auctions)
    tic_values = _numeric(
        tic, ("tic_treasury_net_purchases",), label="tic"
    )

    policy_state = decisions.loc[:, list(_TIMESTAMPS)].copy()
    policy_state["activity"] = (
        decision_values["meeting_count"] + decision_values["statement_count"]
    )
    reserve_state = monetary.loc[:, list(_TIMESTAMPS)].copy()
    reserve_state["z"] = _rolling_zscore(
        _growth(monetary_values["total_reserves"], lag), window
    )
    issuance_state = auctions.loc[:, list(_TIMESTAMPS)].copy()
    issuance_state["z"] = _rolling_zscore(
        _growth(auction_values["offering_amount"], lag), window
    )
    tic_state = tic.loc[:, list(_TIMESTAMPS)].copy()
    tic_state["z"] = _rolling_zscore(
        tic_values["tic_treasury_net_purchases"], window
    )

    policy_aligned = _align_panel(market, policy_state, label="policy")
    reserve_aligned = _align_panel(market, reserve_state, label="reserve")
    issuance_aligned = _align_panel(market, issuance_state, label="issuance")
    tic_aligned = _align_panel(market, tic_state, label="tic")
    activity = policy_aligned["policy_activity"]
    reserve_z = reserve_aligned["reserve_z"]
    issuance_z = issuance_aligned["issuance_z"]
    tic_z = tic_aligned["tic_z"]
    choices = {
        "policy_reserve_interaction": activity * reserve_z,
        "reserve_issuance_balance": reserve_z - issuance_z,
        "foreign_absorption": tic_z - issuance_z,
        "liquidity_foreign_alignment": reserve_z * tic_z,
        "policy_issuance_interaction": activity * issuance_z,
        "four_way_composite": activity * (reserve_z - issuance_z + tic_z),
    }
    return _daily_choice(
        market,
        [
            ("policy", policy_aligned),
            ("reserve", reserve_aligned),
            ("issuance", issuance_aligned),
            ("tic", tic_aligned),
        ],
        choices,
        parameters,
        default="four_way_composite",
    )


_LANE_KERNELS: Mapping[
    str,
    Callable[[pd.DataFrame, Mapping[str, pd.DataFrame], Mapping[str, Any]], pd.DataFrame],
] = {
    "F221": _f221,
    "F222": _f222,
    "F223": _f223,
    "F224": _f224,
    "F225": _f225,
    "F226": _f226,
    "F227": _f227,
    "F228": _f228,
    "F229": _f229,
    "F230": _f230,
}


def evaluate_policy_treasury_lane(
    lane_id: str,
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F221-F230 lane using only released train rows."""

    if lane_id not in _LANE_KERNELS:
        raise PolicyTreasuryFeatureEngineError(f"UNKNOWN_LANE:{lane_id}")
    validated_market = _validated(market, label="market")
    required = _LANE_SOURCES[lane_id]
    missing = sorted(set(required) - set(panels))
    if missing:
        raise PolicyTreasuryFeatureEngineError(
            f"SOURCE_PANEL_MISSING:{lane_id}:{','.join(missing)}"
        )
    validated_panels = {
        name: _validated(panels[name], label=name) for name in required
    }
    return _LANE_KERNELS[lane_id](validated_market, validated_panels, parameters)


def evaluate_policy_treasury_family_batch(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate one representative preregistered configuration per lane."""

    defaults: Mapping[str, str] = {
        "F221": "decision_rate_change",
        "F222": "days_since_statement",
        "F223": "days_since_minutes",
        "F224": "cadence_disagreement",
        "F225": "offer_growth",
        "F226": "bid_to_cover",
        "F227": "refinancing_pressure",
        "F228": "debt_growth",
        "F229": "foreign_allocation_tilt",
        "F230": "four_way_composite",
    }
    return {
        lane: evaluate_policy_treasury_lane(
            lane,
            market,
            panels,
            {
                "statistic": statistic,
                "window": 13,
                "change_lag": 1,
                "normalization": "raw",
                "direction": "continuation",
            },
        )
        for lane, statistic in defaults.items()
    }


__all__ = [
    "PolicyTreasuryFeatureEngineError",
    "evaluate_policy_treasury_family_batch",
    "evaluate_policy_treasury_lane",
]
