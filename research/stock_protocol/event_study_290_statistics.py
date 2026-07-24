"""Pure event-study statistics for the frozen 290-combination stock protocol.

The functions in this module operate on independent opportunities.  They do
not construct a capital curve and deliberately never report portfolio CAGR or
Sharpe.  Censored opportunities remain in survival and censoring analyses but
are excluded from return estimates that require an observed exit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
import hashlib
import json
import math
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd


COSTS_BPS_PER_SIDE: tuple[int, ...] = (0, 5, 10, 25, 50, 100, 200)
RETURN_PERCENTILES: tuple[int, ...] = (5, 10, 25, 50, 75, 90, 95)
SURVIVAL_REPORTING_HORIZONS: tuple[int, ...] = (20, 40, 63, 126, 252)

# One means maximize and minus one minimize. Risk losses are represented as
# positive magnitudes so their objectives are minimized.
REQUIRED_OBJECTIVES: dict[str, int] = {
    "median_return": 1,
    "event_speed": 1,
    "win_rate": 1,
    "profit_factor": 1,
    "worst_period_median_return": 1,
    "bootstrap_median_return_ci_low95": 1,
    "expected_shortfall_10_abs": -1,
    "mae_median_abs": -1,
    "mae_p95_abs": -1,
    "maximum_loss_abs": -1,
    "duration_median": -1,
    "duration_p90": -1,
    "censoring_rate": -1,
    "period_return_dispersion": -1,
    "concentration_hhi": -1,
}

# Balanced Opportunity Score is deliberately limited to the three pillars
# specified by the protocol. Stability and concentration are risk inputs, not
# extra pillars with independent weight.
PILLARS: dict[str, tuple[str, ...]] = {
    "return": (
        "median_return",
        "mean_log_return",
        "profit_factor",
        "bootstrap_median_return_ci_low95",
    ),
    "risk": (
        "expected_shortfall_10_abs",
        "mae_median_abs",
        "worst_decile_loss_abs",
        "period_return_dispersion",
        "concentration_hhi",
    ),
    "time": (
        "event_speed",
        "median_return_per_session",
        "duration_median",
        "time_to_target_median_penalized",
    ),
}
PILLAR_DIRECTIONS: dict[str, int] = {
    "median_return": 1,
    "mean_log_return": 1,
    "profit_factor": 1,
    "bootstrap_median_return_ci_low95": 1,
    "expected_shortfall_10_abs": -1,
    "mae_median_abs": -1,
    "worst_decile_loss_abs": -1,
    "period_return_dispersion": -1,
    "concentration_hhi": -1,
    "event_speed": 1,
    "median_return_per_session": 1,
    "duration_median": -1,
    "time_to_target_median_penalized": -1,
}

MINIMUM_TOTAL_COMPLETE_EVENTS = 200
MINIMUM_COMPLETE_EVENTS_PER_PERIOD = 30
ROBUST_CLEAR_MAJORITY_POSITIVE_YEARS = 0.60
ROBUST_MAX_CENSORING_RATE = 0.20
# Compatibility aliases retained for callers that used opportunity terminology.
MINIMUM_TOTAL_OPPORTUNITIES = MINIMUM_TOTAL_COMPLETE_EVENTS
MINIMUM_OPPORTUNITIES_PER_PERIOD = MINIMUM_COMPLETE_EVENTS_PER_PERIOD
CONTRACT_CLASSIFICATIONS: tuple[str, ...] = (
    "robust_leader",
    "pareto_promising",
    "high_return_high_risk",
    "low_risk_low_return",
    "fast_but_unstable",
    "period_dependent",
    "not_supported",
    "not_applicable",
    "functionally_duplicate",
    "invalid_due_to_data",
    "insufficient_sample",
)

_GROSS_RETURN_ALIASES = ("gross_return", "event_gross_return")
_NET_RETURN_ALIASES = ("net_return", "net_event_return")
_DURATION_ALIASES = (
    "event_duration",
    "holding_sessions",
    "duration_sessions",
    "time_to_event",
)
_MAE_ALIASES = ("maximum_adverse_excursion", "mae", "event_mae")
_RISK_ALIASES = ("event_risk", "trade_path_max_drawdown", *_MAE_ALIASES)
_ROLE_COLUMNS = ("selection_role", "period_role", "tier", "period")
_ALLOWED_SELECTION_ROLES = {
    "a",
    "development",
    "train",
    "training",
    "is",
    "is_train",
    "in_sample",
    "oos_dev",
}
_FORBIDDEN_SELECTION_WORDS = (
    "is_valid",
    "validation",
    "oos_locked",
    "locked",
    "holdout",
    "forward",
)
_MANDATORY_CUTS = ("period", "year", "decade", "country", "market", "currency")
_EVENT_TYPE_ALIASES = ("event_type", "outcome", "exit_reason")


def _first_column(frame: pd.DataFrame, names: Sequence[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _require_columns(frame: pd.DataFrame, required: Sequence[str], label: str) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _finite_numeric(series: pd.Series, name: str, *, allow_na: bool = False) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    invalid = ~np.isfinite(values.to_numpy(dtype=float))
    if allow_na:
        invalid &= values.notna().to_numpy()
    if invalid.any() or (not allow_na and values.isna().any()):
        raise ValueError(f"column {name} contains non-finite values")
    return values


def _bool_series(frame: pd.DataFrame, names: Sequence[str]) -> pd.Series | None:
    column = _first_column(frame, names)
    if column is None:
        return None
    values = frame[column]
    if values.dtype == bool:
        return values.astype(bool)
    normalized = values.astype(str).str.strip().str.lower()
    mapping = {
        "true": True,
        "1": True,
        "yes": True,
        "observed": True,
        "false": False,
        "0": False,
        "no": False,
        "censored": False,
    }
    if not normalized.isin(mapping).all():
        raise ValueError(f"column {column} is not boolean")
    return normalized.map(mapping).astype(bool)


def _consistent_bool_series(
    frame: pd.DataFrame,
    names: Sequence[str],
    label: str,
) -> pd.Series | None:
    present = [name for name in names if name in frame]
    if not present:
        return None
    values = [_bool_series(frame, (name,)) for name in present]
    first = values[0]
    assert first is not None
    if any(value is None or not value.equals(first) for value in values[1:]):
        raise ValueError(f"{label} aliases disagree")
    return first


def _normalized_event_alias(frame: pd.DataFrame, column: str) -> pd.Series:
    raw = frame[column].astype("string").str.strip().str.lower()
    declared = raw.notna() & raw.ne("")
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    result.loc[declared] = "other"
    result.loc[declared & raw.str.contains("target|take_profit", regex=True, na=False)] = "target"
    result.loc[declared & raw.str.contains("stop", regex=True, na=False)] = "stop"
    censored_alias = raw.isin(
        {
            "censored",
            "right_censored",
            "entry_censored",
            "open",
            "open_position",
            "unresolved",
        }
    )
    result.loc[declared & censored_alias] = "censored"
    if column == "event_type":
        known = raw.isin({"target", "stop", "other", "time", "time_exit", "censored"})
        unknown_mask = declared & ~known
        if unknown_mask.any():
            unknown = sorted(raw.loc[unknown_mask].dropna().unique())
            raise ValueError(f"event_type contains unknown values: {unknown}")
    return result


def _event_type_values(frame: pd.DataFrame) -> pd.Series | None:
    present = [column for column in _EVENT_TYPE_ALIASES if column in frame]
    if not present:
        return None
    aliases = {column: _normalized_event_alias(frame, column) for column in present}
    for left_index, left_column in enumerate(present):
        for right_column in present[left_index + 1 :]:
            left = aliases[left_column]
            right = aliases[right_column]
            comparable = left.notna() & right.notna()
            if (left.loc[comparable] != right.loc[comparable]).any():
                raise ValueError(
                    f"event outcome aliases disagree: {left_column} and {right_column}"
                )
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    for column in present:
        result = result.fillna(aliases[column])
    return result if result.notna().any() else None


def _normalize_event_state(frame: pd.DataFrame, returns: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    observed = _consistent_bool_series(
        frame, ("event_observed", "complete", "completed"), "event_observed"
    )
    censored = _consistent_bool_series(
        frame, ("censored", "is_censored"), "censored"
    )
    event_type = _event_type_values(frame)
    if "status" in frame:
        status = frame["status"].astype(str).str.strip().str.lower()
        allowed = {"completed", "right_censored", "entry_censored"}
        if not status.isin(allowed).all():
            unknown = sorted(status.loc[~status.isin(allowed)].unique())
            raise ValueError(f"ledger contains non-event statuses: {unknown}")
        status_observed = status.eq("completed")
        status_censored = ~status_observed
        if observed is not None and not observed.equals(status_observed):
            raise ValueError("event_observed and status disagree")
        if censored is not None and not censored.equals(status_censored):
            raise ValueError("censored and status disagree")
        observed, censored = status_observed, status_censored
    if observed is not None and censored is not None and not observed.equals(~censored):
        raise ValueError("event_observed and censored must be exact complements")
    type_censored = event_type.eq("censored").fillna(False) if event_type is not None else None
    if censored is None:
        if observed is not None:
            censored = ~observed
        elif type_censored is not None:
            assert event_type is not None
            censored = type_censored.where(event_type.notna(), returns.isna()).astype(bool)
        else:
            censored = returns.isna()
    if observed is None:
        observed = ~censored
    if event_type is not None:
        declared_type = event_type.notna()
        if ((type_censored != censored) & declared_type).any():
            raise ValueError("event_type and censoring indicators disagree")

    target = _consistent_bool_series(
        frame, ("target_hit", "reached_target", "reached_50pct"), "target_hit"
    )
    stop = _consistent_bool_series(frame, ("stop_hit", "reached_stop"), "stop_hit")
    if target is not None and stop is not None and (target & stop).any():
        raise ValueError("an opportunity cannot hit target and stop simultaneously")
    if target is not None and (target & censored).any():
        raise ValueError("target_hit contradicts censoring")
    if stop is not None and (stop & censored).any():
        raise ValueError("stop_hit contradicts censoring")
    if event_type is None:
        event_type = pd.Series("other", index=frame.index, dtype=object)
        if target is not None:
            event_type.loc[target] = "target"
        if stop is not None:
            event_type.loc[stop] = "stop"
        event_type.loc[censored] = "censored"
    else:
        event_type = event_type.fillna("other").astype(object)
        event_type.loc[censored] = "censored"
        if target is not None and not target.equals(event_type.eq("target")):
            raise ValueError("target_hit and event_type disagree")
        if stop is not None and not stop.equals(event_type.eq("stop")):
            raise ValueError("stop_hit and event_type disagree")
    return observed.astype(bool), censored.astype(bool), event_type


def _selection_eligibility(frame: pd.DataFrame) -> pd.Series:
    role_columns = [column for column in _ROLE_COLUMNS if column in frame]
    eligible = pd.Series(bool(role_columns), index=frame.index, dtype=bool)
    for column in ("validation_used_for_selection", "locked_used_for_selection"):
        if column in frame:
            values = _bool_series(frame, (column,))
            assert values is not None
            eligible &= ~values
    for role_column in role_columns:
        role = frame[role_column].fillna("").astype(str).str.strip().str.lower()
        forbidden = role.apply(
            lambda value: any(word in value for word in _FORBIDDEN_SELECTION_WORDS)
        )
        known = role.isin(_ALLOWED_SELECTION_ROLES) | forbidden
        eligible &= role.isin(_ALLOWED_SELECTION_ROLES) & ~forbidden & known
    return eligible


def prepare_opportunity_ledger(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
) -> pd.DataFrame:
    """Normalize complete and right-censored opportunities without mutation."""

    if ledger.empty:
        raise ValueError("opportunity ledger is empty")
    _require_columns(
        ledger,
        (combination_column, "opportunity_id", "symbol", "entry_date"),
        "ledger",
    )
    for identifier in (combination_column, "opportunity_id"):
        values = ledger[identifier]
        blank = values.astype("string").str.strip().eq("").fillna(False)
        if values.isna().any() or blank.any():
            raise ValueError(f"column {identifier} contains null or empty identifiers")
    if ledger.duplicated([combination_column, "opportunity_id"]).any():
        raise ValueError("opportunity_id must be unique within each combination")
    gross_return_column = _first_column(ledger, _GROSS_RETURN_ALIASES)
    net_return_column = _first_column(ledger, _NET_RETURN_ALIASES)
    if "event_return_basis" in ledger:
        declared_basis = set(ledger["event_return_basis"].astype(str).str.lower().unique())
        if declared_basis not in ({"gross"}, {"net"}):
            raise ValueError("event_return_basis must be uniformly gross or net")
        if declared_basis == {"net"}:
            gross_return_column = None
            net_return_column = _first_column(
                ledger, ("input_net_event_return", "net_return", "net_event_return", "event_return")
            )
        else:
            gross_return_column = _first_column(
                ledger, ("gross_event_return", "gross_return", "event_gross_return", "event_return")
            )
    duration_column = _first_column(ledger, _DURATION_ALIASES)
    if gross_return_column is None and net_return_column is None:
        raise ValueError("ledger requires an explicitly gross or net return column")
    if duration_column is None:
        raise ValueError(f"ledger requires one duration column from {list(_DURATION_ALIASES)}")

    result = ledger.copy().reset_index(drop=True)
    result["entry_date"] = pd.to_datetime(result["entry_date"], errors="raise").dt.normalize()
    analysis_date = result["entry_date"].copy()
    for fallback_column in ("signal_date", "selection_date"):
        if fallback_column in result:
            fallback = pd.to_datetime(result[fallback_column], errors="raise").dt.normalize()
            analysis_date = analysis_date.fillna(fallback)
    if analysis_date.isna().any():
        raise ValueError("every opportunity requires an entry, signal or selection date")
    result["analysis_date"] = analysis_date
    result["event_duration"] = _finite_numeric(result[duration_column], duration_column)
    if result["event_duration"].lt(0).any():
        raise ValueError("event duration cannot be negative")

    return_column = gross_return_column or net_return_column
    assert return_column is not None
    returns = pd.to_numeric(result[return_column], errors="coerce").astype(float)
    observed, censored, event_type = _normalize_event_state(result, returns)
    result["censored"] = censored
    result["event_observed"] = observed
    observed_returns = returns.loc[result["event_observed"]]
    if observed_returns.isna().any() or not np.isfinite(observed_returns).all():
        raise ValueError("complete opportunities require finite returns")
    if observed_returns.le(-1.0).any():
        raise ValueError("complete opportunity returns must be greater than -100%")
    if returns.loc[result["censored"]].notna().any():
        raise ValueError("censored opportunities cannot declare a realized return")
    returns.loc[result["censored"]] = np.nan
    result["event_return"] = returns
    result["event_return_basis"] = "gross" if gross_return_column is not None else "net"
    if gross_return_column is not None:
        result["gross_event_return"] = returns
    else:
        result["gross_event_return"] = np.nan
    if net_return_column is not None:
        result["input_net_event_return"] = pd.to_numeric(
            result[net_return_column], errors="coerce"
        ).astype(float)

    mae_column = _first_column(result, _MAE_ALIASES)
    risk_column = _first_column(result, _RISK_ALIASES)
    mae = (
        pd.to_numeric(result[mae_column], errors="coerce").astype(float)
        if mae_column is not None
        else pd.Series(np.nan, index=result.index, dtype=float)
    )
    risk = (
        pd.to_numeric(result[risk_column], errors="coerce").abs().astype(float)
        if risk_column is not None
        else mae.abs()
    )
    result["event_mae"] = mae
    result["event_risk"] = risk
    result["event_type"] = event_type
    result["selection_eligible"] = _selection_eligibility(result)
    return result


def add_event_efficiency_metrics(
    ledger: pd.DataFrame,
    *,
    cost_bps_per_side: int | float = 0,
    combination_column: str = "combination_id",
) -> pd.DataFrame:
    """Add two-sided costs and the four required event efficiency measures."""

    if float(cost_bps_per_side) < 0:
        raise ValueError("cost_bps_per_side cannot be negative")
    result = prepare_opportunity_ledger(ledger, combination_column=combination_column)
    round_trip_cost = 2.0 * float(cost_bps_per_side) / 10_000.0
    result["cost_bps_per_side"] = float(cost_bps_per_side)
    gross_available = result["event_return_basis"].eq("gross")
    if float(cost_bps_per_side) > 0 and not gross_available.all():
        raise ValueError("transaction costs require gross returns; net-only returns cannot be charged again")
    result["net_event_return"] = np.where(
        gross_available,
        result["gross_event_return"] - round_trip_cost,
        result["event_return"],
    )
    result.loc[result["censored"], "net_event_return"] = np.nan

    duration = result["event_duration"].replace(0.0, np.nan)
    risk = result["event_risk"].replace(0.0, np.nan)
    mae = result["event_mae"].abs().replace(0.0, np.nan)
    result["event_return_to_risk"] = result["net_event_return"].div(risk)
    result["event_return_to_mae"] = result["net_event_return"].div(mae)
    result["event_speed"] = np.log1p(result["net_event_return"]).div(duration)
    result["event_risk_adjusted_speed"] = result["event_return_to_risk"].div(duration)
    return result


# Compatibility aliases use names likely to appear in campaign/reporting code.
compute_event_metrics = add_event_efficiency_metrics


def _profit_factor(values: pd.Series) -> float:
    gains = float(values.loc[values > 0].sum())
    losses = float(-values.loc[values < 0].sum())
    if losses > 0:
        return gains / losses
    return gains / 1e-12 if gains > 0 else 0.0


def _safe_mean(values: pd.Series) -> float:
    finite = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(finite.mean()) if len(finite) else np.nan


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator == 0:
        return np.nan
    return float(numerator / denominator)


def _expected_shortfall(values: np.ndarray, probability: float) -> float:
    if not len(values):
        return np.nan
    tail_count = max(1, int(math.ceil(len(values) * probability)))
    return float(np.mean(np.partition(values, tail_count - 1)[:tail_count]))


def _period_statistics(group: pd.DataFrame) -> tuple[int, int, int, float, float]:
    if "period" in group and group["period"].notna().any():
        period = group["period"].astype("string").fillna("<missing>")
    else:
        period = group["analysis_date"].dt.year.astype("string")
    counts = group.groupby(period, dropna=False).size()
    observed = group.loc[group["event_observed"]].assign(_period=period)
    complete_counts = observed.groupby("_period").size().reindex(counts.index, fill_value=0)
    period_medians = observed.groupby("_period")["net_event_return"].median().dropna()
    dispersion = float(period_medians.std(ddof=0)) if len(period_medians) else np.nan
    worst = float(period_medians.min()) if len(period_medians) else np.nan
    return (
        int(len(counts)),
        int(counts.min()),
        int(complete_counts.min()),
        dispersion,
        worst,
    )


def _return_concentration(group: pd.DataFrame) -> tuple[float, float, float]:
    contributions = (
        group.loc[group["event_observed"]]
        .groupby("symbol")["net_event_return"]
        .sum()
        .abs()
        .sort_values(ascending=False)
    )
    total = float(contributions.sum())
    shares = contributions / total if total > 0 else contributions * 0.0
    return (
        float(shares.pow(2).sum()),
        float(shares.head(5).sum()),
        float(shares.head(20).sum()),
    )


def _survival_statistics(group: pd.DataFrame, horizon: float) -> dict[str, float]:
    at_risk = int(len(group))
    survival = 1.0
    target_cif = 0.0
    stop_cif = 0.0
    median_duration = np.nan
    for time in sorted(group["event_duration"].unique()):
        if float(time) > horizon:
            break
        current = group.loc[group["event_duration"].eq(time)]
        target = int(current["event_type"].eq("target").sum())
        stop = int(current["event_type"].eq("stop").sum())
        other = int(current["event_type"].eq("other").sum())
        events = target + stop + other
        survival_before = survival
        if at_risk:
            target_cif += survival_before * target / at_risk
            stop_cif += survival_before * stop / at_risk
            survival *= 1.0 - events / at_risk
        if np.isnan(median_duration) and survival <= 0.5:
            median_duration = float(time)
        at_risk -= len(current)
    return {
        "common_horizon": float(horizon),
        "km_survival_at_horizon": float(survival),
        "km_median_duration": float(median_duration),
        "target_cumulative_incidence": float(target_cif),
        "stop_cumulative_incidence": float(stop_cif),
    }


def _event_summary(group: pd.DataFrame, *, common_horizon: float) -> dict[str, Any]:
    observed = group.loc[group["event_observed"]]
    values = observed["net_event_return"].dropna().astype(float)
    duration = observed["event_duration"].astype(float)
    survival = _survival_statistics(group, common_horizon)
    return_array = values.to_numpy(dtype=float)
    log_returns = (
        np.log1p(return_array)
        if len(return_array) and np.all(return_array > -1.0)
        else np.asarray([], dtype=float)
    )
    median_return = float(values.median()) if len(values) else np.nan
    downside = return_array[return_array < 0.0]
    upside = return_array[return_array > 0.0]
    semivariance = float(np.mean(np.square(downside))) if len(downside) else 0.0
    expected_shortfall_05 = _expected_shortfall(return_array, 0.05)
    expected_shortfall_10 = _expected_shortfall(return_array, 0.10)
    mae_abs = observed["event_mae"].abs().dropna().astype(float)
    median_mae_abs = float(mae_abs.median()) if len(mae_abs) else np.nan
    event_speed = float(observed["event_speed"].median())
    valid_session_duration = duration.replace(0.0, np.nan)
    return_per_session = values.div(valid_session_duration.reindex(values.index))
    log_return_per_session = pd.Series(
        log_returns,
        index=values.index if len(log_returns) else pd.Index([]),
        dtype=float,
    ).div(valid_session_duration.reindex(values.index)) if len(log_returns) else pd.Series(dtype=float)
    finite_log_speed = (
        log_return_per_session.replace([np.inf, -np.inf], np.nan).dropna()
    )
    log_speed_es10 = (
        _expected_shortfall(finite_log_speed.to_numpy(dtype=float), 0.10)
        if len(finite_log_speed)
        else np.nan
    )
    calendar_days = pd.to_numeric(
        observed.get("calendar_days_invested", duration),
        errors="coerce",
    ).astype(float)
    valid_calendar_days = calendar_days.replace(0.0, np.nan)
    capital_day_return = values.div(valid_calendar_days.reindex(values.index))
    mae_per_session = mae_abs.div(valid_session_duration.reindex(mae_abs.index))
    intratrade_drawdown = pd.to_numeric(
        observed.get(
            "intratrade_max_drawdown",
            pd.Series(np.nan, index=observed.index),
        ),
        errors="coerce",
    ).dropna()
    target_mask = observed["event_type"].eq("target")
    target_duration = duration.loc[target_mask]
    time_to_target_mean = (
        float(target_duration.mean()) if len(target_duration) else np.nan
    )
    time_to_target_median = (
        float(target_duration.median()) if len(target_duration) else np.nan
    )
    time_to_target_penalized = (
        time_to_target_median
        if np.isfinite(time_to_target_median)
        else float(common_horizon) + 1.0
    )
    analysis_year = group["analysis_date"].dt.year
    year_span = max(1, int(analysis_year.max() - analysis_year.min() + 1))
    observed_with_calendar = observed.assign(
        _entry_year=observed["analysis_date"].dt.year,
        _entry_month=observed["analysis_date"].dt.to_period("M"),
    )
    yearly_means = observed_with_calendar.groupby("_entry_year")[
        "net_event_return"
    ].mean()
    monthly_means = observed_with_calendar.groupby("_entry_month")[
        "net_event_return"
    ].mean()
    (
        periods,
        minimum_period,
        minimum_period_complete,
        period_dispersion,
        worst_period,
    ) = _period_statistics(group)
    concentration_hhi, concentration_top5, concentration_top20 = _return_concentration(group)
    result: dict[str, Any] = {
        "opportunities": int(len(group)),
        "opportunities_per_year": float(len(group) / year_span),
        "complete_events": int(group["event_observed"].sum()),
        "censored_events": int(group["censored"].sum()),
        "censoring_rate": float(group["censored"].mean()),
        "mean_return": float(values.mean()) if len(values) else np.nan,
        "median_return": median_return,
        "net_mean_return": float(values.mean()) if len(values) else np.nan,
        "net_median_return": median_return,
        "geometric_mean_return": (
            float(np.expm1(log_returns.mean())) if len(log_returns) else np.nan
        ),
        "mean_log_return": float(log_returns.mean()) if len(log_returns) else np.nan,
        "win_rate": float(values.gt(0).mean()) if len(values) else np.nan,
        "profit_factor": _profit_factor(values) if len(values) else np.nan,
        "payoff_ratio": _safe_ratio(
            float(np.mean(upside)) if len(upside) else np.nan,
            abs(float(np.mean(downside))) if len(downside) else np.nan,
        ),
        "target_hit_rate": float(target_mask.mean()) if len(observed) else np.nan,
        "best_return": float(values.max()) if len(values) else np.nan,
        "worst_return": float(values.min()) if len(values) else np.nan,
        "maximum_loss_abs": (
            abs(min(float(values.min()), 0.0)) if len(values) else np.nan
        ),
        "return_std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "downside_deviation": float(math.sqrt(semivariance)),
        "semivariance": semivariance,
        "expected_shortfall_5": expected_shortfall_05,
        "expected_shortfall_05": expected_shortfall_05,
        "expected_shortfall_10": expected_shortfall_10,
        "es_5": expected_shortfall_05,
        "es_10": expected_shortfall_10,
        "es5": expected_shortfall_05,
        "es05": expected_shortfall_05,
        "es10": expected_shortfall_10,
        "expected_shortfall_5_abs": abs(min(expected_shortfall_05, 0.0)),
        "expected_shortfall_10_abs": abs(min(expected_shortfall_10, 0.0)),
        "mean_loss": float(np.mean(downside)) if len(downside) else 0.0,
        "median_loss": float(np.median(downside)) if len(downside) else 0.0,
        "worst_decile": expected_shortfall_10,
        "worst_decile_loss_abs": abs(min(expected_shortfall_10, 0.0)),
        "mae_mean_abs": float(mae_abs.mean()) if len(mae_abs) else np.nan,
        "mae_median_abs": median_mae_abs,
        "mae_p90_abs": float(mae_abs.quantile(0.90)) if len(mae_abs) else np.nan,
        "mae_p95_abs": float(mae_abs.quantile(0.95)) if len(mae_abs) else np.nan,
        "intratrade_drawdown_mean": (
            float(intratrade_drawdown.mean()) if len(intratrade_drawdown) else np.nan
        ),
        "intratrade_drawdown_median": (
            float(intratrade_drawdown.median())
            if len(intratrade_drawdown)
            else np.nan
        ),
        **{
            f"probability_loss_gt_{threshold}pct": (
                float(values.lt(-threshold / 100.0).mean())
                if len(values)
                else np.nan
            )
            for threshold in (10, 20, 30, 40, 50)
        },
        **survival,
        # Backward-compatible names now carry Aalen-Johansen estimates.
        "target_incidence": survival["target_cumulative_incidence"],
        "stop_incidence": survival["stop_cumulative_incidence"],
        "duration_mean": float(duration.mean()),
        "duration_median": float(duration.median()),
        "duration_p90": float(duration.quantile(0.90)),
        "calendar_days_mean": float(calendar_days.mean()),
        "calendar_days_median": float(calendar_days.median()),
        "time_to_target_mean": time_to_target_mean,
        "time_to_target_median": time_to_target_median,
        "time_to_target_median_penalized": time_to_target_penalized,
        "mean_return_per_session": _safe_mean(return_per_session),
        "median_return_per_session": (
            float(return_per_session.median())
            if len(return_per_session.dropna())
            else np.nan
        ),
        "mean_log_return_per_session": _safe_mean(log_return_per_session),
        "return_per_capital_day": _safe_mean(capital_day_return),
        "mae_per_session": _safe_mean(mae_per_session),
        "event_return_to_risk": _safe_ratio(median_return, abs(expected_shortfall_10)),
        "event_return_to_mae": _safe_ratio(median_return, median_mae_abs),
        "event_speed": event_speed,
        "event_risk_adjusted_speed": _safe_ratio(
            event_speed, abs(log_speed_es10)
        ),
        "expected_shortfall_10_log_return_per_session": log_speed_es10,
        "event_return_to_risk_mean": _safe_ratio(
            median_return, abs(expected_shortfall_10)
        ),
        "event_return_to_mae_mean": _safe_ratio(median_return, median_mae_abs),
        "event_speed_mean": event_speed,
        "event_risk_adjusted_speed_mean": _safe_ratio(
            event_speed, abs(log_speed_es10)
        ),
        "mae_median": float(observed["event_mae"].median()),
        "median_mae_abs": median_mae_abs,
        "months_with_opportunities": int(
            group["analysis_date"].dt.to_period("M").nunique()
        ),
        "unique_symbols": int(group["symbol"].nunique()),
        "unique_countries": int(
            group["country"].dropna().astype(str).replace("", np.nan).nunique()
        )
        if "country" in group
        else 0,
        "unique_markets": int(
            group["market"].dropna().astype(str).replace("", np.nan).nunique()
        )
        if "market" in group
        else 0,
        "positive_years_pct": (
            float(yearly_means.gt(0).mean()) if len(yearly_means) else np.nan
        ),
        "positive_entry_months_pct": (
            float(monthly_means.gt(0).mean()) if len(monthly_means) else np.nan
        ),
        "periods_evaluated": periods,
        "minimum_period_opportunities": minimum_period,
        "minimum_period_complete_events": minimum_period_complete,
        "period_return_dispersion": period_dispersion,
        "worst_period_median_return": worst_period,
        "concentration_hhi": concentration_hhi,
        "concentration_top5": concentration_top5,
        "concentration_top20": concentration_top20,
        "selection_eligible": bool(group["selection_eligible"].all()),
    }
    for column in (
        "applicability",
        "semantic_applicability",
        "corrected_track_applicability",
    ):
        if column in group:
            result[column] = (
                "not_applicable"
                if group[column].astype(str).eq("not_applicable").any()
                else "applicable"
            )
    if "functionally_duplicated" in group:
        duplicate = _bool_series(group, ("functionally_duplicated",))
        assert duplicate is not None
        result["functionally_duplicated"] = bool(duplicate.any())
    for percentile in RETURN_PERCENTILES:
        result[f"return_p{percentile:02d}"] = (
            float(np.percentile(values, percentile)) if len(values) else np.nan
        )
    return result


def metrics_by_combination(
    ledger: pd.DataFrame,
    *,
    costs_bps_per_side: Sequence[int | float] = COSTS_BPS_PER_SIDE,
    combination_column: str = "combination_id",
    extra_group_columns: Sequence[str] = (),
    common_horizon: float | None = None,
) -> pd.DataFrame:
    """Compute event metrics for every combination and requested cost level."""

    if not costs_bps_per_side:
        raise ValueError("at least one cost level is required")
    frames: list[pd.DataFrame] = []
    grouping = [combination_column, *extra_group_columns]
    for cost in costs_bps_per_side:
        enriched = add_event_efficiency_metrics(
            ledger,
            cost_bps_per_side=cost,
            combination_column=combination_column,
        )
        _require_columns(enriched, grouping, "ledger groups")
        horizon = common_horizon
        if horizon is None:
            maximum_follow_up = enriched.groupby(combination_column)[
                "event_duration"
            ].max()
            horizon = float(maximum_follow_up.min())
        if not np.isfinite(horizon) or horizon < 0:
            raise ValueError("common_horizon must be finite and non-negative")
        rows: list[dict[str, Any]] = []
        grouper: str | list[str] = grouping[0] if len(grouping) == 1 else grouping
        for keys, group in enriched.groupby(grouper, sort=True, dropna=False):
            key_values = (keys,) if len(grouping) == 1 else tuple(keys)
            row = dict(zip(grouping, key_values, strict=True))
            row["cost_bps_per_side"] = float(cost)
            row.update(_event_summary(group, common_horizon=float(horizon)))
            rows.append(row)
        frames.append(pd.DataFrame(rows))
    result = pd.concat(frames, ignore_index=True)
    forbidden = {"cagr", "sharpe", "portfolio_sharpe"} & set(result.columns)
    if forbidden:
        raise AssertionError(f"portfolio metrics leaked into event study: {sorted(forbidden)}")
    return result


compute_combination_metrics = metrics_by_combination
cost_sensitivity = metrics_by_combination


def metric_cuts(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    cost_bps_per_side: int | float = 0,
    cuts: Sequence[str] = _MANDATORY_CUTS,
    common_horizon: float | None = None,
) -> pd.DataFrame:
    """Return independent period/year/decade/geography/currency summaries."""

    if isinstance(cuts, (str, bytes)) or not cuts or len(set(cuts)) != len(cuts):
        raise ValueError("mandatory cuts must be non-empty and unique")
    omitted = set(_MANDATORY_CUTS) - set(cuts)
    if omitted:
        raise ValueError(f"mandatory cuts omitted: {sorted(omitted)}")
    source = ledger.copy()
    _require_columns(source, (combination_column, "entry_date"), "ledger")
    dates = pd.to_datetime(source["entry_date"], errors="raise")
    for fallback_column in ("signal_date", "selection_date"):
        if fallback_column in source:
            dates = dates.fillna(pd.to_datetime(source[fallback_column], errors="raise"))
    if dates.isna().any():
        raise ValueError("mandatory time cuts require a causal opportunity date")
    source["year"] = dates.dt.year.astype(int)
    source["decade"] = (source["year"] // 10 * 10).astype(int)
    missing = set(cuts) - set(source.columns)
    if missing:
        raise ValueError(f"ledger missing mandatory cuts: {sorted(missing)}")
    for cut in cuts:
        values = source[cut]
        blank = values.astype("string").str.strip().eq("").fillna(False)
        if values.isna().any() or blank.any():
            raise ValueError(f"mandatory cut {cut} contains null or empty values")
    expected_combinations = set(source[combination_column].unique())
    expected_counts = source.groupby(combination_column, sort=False).size().sort_index()
    rows: list[pd.DataFrame] = []
    for cut in cuts:
        summary = metrics_by_combination(
            source,
            costs_bps_per_side=(cost_bps_per_side,),
            combination_column=combination_column,
            extra_group_columns=(cut,),
            common_horizon=common_horizon,
        )
        summary.insert(1, "cut", cut)
        summary = summary.rename(columns={cut: "cut_value"})
        mean_return = pd.to_numeric(summary["mean_return"], errors="coerce")
        summary["mean_return_sign"] = np.select(
            (mean_return.gt(0), mean_return.lt(0), mean_return.eq(0)),
            ("positive", "negative", "zero"),
            default="not_estimable",
        )
        if set(summary[combination_column].unique()) != expected_combinations:
            raise ValueError(f"mandatory cut {cut} does not cover every combination")
        covered_counts = (
            summary.groupby(combination_column)["opportunities"]
            .sum()
            .reindex(expected_counts.index)
        )
        if covered_counts.isna().any() or not np.array_equal(
            covered_counts.to_numpy(dtype=np.int64),
            expected_counts.to_numpy(dtype=np.int64),
        ):
            raise ValueError(f"mandatory cut {cut} does not cover every opportunity")
        rows.append(summary)
    return pd.concat(rows, ignore_index=True)


period_cuts = metric_cuts


def censoring_audit(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    group_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Audit censoring counts, rates, durations and observed causes."""

    frame = prepare_opportunity_ledger(ledger, combination_column=combination_column)
    grouping = [combination_column, *group_columns]
    _require_columns(frame, grouping, "censoring groups")
    rows: list[dict[str, Any]] = []
    grouper: str | list[str] = grouping[0] if len(grouping) == 1 else grouping
    for keys, group in frame.groupby(grouper, sort=True, dropna=False):
        key_values = (keys,) if len(grouping) == 1 else tuple(keys)
        row = dict(zip(grouping, key_values, strict=True))
        censored_frame = group.loc[group["censored"]]
        censored = censored_frame["event_duration"]
        observed = group.loc[group["event_observed"], "event_duration"]
        mtm = pd.to_numeric(
            censored_frame.get(
                "mtm_return", pd.Series(np.nan, index=censored_frame.index)
            ),
            errors="coerce",
        ).dropna()
        remaining = pd.to_numeric(
            censored_frame.get(
                "remaining_sessions_estimate",
                pd.Series(np.nan, index=censored_frame.index),
            ),
            errors="coerce",
        ).dropna()
        row.update(
            {
                "opportunities": int(len(group)),
                "complete_events": int(len(observed)),
                "censored_events": int(len(censored)),
                "censoring_rate": float(len(censored) / len(group)),
                "censored_duration_median": float(censored.median()) if len(censored) else np.nan,
                "observed_duration_median": float(observed.median()) if len(observed) else np.nan,
                "target_events": int(group["event_type"].eq("target").sum()),
                "stop_events": int(group["event_type"].eq("stop").sum()),
                "other_events": int(group["event_type"].eq("other").sum()),
                "censored_mtm_return_mean": (
                    float(mtm.mean()) if len(mtm) else np.nan
                ),
                "censored_mtm_return_median": (
                    float(mtm.median()) if len(mtm) else np.nan
                ),
                "remaining_sessions_estimate_mean": (
                    float(remaining.mean()) if len(remaining) else np.nan
                ),
                "remaining_sessions_estimate_median": (
                    float(remaining.median()) if len(remaining) else np.nan
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def survival_incidence_table(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    group_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Kaplan-Meier survival and Aalen-Johansen target/stop incidence."""

    frame = prepare_opportunity_ledger(ledger, combination_column=combination_column)
    grouping = [combination_column, *group_columns]
    _require_columns(frame, grouping, "survival groups")
    output: list[dict[str, Any]] = []
    grouper: str | list[str] = grouping[0] if len(grouping) == 1 else grouping
    for keys, group in frame.groupby(grouper, sort=True, dropna=False):
        key_values = (keys,) if len(grouping) == 1 else tuple(keys)
        labels = dict(zip(grouping, key_values, strict=True))
        at_risk = int(len(group))
        survival = 1.0
        target_cif = 0.0
        stop_cif = 0.0
        observed_times = {
            float(value)
            for value in pd.to_numeric(group["event_duration"], errors="raise").unique()
        }
        timeline = sorted(observed_times | set(SURVIVAL_REPORTING_HORIZONS))
        for time in timeline:
            current = group.loc[group["event_duration"].eq(time)]
            target = int(current["event_type"].eq("target").sum())
            stop = int(current["event_type"].eq("stop").sum())
            other = int(current["event_type"].eq("other").sum())
            censored = int(current["censored"].sum())
            events = target + stop + other
            survival_before = survival
            if at_risk:
                target_cif += survival_before * target / at_risk
                stop_cif += survival_before * stop / at_risk
                survival *= 1.0 - events / at_risk
            output.append(
                {
                    **labels,
                    "event_duration": float(time),
                    "requested_horizon": time in SURVIVAL_REPORTING_HORIZONS,
                    "at_risk": at_risk,
                    "events": events,
                    "target_events": target,
                    "stop_events": stop,
                    "other_events": other,
                    "censored_events": censored,
                    "kaplan_meier_survival": float(survival),
                    "target_cumulative_incidence": float(target_cif),
                    "stop_cumulative_incidence": float(stop_cif),
                }
            )
            at_risk -= len(current)
    return pd.DataFrame(output)


kaplan_meier = survival_incidence_table
competing_risk_incidence = survival_incidence_table
censoring_analysis = survival_incidence_table


def _sign_test_pvalue(deltas: np.ndarray) -> tuple[int, int, float]:
    nonzero = deltas[deltas != 0]
    positives = int((nonzero > 0).sum())
    negatives = int((nonzero < 0).sum())
    n = positives + negatives
    if n == 0:
        return positives, negatives, 1.0
    try:
        from scipy.stats import binomtest

        return (
            positives,
            negatives,
            float(binomtest(positives, n, 0.5, alternative="two-sided").pvalue),
        )
    except ImportError:
        if n > 1_000:
            z = (abs(positives - n / 2.0) - 0.5) / math.sqrt(n / 4.0)
            pvalue = math.erfc(max(0.0, z) / math.sqrt(2.0))
            return positives, negatives, min(1.0, pvalue)
    tail = min(positives, negatives)
    probability = 2.0 * sum(math.comb(n, k) for k in range(tail + 1)) / (2.0**n)
    return positives, negatives, min(1.0, probability)


def _wilcoxon_with_fallback(deltas: np.ndarray) -> dict[str, Any]:
    nonzero = deltas[deltas != 0]
    if len(nonzero) == 0:
        return {
            "wilcoxon_method": "explicit_sign_test_fallback_all_ties",
            "wilcoxon_statistic": 0.0,
            "wilcoxon_pvalue": 1.0,
        }
    try:
        from scipy import stats

        value = stats.wilcoxon(nonzero, alternative="two-sided", zero_method="wilcox")
        return {
            "wilcoxon_method": "scipy_wilcoxon_two_sided",
            "wilcoxon_statistic": float(value.statistic),
            "wilcoxon_pvalue": float(value.pvalue),
        }
    except (ImportError, ValueError):
        _, _, pvalue = _sign_test_pvalue(nonzero)
        return {
            "wilcoxon_method": "explicit_sign_test_fallback_no_scipy",
            "wilcoxon_statistic": float((nonzero > 0).sum()),
            "wilcoxon_pvalue": pvalue,
        }


def paired_variant_comparison(
    ledger: pd.DataFrame,
    *,
    variant_column: str,
    baseline: Any,
    challenger: Any,
    causal_keys: Sequence[str] = ("symbol", "signal_date"),
    metric: str = "net_event_return",
    cost_bps_per_side: int | float = 0,
    bootstrap_samples: int = 5000,
    seed: int = 20260721,
    bootstrap_cluster: str = "hierarchical_year_symbol",
    combination_column: str = "combination_id",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare exits or entries on exactly matched pre-treatment causal keys."""

    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    _require_columns(ledger, (variant_column, *causal_keys), "paired ledger")
    enriched = add_event_efficiency_metrics(
        ledger,
        cost_bps_per_side=cost_bps_per_side,
        combination_column=combination_column,
    )
    left = enriched.loc[enriched[variant_column].eq(baseline) & enriched["event_observed"]]
    right = enriched.loc[enriched[variant_column].eq(challenger) & enriched["event_observed"]]
    if left.duplicated(list(causal_keys)).any() or right.duplicated(list(causal_keys)).any():
        raise ValueError("causal keys must uniquely identify each variant opportunity")
    _require_columns(enriched, (metric,), "paired metric")
    if "symbol" not in causal_keys:
        raise ValueError("paired cluster bootstrap requires symbol in causal_keys")
    left = left.copy()
    left["entry_year"] = left["entry_date"].dt.year.astype(int)
    pairs = left[[*causal_keys, "entry_year", metric]].merge(
        right[[*causal_keys, metric]],
        on=list(causal_keys),
        how="inner",
        validate="one_to_one",
        suffixes=("_baseline", "_challenger"),
    )
    if pairs.empty:
        raise ValueError("no complete opportunities match on causal keys")
    pairs["delta"] = (
        pairs[f"{metric}_challenger"] - pairs[f"{metric}_baseline"]
    )
    deltas = pairs["delta"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    if bootstrap_cluster not in {"symbol", "hierarchical_year_symbol"}:
        raise ValueError("paired bootstrap_cluster must be symbol or hierarchical_year_symbol")
    bootstrap = np.asarray(
        [
            float(_cluster_sample(pairs, bootstrap_cluster, rng)["delta"].mean())
            for _ in range(bootstrap_samples)
        ]
    )
    observed_mean = float(np.mean(deltas))
    centered_null = bootstrap - observed_mean
    cluster_pvalue = float(
        (1 + np.sum(np.abs(centered_null) >= abs(observed_mean)))
        / (bootstrap_samples + 1)
    )
    positives, negatives, sign_pvalue = _sign_test_pvalue(deltas)
    wilcoxon = _wilcoxon_with_fallback(deltas)
    summary = {
        "baseline": baseline,
        "challenger": challenger,
        "metric": metric,
        "causal_keys": json.dumps(list(causal_keys)),
        "bootstrap_method": f"paired_{bootstrap_cluster}_cluster",
        "pairs": int(len(deltas)),
        "mean_delta": observed_mean,
        "median_delta": float(np.median(deltas)),
        "bootstrap_low95": float(np.quantile(bootstrap, 0.025)),
        "bootstrap_high95": float(np.quantile(bootstrap, 0.975)),
        "positive_pairs": positives,
        "negative_pairs": negatives,
        "ties": int((deltas == 0).sum()),
        "primary_pvalue": cluster_pvalue,
        "primary_inference_method": f"paired_{bootstrap_cluster}_cluster_centered_bootstrap",
        "sign_test_pvalue": sign_pvalue,
        "sign_test_evidence_role": "diagnostic_non_cluster_robust",
        **wilcoxon,
        "wilcoxon_evidence_role": "diagnostic_non_cluster_robust",
    }
    records = pd.DataFrame(
        {"sample": np.arange(bootstrap_samples), "paired_mean_delta": bootstrap}
    )
    return pd.DataFrame([summary]), records


paired_exit_comparison = paired_variant_comparison
paired_entry_comparison = paired_variant_comparison


def _bootstrap_estimates(sample: pd.DataFrame) -> dict[str, float]:
    returns = sample["net_event_return"].dropna().to_numpy(dtype=float)
    speeds = sample["event_speed"].replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "event_speed": float(speeds.median()),
    }


def _cluster_bootstrap_weights(
    frame: pd.DataFrame,
    method: str,
    bootstrap_samples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return row multiplicities for all cluster bootstrap samples at once."""

    if method in {"symbol", "year"}:
        column = "symbol" if method == "symbol" else "entry_year"
        codes, uniques = pd.factorize(frame[column], sort=True)
        cluster_count = len(uniques)
        draws = rng.integers(
            0, cluster_count, size=(bootstrap_samples, cluster_count)
        )
        counts = np.zeros((bootstrap_samples, cluster_count), dtype=np.int32)
        sample_rows = np.repeat(np.arange(bootstrap_samples), cluster_count)
        np.add.at(counts, (sample_rows, draws.ravel()), 1)
        return counts[:, codes]

    if method != "hierarchical_year_symbol":
        raise ValueError(f"unknown cluster bootstrap method: {method}")

    year_codes, years = pd.factorize(frame["entry_year"], sort=True)
    year_count = len(years)
    year_draws = rng.integers(0, year_count, size=(bootstrap_samples, year_count))
    weights = np.zeros((bootstrap_samples, len(frame)), dtype=np.int32)
    sample_rows = np.arange(bootstrap_samples)
    for year_code in range(year_count):
        row_positions = np.flatnonzero(year_codes == year_code)
        symbol_codes, symbols = pd.factorize(
            frame.iloc[row_positions]["symbol"], sort=True
        )
        symbol_count = len(symbols)
        symbol_counts = np.zeros(
            (bootstrap_samples, symbol_count), dtype=np.int32
        )
        selected_slots = year_draws == year_code
        for slot in range(year_count):
            selected_samples = sample_rows[selected_slots[:, slot]]
            if not len(selected_samples):
                continue
            symbol_draws = rng.integers(
                0,
                symbol_count,
                size=(len(selected_samples), symbol_count),
            )
            repeated_samples = np.repeat(selected_samples, symbol_count)
            np.add.at(
                symbol_counts,
                (repeated_samples, symbol_draws.ravel()),
                1,
            )
        weights[:, row_positions] = symbol_counts[:, symbol_codes]
    return weights


def _weighted_bootstrap_median(
    values: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Match np.median for integer-weighted bootstrap observations."""

    finite = np.isfinite(values)
    values = values[finite]
    weights = weights[:, finite]
    if not len(values):
        return np.full(len(weights), np.nan, dtype=float)
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    cumulative = np.cumsum(weights[:, order], axis=1)
    totals = cumulative[:, -1]
    result = np.full(len(weights), np.nan, dtype=float)
    populated = totals > 0
    lower_positions = (totals - 1) // 2
    upper_positions = totals // 2
    lower_indices = np.argmax(
        cumulative[populated] > lower_positions[populated, None], axis=1
    )
    upper_indices = np.argmax(
        cumulative[populated] > upper_positions[populated, None], axis=1
    )
    result[populated] = (
        ordered_values[lower_indices] + ordered_values[upper_indices]
    ) / 2.0
    return result


def _weighted_bootstrap_estimates(
    frame: pd.DataFrame,
    weights: np.ndarray,
) -> np.ndarray:
    returns = frame["net_event_return"].to_numpy(dtype=float)
    speeds = frame["event_speed"].to_numpy(dtype=float)
    return_weights = weights[:, np.isfinite(returns)]
    estimates = np.empty((len(weights), 3), dtype=float)
    estimates[:, 0] = (
        return_weights @ returns[np.isfinite(returns)]
    ) / return_weights.sum(axis=1)
    estimates[:, 1] = _weighted_bootstrap_median(returns, weights)
    estimates[:, 2] = _weighted_bootstrap_median(speeds, weights)
    return estimates


def _cluster_sample(
    frame: pd.DataFrame,
    method: str,
    rng: np.random.Generator,
) -> pd.DataFrame:
    if method in {"symbol", "year"}:
        column = "symbol" if method == "symbol" else "entry_year"
        groups = [part for _, part in frame.groupby(column, sort=True)]
        chosen = rng.integers(0, len(groups), size=len(groups))
        return pd.concat([groups[index] for index in chosen], ignore_index=True)
    if method != "hierarchical_year_symbol":
        raise ValueError(f"unknown cluster bootstrap method: {method}")
    years = [part for _, part in frame.groupby("entry_year", sort=True)]
    sampled_years = rng.integers(0, len(years), size=len(years))
    pieces: list[pd.DataFrame] = []
    for year_index in sampled_years:
        symbols = [part for _, part in years[year_index].groupby("symbol", sort=True)]
        sampled_symbols = rng.integers(0, len(symbols), size=len(symbols))
        pieces.extend(symbols[index] for index in sampled_symbols)
    return pd.concat(pieces, ignore_index=True)


def _cluster_metadata(
    cluster_frame: pd.DataFrame,
    *,
    expected_rows: int,
) -> pd.DataFrame:
    if len(cluster_frame) != expected_rows:
        raise ValueError("cluster_frame length must match return observations")
    _require_columns(cluster_frame, ("symbol",), "cluster_frame")
    result = cluster_frame.copy().reset_index(drop=True)
    if "entry_year" not in result:
        date_column = _first_column(result, ("entry_date", "signal_date"))
        if date_column is None:
            raise ValueError("cluster_frame requires entry_year or a causal date")
        result["entry_year"] = pd.to_datetime(result[date_column], errors="raise").dt.year
    result["entry_year"] = pd.to_numeric(result["entry_year"], errors="raise").astype(int)
    result["_row_index"] = np.arange(expected_rows)
    return result


def _cluster_resample_indices(
    metadata: pd.DataFrame,
    method: str,
    rng: np.random.Generator,
) -> np.ndarray:
    if method not in {"symbol", "hierarchical_year_symbol"}:
        raise ValueError("cluster_method must be symbol or hierarchical_year_symbol")
    sampled = _cluster_sample(metadata, method, rng)
    return sampled["_row_index"].to_numpy(dtype=int)


def cluster_bootstrap_confidence_intervals(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    cost_bps_per_side: int | float = 0,
    bootstrap_samples: int = 2000,
    seed: int = 20260721,
    methods: Sequence[str] = ("symbol", "year", "hierarchical_year_symbol"),
    include_records: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bootstrap symbol, year and hierarchical year-to-symbol clusters."""

    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    frame = add_event_efficiency_metrics(
        ledger,
        cost_bps_per_side=cost_bps_per_side,
        combination_column=combination_column,
    )
    frame = frame.loc[frame["event_observed"]].copy()
    if frame.empty:
        raise ValueError("cluster bootstrap requires complete opportunities")
    frame["entry_year"] = frame["entry_date"].dt.year.astype(int)
    rng = np.random.default_rng(seed)
    methods = tuple(methods)
    supported_methods = {"symbol", "year", "hierarchical_year_symbol"}
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("cluster bootstrap methods must be non-empty and unique")
    if set(methods) - supported_methods:
        raise ValueError("cluster bootstrap contains an unsupported method")
    grouped = list(frame.groupby(combination_column, sort=True, dropna=False))
    combinations = [combination for combination, _ in grouped]
    estimate_cube = np.empty(
        (len(grouped), len(methods), bootstrap_samples, 3), dtype=float
    )
    summaries: list[dict[str, Any]] = []
    metric_names = ("mean_return", "median_return", "event_speed")
    for combination_index, (combination, group) in enumerate(grouped):
        group = group.reset_index(drop=True)
        for method_index, method in enumerate(methods):
            weights = _cluster_bootstrap_weights(
                group, method, bootstrap_samples, rng
            )
            estimates = _weighted_bootstrap_estimates(group, weights)
            estimate_cube[combination_index, method_index] = estimates
            for metric_index, metric in enumerate(metric_names):
                values = estimates[:, metric_index]
                values = values[np.isfinite(values)]
                if not len(values):
                    estimate = ci_low95 = ci_high95 = np.nan
                else:
                    estimate = float(np.mean(values))
                    ci_low95, ci_high95 = np.quantile(values, (0.025, 0.975))
                summaries.append(
                    {
                        combination_column: combination,
                        "method": method,
                        "metric": metric,
                        "estimate": estimate,
                        "ci_low95": float(ci_low95),
                        "ci_high95": float(ci_high95),
                    }
                )

    if not include_records:
        return pd.DataFrame(summaries), pd.DataFrame()
    row_count = len(grouped) * len(methods) * bootstrap_samples
    combination_codes = np.repeat(
        np.arange(len(grouped)), len(methods) * bootstrap_samples
    )
    method_codes = np.tile(
        np.repeat(np.arange(len(methods)), bootstrap_samples), len(grouped)
    )
    record_frame = pd.DataFrame(
        {
            combination_column: pd.Categorical.from_codes(
                combination_codes, categories=combinations
            ),
            "method": pd.Categorical.from_codes(method_codes, categories=methods),
            "sample": np.tile(
                np.arange(bootstrap_samples, dtype=np.int32),
                len(grouped) * len(methods),
            ),
            "mean_return": estimate_cube[:, :, :, 0].reshape(row_count),
            "median_return": estimate_cube[:, :, :, 1].reshape(row_count),
            "event_speed": estimate_cube[:, :, :, 2].reshape(row_count),
        }
    )
    return pd.DataFrame(summaries), record_frame


cluster_bootstrap_ci = cluster_bootstrap_confidence_intervals


def robust_combination_inference(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
) -> pd.DataFrame:
    """Two-way clustered mean inference plus sign and Wilcoxon diagnostics."""

    frame = add_event_efficiency_metrics(
        ledger,
        cost_bps_per_side=0,
        combination_column=combination_column,
    )
    frame = frame.loc[frame["event_observed"]].copy()
    if frame.empty:
        raise ValueError("robust inference requires complete opportunities")
    frame["entry_month"] = frame["analysis_date"].dt.to_period("M").astype(str)
    rows: list[dict[str, Any]] = []

    def cluster_meat(scores: pd.Series, labels: pd.Series) -> float:
        sums = scores.groupby(labels, sort=False).sum().to_numpy(dtype=float)
        cluster_count = len(sums)
        correction = (
            cluster_count / (cluster_count - 1)
            if cluster_count > 1
            else 1.0
        )
        return float(correction * np.square(sums).sum())

    normal = NormalDist()
    for combination_id, group in frame.groupby(
        combination_column, sort=True, dropna=False
    ):
        values = group["net_event_return"].to_numpy(dtype=float)
        mean_return = float(np.mean(values))
        scores = pd.Series(values - mean_return, index=group.index)
        symbol_meat = cluster_meat(scores, group["symbol"])
        month_meat = cluster_meat(scores, group["entry_month"])
        observation_meat = float(np.square(scores.to_numpy(dtype=float)).sum())
        variance = max(
            0.0,
            (symbol_meat + month_meat - observation_meat) / (len(group) ** 2),
        )
        standard_error = math.sqrt(variance)
        statistic = (
            mean_return / standard_error if standard_error > 0 else 0.0
        )
        pvalue = (
            2.0 * (1.0 - normal.cdf(abs(statistic)))
            if standard_error > 0
            else 1.0
        )
        positives, negatives, sign_pvalue = _sign_test_pvalue(values)
        wilcoxon = _wilcoxon_with_fallback(values)
        rows.append(
            {
                combination_column: combination_id,
                "complete_events": int(len(group)),
                "mean_return": mean_return,
                "two_way_cluster_standard_error": standard_error,
                "two_way_cluster_ci_low95": mean_return - 1.96 * standard_error,
                "two_way_cluster_ci_high95": mean_return + 1.96 * standard_error,
                "two_way_cluster_statistic": statistic,
                "two_way_cluster_pvalue_two_sided": pvalue,
                "two_way_cluster_dimensions": "symbol,entry_month",
                "sign_positive_events": positives,
                "sign_negative_events": negatives,
                "sign_test_pvalue": sign_pvalue,
                **wilcoxon,
                "sign_and_wilcoxon_evidence_role": (
                    "diagnostic_non_cluster_robust"
                ),
            }
        )
    return pd.DataFrame(rows)


def concentration_statistics(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
) -> pd.DataFrame:
    """Measure absolute return contribution concentration by symbol."""

    frame = prepare_opportunity_ledger(ledger, combination_column=combination_column)
    rows: list[dict[str, Any]] = []
    for combination, group in frame.groupby(combination_column, sort=True, dropna=False):
        contributions = (
            group.loc[group["event_observed"]]
            .groupby("symbol")["event_return"]
            .sum()
            .abs()
            .sort_values(ascending=False)
        )
        total = float(contributions.sum())
        shares = contributions / total if total > 0 else contributions * 0.0
        rows.append(
            {
                combination_column: combination,
                "symbols": int(len(contributions)),
                "concentration_hhi": float(shares.pow(2).sum()),
                "concentration_top5": float(shares.head(5).sum()),
                "concentration_top20": float(shares.head(20).sum()),
            }
        )
    return pd.DataFrame(rows)


def leave_one_out_audit(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    dimensions: Sequence[str] = ("year", "symbol", "country", "market"),
) -> pd.DataFrame:
    """Recompute mean return after every requested omission and top contributor cut."""

    frame = prepare_opportunity_ledger(ledger, combination_column=combination_column)
    frame["year"] = frame["analysis_date"].dt.year.astype(int)
    rows: list[dict[str, Any]] = []
    for combination, group in frame.groupby(combination_column, sort=True, dropna=False):
        complete = group.loc[group["event_observed"]].copy()
        baseline = float(complete["event_return"].mean())
        for dimension in dimensions:
            if dimension not in complete:
                continue
            for omitted in sorted(complete[dimension].dropna().unique(), key=str):
                remaining = complete.loc[~complete[dimension].eq(omitted)]
                estimate = float(remaining["event_return"].mean()) if len(remaining) else np.nan
                rows.append(
                    {
                        combination_column: combination,
                        "omission": dimension,
                        "omitted_value": omitted,
                        "remaining_events": int(len(remaining)),
                        "baseline_mean_return": baseline,
                        "leave_out_mean_return": estimate,
                        "change_from_baseline": estimate - baseline,
                    }
                )
        contribution = complete.groupby("symbol")["event_return"].sum().abs().sort_values(
            ascending=False
        )
        for count in (5, 20):
            omitted_symbols = contribution.head(count).index
            remaining = complete.loc[~complete["symbol"].isin(omitted_symbols)]
            estimate = float(remaining["event_return"].mean()) if len(remaining) else np.nan
            rows.append(
                {
                    combination_column: combination,
                    "omission": f"top{count}_symbols",
                    "omitted_value": json.dumps([str(value) for value in omitted_symbols]),
                    "remaining_events": int(len(remaining)),
                    "baseline_mean_return": baseline,
                    "leave_out_mean_return": estimate,
                    "change_from_baseline": estimate - baseline,
                }
            )
        ranked_opportunities = complete.sort_values(
            ["event_return", "opportunity_id"],
            ascending=[False, True],
            kind="stable",
        )
        for count in (5, 20):
            omitted_ids = ranked_opportunities.head(count)["opportunity_id"].astype(str)
            remaining = complete.loc[
                ~complete["opportunity_id"].astype(str).isin(omitted_ids)
            ]
            estimate = (
                float(remaining["event_return"].mean()) if len(remaining) else np.nan
            )
            rows.append(
                {
                    combination_column: combination,
                    "omission": f"top{count}_opportunities",
                    "omitted_value": json.dumps(omitted_ids.tolist()),
                    "remaining_events": int(len(remaining)),
                    "baseline_mean_return": baseline,
                    "leave_out_mean_return": estimate,
                    "change_from_baseline": estimate - baseline,
                }
            )
    return pd.DataFrame(rows)


def benjamini_hochberg(pvalues: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg false-discovery-rate adjusted p-values."""

    values = np.asarray(pvalues, dtype=float)
    if values.ndim != 1 or len(values) == 0 or np.any((values < 0) | (values > 1)):
        raise ValueError("pvalues must be a non-empty one-dimensional array in [0, 1]")
    order = np.argsort(values, kind="stable")
    ranked = values[order]
    adjusted = np.minimum.accumulate((ranked * len(values) / np.arange(1, len(values) + 1))[::-1])[::-1]
    output = np.empty_like(adjusted)
    output[order] = np.minimum(adjusted, 1.0)
    return output


def holm_adjust(pvalues: Sequence[float]) -> np.ndarray:
    """Holm family-wise-error adjusted p-values."""

    values = np.asarray(pvalues, dtype=float)
    if values.ndim != 1 or len(values) == 0 or np.any((values < 0) | (values > 1)):
        raise ValueError("pvalues must be a non-empty one-dimensional array in [0, 1]")
    order = np.argsort(values, kind="stable")
    ranked = values[order]
    adjusted = np.maximum.accumulate(ranked * (len(values) - np.arange(len(values))))
    output = np.empty_like(adjusted)
    output[order] = np.minimum(adjusted, 1.0)
    return output


holm_bonferroni = holm_adjust


def _return_matrix(values: pd.DataFrame | np.ndarray) -> tuple[np.ndarray, list[Any]]:
    if isinstance(values, pd.DataFrame):
        labels = list(values.columns)
        matrix = values.to_numpy(dtype=float)
    else:
        matrix = np.asarray(values, dtype=float)
        labels = list(range(matrix.shape[1] if matrix.ndim == 2 else 0))
    if matrix.ndim != 2 or min(matrix.shape) < 2 or not np.isfinite(matrix).all():
        raise ValueError("return matrix must be finite with at least two rows and columns")
    return matrix, labels


def _batched_cluster_null_moments(
    centered: np.ndarray,
    metadata: pd.DataFrame,
    *,
    cluster_method: str,
    bootstrap_samples: int,
    rng: np.random.Generator,
    batch_size: int = 32,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute cluster-resampled means and errors without materializing row samples."""

    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    sample_count, combination_count = centered.shape
    means = np.empty((bootstrap_samples, combination_count), dtype=float)
    errors = np.empty_like(means)
    totals = np.empty(bootstrap_samples, dtype=float)
    squared = np.square(centered)
    for start in range(0, bootstrap_samples, batch_size):
        stop = min(start + batch_size, bootstrap_samples)
        weights = _cluster_bootstrap_weights(
            metadata,
            cluster_method,
            stop - start,
            rng,
        )
        batch_totals = weights.sum(axis=1, dtype=np.int64).astype(float)
        if np.any(batch_totals <= 1):
            raise ValueError("cluster bootstrap requires at least two sampled rows")
        batch_means = (weights @ centered) / batch_totals[:, None]
        centered_squares = (
            (weights @ squared)
            - batch_totals[:, None] * np.square(batch_means)
        )
        variances = np.maximum(centered_squares, 0.0) / (
            batch_totals[:, None] - 1.0
        )
        means[start:stop] = batch_means
        errors[start:stop] = np.sqrt(variances / batch_totals[:, None])
        totals[start:stop] = batch_totals
    if sample_count < 2:
        raise ValueError("cluster bootstrap requires at least two source rows")
    return means, errors, totals


def westfall_young_max_t(
    returns: pd.DataFrame | np.ndarray,
    *,
    cluster_frame: pd.DataFrame,
    cluster_method: str = "hierarchical_year_symbol",
    bootstrap_samples: int = 5000,
    seed: int = 20260721,
) -> pd.DataFrame:
    """Single-step maxT equivalent using synchronized cluster bootstrap."""

    matrix, labels = _return_matrix(returns)
    n = matrix.shape[0]
    metadata = _cluster_metadata(cluster_frame, expected_rows=n)
    standard_error = matrix.std(axis=0, ddof=1) / math.sqrt(n)
    observed = np.divide(
        matrix.mean(axis=0), standard_error, out=np.zeros_like(standard_error), where=standard_error > 0
    )
    centered = matrix - matrix.mean(axis=0)
    rng = np.random.default_rng(seed)
    null_means, null_errors, _ = _batched_cluster_null_moments(
        centered,
        metadata,
        cluster_method=cluster_method,
        bootstrap_samples=bootstrap_samples,
        rng=rng,
    )
    null_statistics = np.divide(
        null_means,
        null_errors,
        out=np.zeros_like(null_means),
        where=null_errors > 0,
    )
    maxima = np.max(np.abs(null_statistics), axis=1)
    return pd.DataFrame(
        {
            "combination_id": labels,
            "statistic": observed,
            "adjusted_pvalue": [float((1 + np.sum(maxima >= abs(value))) / (bootstrap_samples + 1)) for value in observed],
            "method": f"westfall_young_equivalent_centered_{cluster_method}_cluster_maxT",
        }
    )


max_t_adjustment = westfall_young_max_t


def white_spa_equivalent(
    returns: pd.DataFrame | np.ndarray,
    *,
    cluster_frame: pd.DataFrame,
    cluster_method: str = "hierarchical_year_symbol",
    bootstrap_samples: int = 5000,
    seed: int = 20260721,
) -> pd.DataFrame:
    """White Reality Check and studentized SPA equivalents over event returns."""

    matrix, _ = _return_matrix(returns)
    n = matrix.shape[0]
    metadata = _cluster_metadata(cluster_frame, expected_rows=n)
    means = matrix.mean(axis=0)
    errors = matrix.std(axis=0, ddof=1) / math.sqrt(n)
    white_observed = float(np.max(np.sqrt(n) * means))
    spa_observed = float(np.max(np.divide(means, errors, out=np.zeros_like(means), where=errors > 0)))
    centered = matrix - matrix.mean(axis=0)
    rng = np.random.default_rng(seed)
    null_means, null_errors, null_totals = _batched_cluster_null_moments(
        centered,
        metadata,
        cluster_method=cluster_method,
        bootstrap_samples=bootstrap_samples,
        rng=rng,
    )
    white_null = np.max(np.sqrt(null_totals[:, None]) * null_means, axis=1)
    spa_null = np.max(
        np.divide(
            null_means,
            null_errors,
            out=np.zeros_like(null_means),
            where=null_errors > 0,
        ),
        axis=1,
    )
    return pd.DataFrame(
        [
            {
                "test": "white_reality_check",
                "statistic": white_observed,
                "pvalue": float((1 + np.sum(white_null >= white_observed)) / (bootstrap_samples + 1)),
                "method": f"white_reality_check_equivalent_centered_{cluster_method}_cluster_max_mean",
            },
            {
                "test": "spa",
                "statistic": spa_observed,
                "pvalue": float((1 + np.sum(spa_null >= spa_observed)) / (bootstrap_samples + 1)),
                "method": f"spa_equivalent_centered_{cluster_method}_cluster_studentized_max",
            },
        ]
    )


white_reality_check = white_spa_equivalent
spa_test = white_spa_equivalent


def cluster_mean_significance_tests(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    cluster_method: str = "hierarchical_year_symbol",
    bootstrap_samples: int = 5000,
    seed: int = 20260721,
) -> pd.DataFrame:
    """One-sided centered-null mean tests with whole-cluster resampling."""

    if cluster_method not in {"symbol", "hierarchical_year_symbol"}:
        raise ValueError("cluster_method must be symbol or hierarchical_year_symbol")
    frame = add_event_efficiency_metrics(ledger, combination_column=combination_column)
    frame = frame.loc[frame["event_observed"]].copy()
    frame["entry_year"] = frame["entry_date"].dt.year.astype(int)
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for combination, group in frame.groupby(combination_column, sort=True, dropna=False):
        group = group.reset_index(drop=True)
        observed = float(group["net_event_return"].mean())
        centered = group.copy()
        centered["net_event_return"] = centered["net_event_return"] - observed
        weights = _cluster_bootstrap_weights(
            centered,
            cluster_method,
            bootstrap_samples,
            rng,
        )
        centered_returns = centered["net_event_return"].to_numpy(dtype=float)
        totals = weights.sum(axis=1)
        if np.any(totals <= 0):
            raise ValueError("cluster bootstrap produced an empty resample")
        null = (weights @ centered_returns) / totals
        rows.append(
            {
                combination_column: combination,
                "mean_return": observed,
                "pvalue_one_sided": float(
                    (1 + np.sum(null >= observed)) / (bootstrap_samples + 1)
                ),
                "method": f"centered_{cluster_method}_cluster_bootstrap_mean",
            }
        )
    return pd.DataFrame(rows)


def _aligned_event_return_matrix(
    ledger: pd.DataFrame,
    *,
    combination_column: str,
    causal_keys: Sequence[str] = ("symbol", "signal_date"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = add_event_efficiency_metrics(ledger, combination_column=combination_column)
    _require_columns(frame, (combination_column, *causal_keys), "multiple-testing ledger")
    complete = frame.loc[frame["event_observed"]].copy()
    if complete.duplicated([combination_column, *causal_keys]).any():
        raise ValueError("multiple-testing causal keys must be unique per combination")
    matrix = complete.pivot(
        index=list(causal_keys), columns=combination_column, values="net_event_return"
    ).dropna(axis=0, how="any")
    if min(matrix.shape) < 2:
        raise ValueError("multiple testing requires at least two shared events and combinations")
    metadata = matrix.index.to_frame(index=False)
    if "entry_year" not in metadata:
        date_column = _first_column(metadata, ("signal_date", "entry_date"))
        if date_column is None:
            raise ValueError("causal keys require a date for hierarchical clustering")
        metadata["entry_year"] = pd.to_datetime(
            metadata[date_column], errors="raise"
        ).dt.year.astype(int)
    return matrix.reset_index(drop=True), metadata.reset_index(drop=True)


def cscv_pbo(
    returns: pd.DataFrame | np.ndarray,
    *,
    partitions: int = 8,
    observation_dates: Sequence[Any] | None = None,
    functional_duplicates: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Combinatorially symmetric cross-validation probability of backtest overfit."""

    inferred_dates: Sequence[Any] | None = None
    if isinstance(returns, pd.DataFrame) and not isinstance(returns.index, pd.RangeIndex):
        inferred_dates = returns.index
    matrix, labels = _return_matrix(returns)
    null_labels = []
    for label in labels:
        missing = pd.isna(label)
        null_labels.append(bool(missing) if np.isscalar(missing) else False)
    if len(set(labels)) != len(labels) or any(null_labels):
        raise ValueError("PBO combination identifiers must be unique and non-null")
    column_order = sorted(range(len(labels)), key=lambda index: str(labels[index]))
    matrix = matrix[:, column_order]
    labels = [labels[index] for index in column_order]
    raw_dates = observation_dates if observation_dates is not None else inferred_dates
    if raw_dates is None:
        raise ValueError("PBO requires causal observation_dates or a date index")
    if len(raw_dates) != matrix.shape[0]:
        raise ValueError("observation_dates length must match return rows")
    date_index = pd.Index(raw_dates)
    if isinstance(date_index, pd.PeriodIndex):
        date_index = date_index.to_timestamp()
    dates = pd.to_datetime(pd.Series(date_index), errors="raise", utc=True).dt.normalize()
    if dates.isna().any():
        raise ValueError("observation_dates contains null dates")
    row_order = np.argsort(dates.astype("int64").to_numpy(), kind="stable")
    matrix = matrix[row_order]
    dates = dates.iloc[row_order].reset_index(drop=True)
    duplicate_groups: list[dict[str, Any]] = []
    if functional_duplicates is not None and not functional_duplicates.empty:
        _require_columns(
            functional_duplicates,
            ("combination_id", "functionally_duplicated", "canonical_combination_id"),
            "functional duplicate audit",
        )
        canonical_by_label = {label: label for label in labels}
        duplicated = functional_duplicates.loc[
            functional_duplicates["functionally_duplicated"].astype(bool)
        ]
        for _, row in duplicated.iterrows():
            label = row["combination_id"]
            canonical = row["canonical_combination_id"]
            if label in canonical_by_label and canonical in canonical_by_label:
                canonical_by_label[label] = canonical
        audit_groups: dict[Any, list[int]] = {}
        for index, label in enumerate(labels):
            audit_groups.setdefault(canonical_by_label[label], []).append(index)
        audit_retained: list[int] = []
        for canonical in sorted(audit_groups, key=str):
            indices = audit_groups[canonical]
            canonical_indices = [index for index in indices if labels[index] == canonical]
            keep = canonical_indices[0] if canonical_indices else min(
                indices, key=lambda index: str(labels[index])
            )
            ordered_indices = sorted(indices, key=lambda index: str(labels[index]))
            audit_retained.append(keep)
            if len(indices) > 1:
                duplicate_groups.append(
                    {
                        "canonical_combination_id": labels[keep],
                        "members": [labels[index] for index in ordered_indices],
                        "excluded_duplicates": [
                            labels[index] for index in ordered_indices if index != keep
                        ],
                        "source": "functional_duplicate_audit",
                    }
                )
        audit_retained.sort(key=lambda index: str(labels[index]))
        matrix = matrix[:, audit_retained]
        labels = [labels[index] for index in audit_retained]
    retained: list[int] = []
    fingerprints: dict[str, list[int]] = {}
    for index in range(matrix.shape[1]):
        fingerprint = _canonical_hash(np.round(matrix[:, index], 12).tolist())
        fingerprints.setdefault(fingerprint, []).append(index)
    for fingerprint in sorted(fingerprints):
        indices = fingerprints[fingerprint]
        ordered_indices = sorted(indices, key=lambda index: str(labels[index]))
        retained.append(ordered_indices[0])
        if len(indices) > 1:
            duplicate_groups.append(
                {
                    "canonical_combination_id": labels[ordered_indices[0]],
                    "members": [labels[index] for index in ordered_indices],
                    "excluded_duplicates": [labels[index] for index in ordered_indices[1:]],
                    "source": "identical_result_vector",
                }
            )
    retained.sort(key=lambda index: str(labels[index]))
    matrix = matrix[:, retained]
    labels = [labels[index] for index in retained]
    if matrix.shape[1] < 2:
        raise ValueError("PBO requires at least two functionally distinct combinations")
    if partitions < 2 or partitions % 2:
        raise ValueError("partitions must be an even integer of at least two")
    unique_dates = pd.Index(dates.unique()).sort_values()
    if len(unique_dates) < partitions:
        raise ValueError("returns require at least one complete date per partition")
    date_blocks = np.array_split(unique_dates.to_numpy(), partitions)
    blocks = [np.flatnonzero(dates.isin(block).to_numpy()) for block in date_blocks]
    partition_date_ranges = [
        {
            "first_date": pd.Timestamp(block[0]).isoformat(),
            "last_date": pd.Timestamp(block[-1]).isoformat(),
            "dates": int(len(block)),
            "rows": int(len(row_indices)),
        }
        for block, row_indices in zip(date_blocks, blocks, strict=True)
    ]
    logits: list[float] = []
    selected: list[tuple[Any, ...]] = []
    for training_blocks in combinations(range(partitions), partitions // 2):
        training_set = set(training_blocks)
        train_index = np.concatenate([blocks[index] for index in training_blocks])
        test_index = np.concatenate([blocks[index] for index in range(partitions) if index not in training_set])
        training_performance = matrix[train_index].mean(axis=0)
        best = float(training_performance.max())
        winners = np.flatnonzero(
            np.isclose(training_performance, best, rtol=1e-12, atol=1e-15)
        )
        test_performance = matrix[test_index].mean(axis=0)
        average_ranks = pd.Series(test_performance).rank(method="average", ascending=True)
        percentile = float(average_ranks.iloc[winners].mean() / (matrix.shape[1] + 1))
        logits.append(float(math.log(percentile / (1.0 - percentile))))
        selected.append(tuple(labels[index] for index in winners))
    values = np.asarray(logits)
    return {
        "pbo": float(np.mean(values <= 0.0)),
        "splits": int(len(values)),
        "median_logit": float(np.median(values)),
        "logits": values,
        "selected_combinations": selected,
        "effective_combinations": int(matrix.shape[1]),
        "duplicate_groups": duplicate_groups,
        "partition_date_ranges": partition_date_ranges,
        "rank_method": "average",
        "is_tie_method": "symmetric_average_oos_rank",
        "method": "CSCV_PBO_complete_sorted_date_blocks",
    }


def deflated_event_statistic(
    event_returns: Sequence[float],
    *,
    trials: int = 290,
) -> dict[str, float | int | str | bool]:
    """Non-annualized diagnostic; its standard error is not cluster robust."""

    values = np.asarray(event_returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("event_returns must contain at least two finite values")
    if trials < 1:
        raise ValueError("trials must be positive")
    error = float(values.std(ddof=1) / math.sqrt(len(values)))
    observed = float(values.mean() / error) if error > 0 else 0.0
    expected_max = (
        NormalDist().inv_cdf((trials - 0.375) / (trials + 0.25)) if trials > 1 else 0.0
    )
    deflated = observed - expected_max
    return {
        "event_statistic": observed,
        "expected_max_under_trials": float(expected_max),
        "deflated_event_statistic": float(deflated),
        "deflated_event_probability": float(NormalDist().cdf(deflated)),
        "trials": int(trials),
        "cluster_robust": False,
        "evidence_role": "diagnostic_non_cluster_robust_not_primary_evidence",
        "method": "nonannualized_iid_normal_max_deflated_event_mean_diagnostic",
    }


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _frame_group_fingerprints(
    frame: pd.DataFrame,
    *,
    combination_column: str,
    value_columns: Sequence[str] | None,
) -> dict[Any, str]:
    _require_columns(frame, (combination_column,), "duplicate frame")
    columns = list(value_columns) if value_columns is not None else [
        column for column in frame.columns if column != combination_column
    ]
    _require_columns(frame, columns, "duplicate value columns")
    fingerprints: dict[Any, str] = {}
    for combination, group in frame.groupby(combination_column, sort=True, dropna=False):
        records = group[columns].copy()
        for column in records.select_dtypes(include=["number"]).columns:
            records[column] = records[column].astype(float).round(12)
        canonical = sorted(records.to_dict("records"), key=lambda item: json.dumps(item, sort_keys=True, default=str))
        fingerprints[combination] = _canonical_hash(canonical)
    return fingerprints


def detect_functional_duplicates(
    specs: pd.DataFrame,
    trades: pd.DataFrame,
    results: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    spec_columns: Sequence[str] | None = None,
    trade_columns: Sequence[str] | None = None,
    result_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Flag functional duplicates independently by specs, trades and results."""

    sources = {
        "spec": _frame_group_fingerprints(
            specs,
            combination_column=combination_column,
            value_columns=spec_columns,
        ),
        "trades": _frame_group_fingerprints(
            trades,
            combination_column=combination_column,
            value_columns=trade_columns,
        ),
        "results": _frame_group_fingerprints(
            results,
            combination_column=combination_column,
            value_columns=result_columns,
        ),
    }
    combinations_ids = sorted(set().union(*(set(value) for value in sources.values())), key=str)
    rows: list[dict[str, Any]] = []
    for duplicate_type, fingerprints in sources.items():
        groups: dict[str, list[Any]] = {}
        for combination, fingerprint in fingerprints.items():
            groups.setdefault(fingerprint, []).append(combination)
        for combination in combinations_ids:
            fingerprint = fingerprints.get(combination)
            members = sorted(groups.get(fingerprint, []), key=str) if fingerprint is not None else []
            rows.append(
                {
                    combination_column: combination,
                    "duplicate_type": duplicate_type,
                    "fingerprint": fingerprint,
                    "functionally_duplicated": len(members) > 1,
                    "canonical_combination_id": members[0] if members else None,
                    "duplicate_group": json.dumps([str(value) for value in members]),
                }
            )
    return pd.DataFrame(rows)


functional_duplicate_audit = detect_functional_duplicates


def _objective_percentile(values: pd.Series, direction: int) -> pd.Series:
    if direction not in (-1, 1):
        raise ValueError(f"objective {values.name} direction must be -1 or 1")
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric).all():
        raise ValueError(f"objective {values.name} contains non-finite values")
    return numeric.rank(method="average", pct=True, ascending=direction > 0)


def _pareto_ranks(frame: pd.DataFrame, objectives: Mapping[str, int]) -> np.ndarray:
    utility = np.column_stack(
        [frame[column].to_numpy(dtype=float) * direction for column, direction in objectives.items()]
    )
    remaining = list(range(len(frame)))
    ranks = np.zeros(len(frame), dtype=int)
    rank = 1
    while remaining:
        front: list[int] = []
        for index in remaining:
            others = [other for other in remaining if other != index]
            dominated = any(
                np.all(utility[other] >= utility[index])
                and np.any(utility[other] > utility[index])
                for other in others
            )
            if not dominated:
                front.append(index)
        ranks[front] = rank
        remaining = [index for index in remaining if index not in set(front)]
        rank += 1
    return ranks


def rank_combinations(
    metrics: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    objectives: Mapping[str, int] = REQUIRED_OBJECTIVES,
) -> pd.DataFrame:
    """Apply sample eligibility, Pareto ranks and the three balanced pillars."""

    _require_columns(metrics, (combination_column, *objectives), "ranking metrics")
    pillar_objectives = tuple(
        objective for pillar in PILLARS.values() for objective in pillar
    )
    if len(pillar_objectives) != len(set(pillar_objectives)):
        raise ValueError("a metric cannot appear in more than one balanced pillar")
    if set(pillar_objectives) != set(PILLAR_DIRECTIONS):
        raise ValueError("every balanced-pillar metric requires an explicit direction")
    _require_columns(metrics, pillar_objectives, "balanced pillar metrics")
    result = metrics.copy().reset_index(drop=True)
    if "selection_eligible" not in result:
        result["selection_eligible"] = _selection_eligibility(result)
    else:
        declared_eligibility = _bool_series(result, ("selection_eligible",))
        assert declared_eligibility is not None
        result["selection_eligible"] = declared_eligibility
    declared_eligibility = result["selection_eligible"].copy()
    required_metric_columns = tuple(
        dict.fromkeys((*objectives.keys(), *pillar_objectives))
    )
    objective_values = result[list(required_metric_columns)].apply(
        pd.to_numeric, errors="coerce"
    )
    result["ranking_metrics_complete"] = np.isfinite(
        objective_values.to_numpy(dtype=float)
    ).all(axis=1)
    invalid = ~result["ranking_metrics_complete"]
    if "data_valid" in result:
        data_valid = _bool_series(result, ("data_valid",))
        assert data_valid is not None
        invalid |= ~data_valid
    if "invalid_due_to_data" in result:
        invalid_flag = _bool_series(result, ("invalid_due_to_data",))
        assert invalid_flag is not None
        invalid |= invalid_flag

    not_applicable = pd.Series(False, index=result.index)
    for column in (
        "applicability",
        "semantic_applicability",
        "corrected_track_applicability",
    ):
        if column in result:
            not_applicable |= result[column].astype(str).str.strip().str.lower().eq(
                "not_applicable"
            )
    duplicated = pd.Series(False, index=result.index)
    if "functionally_duplicated" in result:
        duplicate_values = _bool_series(result, ("functionally_duplicated",))
        assert duplicate_values is not None
        duplicated = duplicate_values

    total_column = next(
        (
            column
            for column in ("complete_events", "sample_size", "n_total", "opportunities")
            if column in result
        ),
        None,
    )
    period_column = next(
        (
            column
            for column in (
                "minimum_period_complete_events",
                "min_period_sample_size",
                "min_period_n",
                "minimum_period_opportunities",
            )
            if column in result
        ),
        None,
    )
    total_sample = pd.to_numeric(
        result[total_column]
        if total_column is not None
        else pd.Series(0, index=result.index),
        errors="coerce",
    ).fillna(0)
    minimum_period = pd.to_numeric(
        result[period_column]
        if period_column is not None
        else pd.Series(0, index=result.index),
        errors="coerce",
    ).fillna(0)
    insufficient = (
        total_sample.lt(MINIMUM_TOTAL_COMPLETE_EVENTS)
        | minimum_period.lt(MINIMUM_COMPLETE_EVENTS_PER_PERIOD)
    )
    result["selection_eligible"] = (
        declared_eligibility
        & ~invalid
        & ~not_applicable
        & ~duplicated
        & ~insufficient
    )
    result["pareto_rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["balanced_score"] = np.nan
    result["ideal_distance"] = np.nan
    result["classification"] = "not_supported"
    percentile_directions = dict(PILLAR_DIRECTIONS)
    percentile_directions.update(objectives)
    for objective in percentile_directions:
        result[f"{objective}_percentile"] = np.nan
    for pillar in PILLARS:
        result[f"{pillar}_percentile"] = np.nan
    result.loc[insufficient, "classification"] = "insufficient_sample"
    result.loc[duplicated, "classification"] = "functionally_duplicate"
    result.loc[invalid, "classification"] = "invalid_due_to_data"
    result.loc[not_applicable, "classification"] = "not_applicable"
    eligible = result.loc[result["selection_eligible"]].copy()
    if eligible.empty:
        return result
    for objective, direction in percentile_directions.items():
        eligible[f"{objective}_percentile"] = _objective_percentile(
            eligible[objective], direction
        )
    for pillar, pillar_objectives in PILLARS.items():
        eligible[f"{pillar}_percentile"] = eligible[
            [f"{objective}_percentile" for objective in pillar_objectives]
        ].mean(axis=1)
    pillar_columns = [f"{pillar}_percentile" for pillar in PILLARS]
    clipped = eligible[pillar_columns].clip(lower=1e-12)
    eligible["balanced_score"] = np.exp(np.log(clipped).mean(axis=1))
    eligible["ideal_distance"] = np.sqrt(((1.0 - eligible[pillar_columns]) ** 2).sum(axis=1))
    eligible["pareto_rank"] = _pareto_ranks(eligible, objectives)
    eligible["classification"] = np.select(
        [
            eligible["time_percentile"].ge(0.75)
            & eligible["risk_percentile"].lt(0.50),
            eligible["period_return_dispersion_percentile"].le(0.25),
            eligible["return_percentile"].ge(0.75)
            & eligible["risk_percentile"].lt(0.50),
            eligible["risk_percentile"].ge(0.75)
            & eligible["return_percentile"].lt(0.50),
            eligible["pareto_rank"].eq(1),
        ],
        [
            "fast_but_unstable",
            "period_dependent",
            "high_return_high_risk",
            "low_risk_low_return",
            "pareto_promising",
        ],
        default="not_supported",
    )
    for column in eligible.columns:
        if column not in result:
            result[column] = np.nan
    result.loc[eligible.index, eligible.columns] = eligible
    result["pareto_rank"] = result["pareto_rank"].astype("Int64")
    return result


pareto_classification = rank_combinations


def objective_winners(
    ranked: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    objectives: Mapping[str, int] = REQUIRED_OBJECTIVES,
) -> pd.DataFrame:
    """Return ties for each mandatory objective using eligible rows only."""

    _require_columns(ranked, (combination_column, "selection_eligible", *objectives), "ranked metrics")
    eligible = ranked.loc[ranked["selection_eligible"].astype(bool)]
    if eligible.empty:
        return pd.DataFrame(
            columns=(
                "objective",
                "direction",
                combination_column,
                "objective_value",
                "balanced_score",
                "pareto_rank",
                "classification",
            )
        )
    rows: list[dict[str, Any]] = []
    for objective, direction in objectives.items():
        best = eligible[objective].max() if direction > 0 else eligible[objective].min()
        winners = eligible.loc[eligible[objective].eq(best)]
        for _, winner in winners.iterrows():
            rows.append(
                {
                    "objective": objective,
                    "direction": "maximize" if direction > 0 else "minimize",
                    combination_column: winner[combination_column],
                    "objective_value": float(best),
                    "balanced_score": float(winner.get("balanced_score", np.nan)),
                    "pareto_rank": winner.get("pareto_rank", pd.NA),
                    "classification": winner.get("classification", "unclassified"),
                }
            )
    return pd.DataFrame(rows)


select_objective_winners = objective_winners


def event_study_290_statistics(
    ledger: pd.DataFrame,
    *,
    combination_column: str = "combination_id",
    bootstrap_samples: int = 2000,
    seed: int = 20260721,
    declared_combination_count: int = 290,
    functional_duplicate_table: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build the complete artifact for exactly 290 declared combinations."""

    if declared_combination_count != 290:
        raise ValueError("production event study must declare exactly 290 combinations")
    prepared = prepare_opportunity_ledger(ledger, combination_column=combination_column)
    actual = int(prepared[combination_column].nunique())
    if actual != 290:
        raise ValueError(f"event study requires exactly 290 combinations; found {actual}")
    development = prepared.loc[prepared["selection_eligible"]].copy()
    all_ids = set(prepared[combination_column].unique())
    development_ids = set(development[combination_column].unique())
    if development.empty or development_ids != all_ids:
        missing = sorted(all_ids - development_ids, key=str)
        raise ValueError(
            "development-only selection evidence must cover all 290 combinations; "
            f"missing {missing}"
        )

    metrics = metrics_by_combination(development, combination_column=combination_column)
    diagnostic_metrics = metrics_by_combination(
        prepared, combination_column=combination_column
    )
    metrics["evidence_role"] = "development_selection"
    diagnostic_metrics["evidence_role"] = "all_periods_diagnostic"
    zero_cost = metrics.loc[metrics["cost_bps_per_side"].eq(0)].reset_index(drop=True)
    bootstrap_summary, bootstrap_records = cluster_bootstrap_confidence_intervals(
        development,
        combination_column=combination_column,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    hierarchical = bootstrap_summary.loc[
        bootstrap_summary["method"].eq("hierarchical_year_symbol")
        & bootstrap_summary["metric"].isin(("mean_return", "median_return")),
        [combination_column, "metric", "ci_low95", "ci_high95"],
    ]
    bootstrap_rows: list[dict[str, Any]] = []
    for combination, group in hierarchical.groupby(
        combination_column, sort=True, dropna=False
    ):
        row: dict[str, Any] = {combination_column: combination}
        for record in group.itertuples(index=False):
            metric = str(record.metric)
            row[f"bootstrap_{metric}_ci_low95"] = float(record.ci_low95)
            row[f"bootstrap_{metric}_ci_high95"] = float(record.ci_high95)
            row[f"bootstrap_{metric}_ci_width95"] = float(
                record.ci_high95 - record.ci_low95
            )
        bootstrap_rows.append(row)
    bootstrap_rank = pd.DataFrame(bootstrap_rows)
    zero_cost = zero_cost.merge(
        bootstrap_rank,
        on=combination_column,
        how="left",
        validate="one_to_one",
    )
    if functional_duplicate_table is not None:
        _require_columns(
            functional_duplicate_table,
            (combination_column, "functionally_duplicated"),
            "functional duplicate table",
        )
        normalized_duplicates = _bool_series(
            functional_duplicate_table, ("functionally_duplicated",)
        )
        assert normalized_duplicates is not None
        duplicate_flags = (
            functional_duplicate_table.assign(_duplicate=normalized_duplicates)
            .groupby(combination_column, as_index=False)["_duplicate"]
            .any()
            .rename(columns={"_duplicate": "_audit_functionally_duplicated"})
        )
        zero_cost = zero_cost.merge(
            duplicate_flags,
            on=combination_column,
            how="left",
            validate="one_to_one",
        )
        if "functionally_duplicated" in zero_cost:
            existing_duplicates = _bool_series(
                zero_cost, ("functionally_duplicated",)
            )
            assert existing_duplicates is not None
        else:
            existing_duplicates = pd.Series(False, index=zero_cost.index)
        zero_cost["functionally_duplicated"] = existing_duplicates | zero_cost[
            "_audit_functionally_duplicated"
        ].fillna(False)
        zero_cost = zero_cost.drop(columns=["_audit_functionally_duplicated"])
    ranked = rank_combinations(zero_cost, combination_column=combination_column)
    cluster_tests = cluster_mean_significance_tests(
        development,
        combination_column=combination_column,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    cluster_tests["benjamini_hochberg_pvalue"] = benjamini_hochberg(
        cluster_tests["pvalue_one_sided"]
    )
    cluster_tests["holm_pvalue"] = holm_adjust(cluster_tests["pvalue_one_sided"])
    return_matrix, cluster_frame = _aligned_event_return_matrix(
        development, combination_column=combination_column
    )
    max_t = westfall_young_max_t(
        return_matrix,
        cluster_frame=cluster_frame,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    white_spa = white_spa_equivalent(
        return_matrix,
        cluster_frame=cluster_frame,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    pbo = cscv_pbo(
        return_matrix,
        observation_dates=cluster_frame["signal_date"],
        functional_duplicates=functional_duplicate_table,
    )
    pbo_summary = pd.DataFrame(
        [
            {
                "pbo": pbo["pbo"],
                "splits": pbo["splits"],
                "median_logit": pbo["median_logit"],
                "effective_combinations": pbo["effective_combinations"],
                "rank_method": pbo["rank_method"],
                "method": pbo["method"],
            }
        ]
    )
    pbo_splits = pd.DataFrame(
        {
            "split": np.arange(int(pbo["splits"])),
            "logit": pbo["logits"],
            "selected_combination_ids": pbo["selected_combinations"],
        }
    )
    pbo_duplicates = pd.DataFrame(
        pbo["duplicate_groups"],
        columns=(
            "canonical_combination_id",
            "members",
            "excluded_duplicates",
            "source",
        ),
    )
    deflated_rows: list[dict[str, Any]] = []
    for combination, group in development.loc[development["event_observed"]].groupby(
        combination_column, sort=True, dropna=False
    ):
        deflated_rows.append(
            {
                combination_column: combination,
                **deflated_event_statistic(
                    group["event_return"].to_numpy(dtype=float),
                    trials=declared_combination_count,
                ),
            }
        )
    selection_cuts = metric_cuts(development, combination_column=combination_column)
    selection_cuts["evidence_role"] = "development_selection"
    diagnostic_cuts = metric_cuts(prepared, combination_column=combination_column)
    diagnostic_cuts["evidence_role"] = "all_periods_diagnostic"
    diagnostic_censoring = censoring_audit(
        prepared, combination_column=combination_column
    )
    diagnostic_censoring["evidence_role"] = "all_periods_diagnostic"
    diagnostic_survival = survival_incidence_table(
        prepared, combination_column=combination_column
    )
    diagnostic_survival["evidence_role"] = "all_periods_diagnostic"
    return {
        "protocol_counts": pd.DataFrame(
            [{"declared_combinations": declared_combination_count, "actual_combinations": actual}]
        ),
        "combination_metrics": metrics,
        "diagnostic_combination_metrics": diagnostic_metrics,
        "cuts": selection_cuts,
        "diagnostic_cuts": diagnostic_cuts,
        "censoring_audit": diagnostic_censoring,
        "survival_incidence": diagnostic_survival,
        "bootstrap_summary": bootstrap_summary,
        "bootstrap_records": bootstrap_records,
        "cluster_multiple_testing": cluster_tests,
        "robust_inference_diagnostics": robust_combination_inference(
            prepared,
            combination_column=combination_column,
        ),
        "westfall_young_max_t": max_t,
        "white_spa": white_spa,
        "cscv_pbo_summary": pbo_summary,
        "cscv_pbo_splits": pbo_splits,
        "pbo_duplicate_groups": pbo_duplicates,
        "diagnostic_deflated_event_statistics": pd.DataFrame(deflated_rows),
        "leave_one_out": leave_one_out_audit(
            development, combination_column=combination_column
        ),
        "concentration": concentration_statistics(
            development, combination_column=combination_column
        ),
        "ranked_combinations": ranked,
        "objective_winners": objective_winners(
            ranked, combination_column=combination_column
        ),
    }


__all__ = [
    "COSTS_BPS_PER_SIDE",
    "CONTRACT_CLASSIFICATIONS",
    "MINIMUM_COMPLETE_EVENTS_PER_PERIOD",
    "MINIMUM_OPPORTUNITIES_PER_PERIOD",
    "MINIMUM_TOTAL_COMPLETE_EVENTS",
    "MINIMUM_TOTAL_OPPORTUNITIES",
    "PILLARS",
    "PILLAR_DIRECTIONS",
    "REQUIRED_OBJECTIVES",
    "ROBUST_CLEAR_MAJORITY_POSITIVE_YEARS",
    "ROBUST_MAX_CENSORING_RATE",
    "add_event_efficiency_metrics",
    "benjamini_hochberg",
    "censoring_audit",
    "cluster_bootstrap_confidence_intervals",
    "cluster_mean_significance_tests",
    "concentration_statistics",
    "cscv_pbo",
    "deflated_event_statistic",
    "detect_functional_duplicates",
    "event_study_290_statistics",
    "holm_adjust",
    "leave_one_out_audit",
    "metric_cuts",
    "metrics_by_combination",
    "objective_winners",
    "paired_variant_comparison",
    "prepare_opportunity_ledger",
    "rank_combinations",
    "robust_combination_inference",
    "survival_incidence_table",
    "westfall_young_max_t",
    "white_spa_equivalent",
]
