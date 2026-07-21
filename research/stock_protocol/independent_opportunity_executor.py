"""Causal execution of independent stock-protocol opportunities.

Unlike :mod:`.execution`, this module deliberately has no portfolio state.  The
input frame defines the entry cohort; the full panel is follow-up data and is
therefore never clipped to the cohort's year, fold, or reporting period.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ...data_contracts.calendars import MarketCalendarKind, expected_sessions
from .dataset import ResearchPanel
from .locked_access import LockedDataAuthorization, assert_locked_access
from .opportunity_audit import symbol_metadata_frame


DATASET_CUTOFF = pd.Timestamp("2026-07-17")
MAX_HOLDING_SESSIONS = 252
TRACKS = {"exact_track", "corrected_track"}
STATUSES = {
    "completed",
    "right_censored",
    "entry_not_triggered",
    "failed_due_to_data",
    "entry_censored",
}

RESULT_COLUMNS = [
    "opportunity_id",
    "combination_id",
    "track",
    "status",
    "applicability",
    "censor_reason",
    "delisting_date",
    "symbol",
    "selection_date",
    "signal_date",
    "entry_signal_date",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "optimistic_exit_price",
    "exit_reason",
    "gross_return",
    "mtm_date",
    "mtm_price",
    "mtm_return",
    "maximum_favourable_excursion",
    "maximum_adverse_excursion",
    "intratrade_max_drawdown",
    "holding_sessions",
    "remaining_sessions_estimate",
    "calendar_days_invested",
    "stop_hit",
    "target_hit",
    "time_exit",
    "max_holding_reached",
    "volatility",
    "trajectory_volatility",
    "entry_gap",
    "coverage_market",
    "coverage_exchange",
    "coverage_calendar_source",
    "score",
]


@dataclass(frozen=True)
class _CoverageCalendar:
    market: str
    exchange: str
    source: str
    observed_sessions: pd.DatetimeIndex
    kind: MarketCalendarKind | None = None

    def sessions(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        if end < start:
            return pd.DatetimeIndex([])
        if self.kind is not None:
            return expected_sessions(start, end, self.kind)
        return self.observed_sessions[
            (self.observed_sessions >= start) & (self.observed_sessions <= end)
        ]

    def last_session(self, cutoff: pd.Timestamp) -> pd.Timestamp | None:
        if self.kind is not None:
            sessions = self.sessions(cutoff - pd.Timedelta(days=31), cutoff)
        else:
            sessions = self.observed_sessions[self.observed_sessions <= cutoff]
        if sessions.empty:
            return None
        return pd.Timestamp(sessions[-1]).normalize()

    def observed_last_session(self, cutoff: pd.Timestamp) -> pd.Timestamp | None:
        sessions = self.observed_sessions[self.observed_sessions <= cutoff]
        if sessions.empty:
            return None
        return pd.Timestamp(sessions[-1]).normalize()


@dataclass(frozen=True)
class PreparedOpportunityExecutionContext:
    """Immutable, reusable execution view of one bounded research panel."""

    source: pd.DataFrame
    groups: Mapping[str, pd.DataFrame]
    calendars: Mapping[str, _CoverageCalendar]
    effective_cutoff: pd.Timestamp


def _normalise_timestamp(value: object) -> pd.Timestamp | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    result = pd.Timestamp(timestamp)
    if result.tzinfo is not None:
        result = result.tz_convert(None)
    return result.normalize()


def _iso(value: pd.Timestamp | None) -> str | None:
    return None if value is None else value.date().isoformat()


def _finite_positive(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) and result > 0 else None


def _optional_float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return np.nan
    return result if np.isfinite(result) else np.nan


def _opportunity_id(
    combination_id: str,
    symbol: str,
    selection_date: pd.Timestamp | None,
    entry_signal_date: pd.Timestamp | None,
    entry_date: pd.Timestamp | None,
) -> str:
    identity = [
        combination_id,
        symbol,
        _iso(selection_date),
        _iso(entry_signal_date),
        _iso(entry_date),
    ]
    payload = json.dumps(identity, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_exit_rule(rule: Mapping[str, object]) -> tuple[str, int]:
    kind = str(rule.get("kind", "none"))
    supported = {
        "none",
        "time",
        "catastrophe_atr",
        "initial_stop_pct",
        "take_profit",
        "stop_and_target",
        "min_10",
        "min_20",
        "sma_50",
        "trailing_atr",
        "breakout_failure",
        "ranking_hysteresis",
    }
    if kind not in supported:
        raise NotImplementedError(f"exit rule {kind!r} is not implemented")
    holding = int(rule.get("holding_sessions", 63))
    if holding < 1 or holding > MAX_HOLDING_SESSIONS:
        raise ValueError("holding_sessions must be between 1 and 252")
    return kind, holding


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=RESULT_COLUMNS)


def _adjust_execution_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    """Put every execution price on the feature engine's adjusted basis."""

    result = frame.copy()
    raw_close = pd.to_numeric(result["close"], errors="coerce")
    adjusted_close = pd.to_numeric(result["adj_close"], errors="coerce")
    factor = adjusted_close.div(raw_close.where(raw_close.gt(0)))
    factor = factor.where(np.isfinite(factor) & factor.gt(0))
    for column in ("open", "high", "low"):
        result[column] = pd.to_numeric(result[column], errors="coerce").mul(factor)
    result["close"] = adjusted_close
    result["adj_close"] = adjusted_close
    return result


def _explicit_metadata(group: pd.DataFrame, column: str) -> str | None:
    if column not in group:
        return None
    values = {
        str(value).strip()
        for value in group[column].dropna()
        if str(value).strip() and str(value).strip().lower() != "unknown"
    }
    return next(iter(values)) if len(values) == 1 else None


def _coverage_calendars(
    groups: Mapping[str, pd.DataFrame],
) -> dict[str, _CoverageCalendar]:
    if not groups:
        return {}
    metadata = symbol_metadata_frame(groups).set_index("symbol")
    resolved: dict[str, tuple[str, str, bool]] = {}
    for symbol, group in groups.items():
        market = _explicit_metadata(group, "market")
        exchange = _explicit_metadata(group, "exchange")
        has_explicit_metadata = any(
            column in group
            and group[column].dropna().astype(str).str.strip().ne("").any()
            for column in ("market", "exchange")
        )
        if has_explicit_metadata:
            market = market or "unknown"
            exchange = exchange or "unknown"
        else:
            fallback = metadata.loc[symbol]
            market = str(fallback["market"])
            exchange = str(fallback["exchange"])
        unknown = market.lower() == "unknown" and exchange.lower() == "unknown"
        resolved[symbol] = (market, exchange, unknown)

    observed_parts: dict[tuple[str, str], list[pd.DatetimeIndex]] = {}
    for symbol, (market, exchange, unknown) in resolved.items():
        if unknown:
            continue
        key = (market, exchange)
        observed_parts.setdefault(key, []).append(
            pd.DatetimeIndex(groups[symbol]["date"])
        )
    observed_by_market = {
        key: pd.DatetimeIndex(
            np.concatenate([dates.to_numpy() for dates in parts])
        ).drop_duplicates().sort_values()
        for key, parts in observed_parts.items()
    }

    calendars: dict[str, _CoverageCalendar] = {}
    for symbol, (market, exchange, unknown) in resolved.items():
        own_dates = pd.DatetimeIndex(groups[symbol]["date"]).drop_duplicates().sort_values()
        is_us = market.strip().lower() in {
            "united states",
            "us",
            "usa",
        } or exchange.strip().lower() in {
            "nyse",
            "nasdaq",
            "amex",
            "us consolidated",
        }
        if is_us:
            calendars[symbol] = _CoverageCalendar(
                market,
                exchange,
                "registered_market_calendar:NYSE",
                observed_by_market.get((market, exchange), own_dates),
                MarketCalendarKind.NYSE,
            )
        elif not unknown:
            calendars[symbol] = _CoverageCalendar(
                market,
                exchange,
                "fallback_observed_market_exchange_sessions",
                observed_by_market[(market, exchange)],
            )
        else:
            calendars[symbol] = _CoverageCalendar(
                market,
                exchange,
                "fallback_observed_symbol_sessions_unknown_market",
                own_dates,
            )
    return calendars


def prepare_opportunity_execution_context(
    panel: ResearchPanel,
    *,
    cutoff: str | pd.Timestamp = DATASET_CUTOFF,
    locked_authorization: LockedDataAuthorization | None = None,
) -> PreparedOpportunityExecutionContext:
    """Prepare adjusted bars, symbol groups and coverage calendars once."""

    requested_cutoff = _normalise_timestamp(cutoff)
    if requested_cutoff is None:
        raise ValueError("cutoff must be a valid date")
    effective_cutoff = min(requested_cutoff, DATASET_CUTOFF)
    source = panel.frame.copy()
    required_prices = {"date", "symbol", "open", "high", "low", "close"}
    missing_prices = required_prices - set(source.columns)
    if missing_prices:
        raise ValueError(f"panel missing price columns: {sorted(missing_prices)}")
    if "adj_close" not in source:
        source["adj_close"] = source["close"]
    source["date"] = pd.to_datetime(source["date"], errors="raise")
    if source["date"].dt.tz is not None:
        source["date"] = source["date"].dt.tz_convert(None)
    source["date"] = source["date"].dt.normalize()
    source = source.loc[source["date"].le(effective_cutoff)].sort_values(
        ["symbol", "date"], kind="stable"
    )
    source = _adjust_execution_ohlc(source)
    if not source.empty and source["date"].max() >= pd.Timestamp("2021-01-01"):
        assert_locked_access(locked_authorization, latest_date=source["date"].max())
    groups = {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in source.groupby("symbol", sort=False)
    }
    return PreparedOpportunityExecutionContext(
        source=source,
        groups=groups,
        calendars=_coverage_calendars(groups),
        effective_cutoff=effective_cutoff,
    )


def _keep_sets(ranking_keep: pd.DataFrame | None) -> dict[pd.Timestamp, set[str]]:
    if ranking_keep is None:
        raise ValueError("ranking hysteresis requires causal keep-set observations")
    date_column = "signal_date" if "signal_date" in ranking_keep else "date"
    if date_column not in ranking_keep or "symbol" not in ranking_keep:
        raise ValueError("ranking hysteresis requires causal keep-set observations")
    frame = ranking_keep.copy()
    frame[date_column] = pd.to_datetime(frame[date_column], errors="raise")
    if frame[date_column].dt.tz is not None:
        frame[date_column] = frame[date_column].dt.tz_convert(None)
    frame[date_column] = frame[date_column].dt.normalize()
    if "available_at" in frame:
        available = pd.to_datetime(frame["available_at"], errors="raise")
        if available.dt.tz is not None:
            available = available.dt.tz_convert(None)
        if (available.dt.normalize() > frame[date_column]).any():
            raise ValueError("ranking keep sets must be causal")
    return {
        pd.Timestamp(date): set(group["symbol"].astype(str))
        for date, group in frame.groupby(date_column, sort=True)
    }


def _prior_level(group: pd.DataFrame, index: int, kind: str) -> float | None:
    if kind in {"min_10", "min_20"}:
        window = int(kind.split("_", 1)[1])
        values = pd.to_numeric(group["low"], errors="coerce").iloc[:index]
        if len(values) < window or values.tail(window).isna().any():
            return None
        return _finite_positive(values.tail(window).min())
    if kind == "sma_50":
        values = pd.to_numeric(group["adj_close"], errors="coerce").iloc[:index]
        if len(values) < 50 or values.tail(50).isna().any():
            return None
        return _finite_positive(values.tail(50).mean())
    return None


def _bar_outcome(
    row: pd.Series,
    *,
    stop: float | None,
    target: float | None,
) -> tuple[float, float | None, str, bool, bool] | None:
    open_price = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    if stop is not None and open_price <= stop:
        return open_price, target, "gap_through_stop", True, False
    if target is not None and open_price >= target:
        return open_price, target, "gap_through_target", False, True
    stop_hit = stop is not None and low <= stop
    target_hit = target is not None and high >= target
    if stop_hit and target_hit:
        return stop, target, "stop_target_conflict_conservative", True, False
    if stop_hit:
        return stop, target, "stop", True, False
    if target_hit:
        return target, target, "take_profit", False, True
    return None


def _path_metrics(
    path: pd.DataFrame,
    entry_price: float,
    entry_date: pd.Timestamp,
) -> dict[str, object]:
    if path.empty:
        return {
            "maximum_favourable_excursion": np.nan,
            "maximum_adverse_excursion": np.nan,
            "intratrade_max_drawdown": np.nan,
            "holding_sessions": 0,
            "calendar_days_invested": 0,
            "trajectory_volatility": np.nan,
            "volatility": np.nan,
        }
    high = pd.to_numeric(path["high"], errors="coerce")
    low = pd.to_numeric(path["low"], errors="coerce")
    running_peak = entry_price
    drawdowns: list[float] = [0.0]
    for row in path.itertuples(index=False):
        if bool(row.low_before_high):
            drawdowns.append(float(row.low) / running_peak - 1.0)
            running_peak = max(running_peak, float(row.high))
        else:
            running_peak = max(running_peak, float(row.high))
            drawdowns.append(float(row.low) / running_peak - 1.0)
    final_date = pd.Timestamp(path.iloc[-1]["date"])
    path_returns = pd.to_numeric(path["close"], errors="coerce").pct_change(
        fill_method=None
    ).dropna()
    trajectory_volatility = (
        float(path_returns.std(ddof=1) * np.sqrt(252.0))
        if len(path_returns) >= 2
        else np.nan
    )
    return {
        "maximum_favourable_excursion": float(high.max() / entry_price - 1.0),
        "maximum_adverse_excursion": float(low.min() / entry_price - 1.0),
        "intratrade_max_drawdown": float(min(drawdowns)),
        "holding_sessions": int(len(path) - 1),
        "calendar_days_invested": int((final_date - entry_date).days),
        "trajectory_volatility": trajectory_volatility,
        "volatility": trajectory_volatility,
    }


def _base_result(
    values: Mapping[str, Any],
    *,
    combination_id: str,
    track: str,
    symbol: str,
    selection_date: pd.Timestamp | None,
    entry_signal_date: pd.Timestamp | None,
    entry_date: pd.Timestamp | None,
) -> dict[str, object]:
    result = dict(values)
    result.update(
        {
            "opportunity_id": _opportunity_id(
                combination_id,
                symbol,
                selection_date,
                entry_signal_date,
                entry_date,
            ),
            "combination_id": combination_id,
            "track": track,
            "status": "failed_due_to_data",
            "applicability": "applicable",
            "censor_reason": None,
            "delisting_date": None,
            "symbol": symbol,
            "selection_date": _iso(selection_date),
            "signal_date": _iso(entry_signal_date),
            "entry_signal_date": _iso(entry_signal_date),
            "entry_date": _iso(entry_date),
            "entry_price": np.nan,
            "exit_date": None,
            "exit_price": np.nan,
            "optimistic_exit_price": np.nan,
            "exit_reason": None,
            "gross_return": np.nan,
            "mtm_date": None,
            "mtm_price": np.nan,
            "mtm_return": np.nan,
            "maximum_favourable_excursion": np.nan,
            "maximum_adverse_excursion": np.nan,
            "intratrade_max_drawdown": np.nan,
            "holding_sessions": 0,
            "remaining_sessions_estimate": np.nan,
            "calendar_days_invested": 0,
            "stop_hit": False,
            "target_hit": False,
            "time_exit": False,
            "max_holding_reached": False,
            "volatility": np.nan,
            "trajectory_volatility": np.nan,
            "entry_gap": np.nan,
            "coverage_market": None,
            "coverage_exchange": None,
            "coverage_calendar_source": None,
            "score": _optional_float(values.get("score", np.nan)),
        }
    )
    return result


def _mark_mtm(result: dict[str, object], path: pd.DataFrame, entry_price: float) -> None:
    if path.empty:
        return
    last = path.iloc[-1]
    mtm_price = _finite_positive(last["close"])
    if mtm_price is None:
        return
    result["mtm_date"] = _iso(pd.Timestamp(last["date"]))
    result["mtm_price"] = mtm_price
    result["mtm_return"] = mtm_price / entry_price - 1.0


def _delisting_date_explaining_coverage_end(
    group: pd.DataFrame,
    calendar: _CoverageCalendar,
) -> pd.Timestamp | None:
    """Return a dated delisting only when it explains the first absent session."""

    if "delisting_date" not in group or group.empty:
        return None
    coverage_end = pd.Timestamp(group.iloc[-1]["date"]).normalize()
    dated_events = {
        date
        for value in group["delisting_date"].dropna()
        if (date := _normalise_timestamp(value)) is not None
    }
    for raw_date in sorted(dated_events):
        if raw_date < coverage_end:
            continue
        unexplained_sessions = calendar.sessions(
            coverage_end + pd.Timedelta(days=1),
            raw_date - pd.Timedelta(days=1),
        )
        if unexplained_sessions.empty:
            return raw_date
    return None


def _execution_bounded_path(
    group: pd.DataFrame,
    *,
    entry_index: int,
    path_end: int,
    exit_index: int | None,
    exit_price: float | None,
    exit_reason: str | None,
) -> pd.DataFrame:
    path = (
        group.iloc[entry_index : path_end + 1].copy()
        if path_end >= entry_index
        else group.iloc[0:0].copy()
    )
    path["low_before_high"] = False
    if exit_index is None or exit_price is None or exit_reason is None or path.empty:
        return path

    exit_row = path.iloc[-1].copy()
    open_price = float(exit_row["open"])
    open_exit_reasons = {
        "gap_through_stop",
        "gap_through_target",
        "ranking_hysteresis_next_open",
    }
    if exit_reason in open_exit_reasons:
        bounded_high = bounded_low = float(exit_price)
    elif exit_reason in {"stop", "stop_target_conflict_conservative"}:
        bounded_high = open_price
        bounded_low = float(exit_price)
    elif exit_reason == "take_profit":
        bounded_high = float(exit_price)
        bounded_low = min(open_price, float(exit_row["low"]))
        exit_row["low_before_high"] = True
    else:
        return path
    exit_row["open"] = open_price
    exit_row["high"] = max(bounded_high, bounded_low)
    exit_row["low"] = min(bounded_high, bounded_low)
    exit_row["close"] = float(exit_price)
    exit_row["adj_close"] = float(exit_price)
    path.iloc[-1] = exit_row
    return path


def execute_independent_opportunities(
    signal_frame: pd.DataFrame,
    panel: ResearchPanel,
    exit_rule: Mapping[str, object],
    *,
    combination_id: str | None = None,
    ranking_keep: pd.DataFrame | None = None,
    cutoff: str | pd.Timestamp = DATASET_CUTOFF,
    track: str = "corrected_track",
    locked_authorization: LockedDataAuthorization | None = None,
    prepared_context: PreparedOpportunityExecutionContext | None = None,
) -> pd.DataFrame:
    """Execute every entry signal independently using causal daily bars.

    ``signal_frame`` is the entry cohort.  It is intentionally not used to
    bound follow-up: positions continue in ``panel`` until an observed exit,
    the configured maximum holding period, or the immutable dataset cutoff.
    """

    kind, holding = _validate_exit_rule(exit_rule)
    if track not in TRACKS:
        raise ValueError(f"track must be one of {sorted(TRACKS)}")
    if signal_frame.empty:
        return _empty_result()
    if "symbol" not in signal_frame:
        raise ValueError("signal frame missing symbol")
    signal_date_column = (
        "entry_signal_date" if "entry_signal_date" in signal_frame else "signal_date"
    )
    if signal_date_column not in signal_frame:
        raise ValueError("signal frame missing entry_signal_date or signal_date")
    if combination_id is None and "combination_id" not in signal_frame:
        raise ValueError("combination_id is required for stable opportunity identity")

    requested_cutoff = _normalise_timestamp(cutoff)
    if requested_cutoff is None:
        raise ValueError("cutoff must be a valid date")
    effective_cutoff = min(requested_cutoff, DATASET_CUTOFF)
    if prepared_context is None:
        prepared_context = prepare_opportunity_execution_context(
            panel,
            cutoff=effective_cutoff,
            locked_authorization=locked_authorization,
        )
    elif prepared_context.effective_cutoff != effective_cutoff:
        raise ValueError("prepared context cutoff differs from requested cutoff")
    groups = prepared_context.groups
    keep_by_date = _keep_sets(ranking_keep) if kind == "ranking_hysteresis" else {}

    rows: list[dict[str, object]] = []
    for _, signal in signal_frame.iterrows():
        values = signal.to_dict()
        symbol = str(values.get("symbol", ""))
        entry_signal_date = _normalise_timestamp(values.get(signal_date_column))
        selection_date = _normalise_timestamp(
            values.get("selection_date", entry_signal_date)
        )
        raw_combination = values.get("combination_id", combination_id)
        if pd.isna(raw_combination) or not str(raw_combination):
            raw_combination = combination_id
        if raw_combination is None or not str(raw_combination):
            raise ValueError("combination_id is required for every opportunity")
        row_combination = str(raw_combination)
        triggered = values.get("entry_triggered", True)
        if pd.isna(triggered):
            triggered = False
        input_applicable = values.get("applicable", True)
        if pd.isna(input_applicable):
            input_applicable = False

        group = groups.get(symbol)
        calendar = prepared_context.calendars.get(symbol)
        entry_date: pd.Timestamp | None = None
        entry_index: int | None = None
        should_seek_entry = bool(triggered) and entry_signal_date is not None and (
            bool(input_applicable) or track == "exact_track"
        )
        if should_seek_entry and group is not None:
            candidates = group.index[group["date"].gt(entry_signal_date)]
            if len(candidates):
                entry_index = int(candidates[0])
                entry_date = pd.Timestamp(group.iloc[entry_index]["date"])
        result = _base_result(
            values,
            combination_id=row_combination,
            track=track,
            symbol=symbol,
            selection_date=selection_date,
            entry_signal_date=entry_signal_date,
            entry_date=entry_date,
        )
        result["planned_holding_sessions"] = holding
        if calendar is not None:
            result["coverage_market"] = calendar.market
            result["coverage_exchange"] = calendar.exchange
            result["coverage_calendar_source"] = calendar.source

        if not bool(triggered) or entry_signal_date is None:
            result["status"] = "entry_not_triggered"
            result["censor_reason"] = "entry_signal_not_triggered"
            rows.append(result)
            continue
        if not bool(input_applicable) and track == "corrected_track":
            result["status"] = "entry_not_triggered"
            result["applicability"] = "not_applicable"
            result["censor_reason"] = "entry_rule_not_applicable"
            rows.append(result)
            continue
        if not bool(input_applicable):
            result["applicability"] = "historical_fallback"
        available_at = _normalise_timestamp(values.get("available_at", entry_signal_date))
        if available_at is None or available_at > entry_signal_date:
            raise ValueError("entry signal cannot be used before available_at")
        if group is None or group["date"].duplicated().any():
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = "missing_or_ambiguous_symbol_prices"
            rows.append(result)
            continue
        if calendar is None:
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = "missing_symbol_coverage_calendar"
            rows.append(result)
            continue
        contractual_last_session = calendar.last_session(effective_cutoff)
        if contractual_last_session is None:
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = "coverage_calendar_has_no_observed_session"
            rows.append(result)
            continue
        observed_dataset_cutoff = calendar.observed_last_session(effective_cutoff)
        dataset_ended_early = (
            observed_dataset_cutoff is None
            or observed_dataset_cutoff < contractual_last_session
        )
        coverage_end = pd.Timestamp(group.iloc[-1]["date"])
        coverage_ended_early = coverage_end < contractual_last_session
        delisting_date = _delisting_date_explaining_coverage_end(group, calendar)
        if delisting_date is not None:
            result["delisting_date"] = _iso(delisting_date)
        if entry_signal_date >= effective_cutoff:
            result["status"] = "entry_censored"
            result["censor_reason"] = "no_next_open_before_dataset_cutoff"
            rows.append(result)
            continue
        if entry_index is None:
            if coverage_ended_early and delisting_date is not None:
                result["status"] = "entry_censored"
                result["censor_reason"] = "documented_delisting_before_entry"
            elif coverage_ended_early:
                result["status"] = "failed_due_to_data"
                result["censor_reason"] = (
                    "dataset_ended_before_contractual_cutoff"
                    if dataset_ended_early
                    and observed_dataset_cutoff is not None
                    and coverage_end == observed_dataset_cutoff
                    else "symbol_coverage_ended_before_dataset_cutoff"
                )
            else:
                result["status"] = "entry_censored"
                result["censor_reason"] = "no_next_open_before_dataset_cutoff"
            rows.append(result)
            continue

        assert entry_index is not None and entry_date is not None
        entry_price = _finite_positive(group.iloc[entry_index]["open"])
        if entry_price is None:
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = "invalid_entry_open"
            rows.append(result)
            continue
        result["entry_price"] = entry_price
        signal_close = _finite_positive(values.get("adj_close"))
        if signal_close is not None:
            result["entry_gap"] = entry_price / signal_close - 1.0

        effective_kind = kind
        breakout_level = _finite_positive(values.get("breakout_level"))
        not_applicable = kind == "breakout_failure" and breakout_level is None
        if not_applicable and track == "exact_track":
            effective_kind = "none"
            result["applicability"] = "historical_fallback"
        elif not_applicable:
            result["applicability"] = "not_applicable"

        atr = _finite_positive(values.get("atr20"))
        if effective_kind in {"catastrophe_atr", "trailing_atr"} and atr is None:
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = "missing_entry_atr"
            rows.append(result)
            continue

        stop: float | None = None
        target: float | None = None
        if effective_kind == "catastrophe_atr":
            stop = entry_price - float(exit_rule.get("k", 3.0)) * float(atr)
        elif effective_kind in {"initial_stop_pct", "stop_and_target"}:
            stop = entry_price * (1.0 - float(exit_rule.get("stop_pct", 5.0)) / 100.0)
        if effective_kind in {"take_profit", "stop_and_target"}:
            target = entry_price * (
                1.0 + float(exit_rule.get("target_pct", 10.0)) / 100.0
            )

        maximum_index = entry_index + holding
        observed_end = min(maximum_index, len(group) - 1)
        trailing_high = entry_price
        exit_index: int | None = None
        exit_price: float | None = None
        optimistic_exit: float | None = None
        exit_reason: str | None = None
        stop_hit = False
        target_hit = False
        failed_reason: str | None = None
        ranking_exit_index: int | None = None
        if effective_kind == "ranking_hysteresis":
            drop_dates = [
                date
                for date, symbols in keep_by_date.items()
                if date > entry_signal_date and symbol not in symbols
            ]
            if drop_dates:
                first_drop = min(drop_dates)
                exit_candidates = group.index[
                    group["date"].gt(first_drop) & group.index.to_series().ge(entry_index)
                ]
                if len(exit_candidates):
                    ranking_exit_index = int(exit_candidates[0])

        for index in range(entry_index, observed_end + 1):
            row = group.iloc[index]
            row_date = pd.Timestamp(row["date"])
            prices = [_finite_positive(row[column]) for column in ("open", "high", "low", "close")]
            if any(price is None for price in prices) or float(row["low"]) > float(row["high"]):
                failed_reason = "invalid_follow_up_ohlc"
                observed_end = index - 1
                break

            if ranking_exit_index is not None and index == ranking_exit_index:
                exit_index = index
                exit_price = float(row["open"])
                exit_reason = "ranking_hysteresis_next_open"
                break

            current_stop = stop
            if effective_kind == "trailing_atr":
                current_stop = trailing_high - float(exit_rule.get("k", 3.0)) * float(atr)
            elif effective_kind in {"min_10", "min_20", "sma_50"}:
                current_stop = _prior_level(group, index, effective_kind)
            elif effective_kind == "breakout_failure":
                elapsed = index - entry_index
                current_stop = (
                    breakout_level
                    if elapsed < int(exit_rule.get("failure_window", 1))
                    else None
                )

            outcome = _bar_outcome(row, stop=current_stop, target=target)
            if outcome is not None:
                exit_price, optimistic_exit, exit_reason, stop_hit, target_hit = outcome
                exit_index = index
                break
            trailing_high = max(trailing_high, float(row["high"]))

        path_end = exit_index if exit_index is not None else observed_end
        path = _execution_bounded_path(
            group,
            entry_index=entry_index,
            path_end=path_end,
            exit_index=exit_index,
            exit_price=exit_price,
            exit_reason=exit_reason,
        )
        result.update(_path_metrics(path, entry_price, entry_date))
        _mark_mtm(result, path, entry_price)
        coverage_failure_reason = (
            "dataset_ended_before_contractual_cutoff"
            if dataset_ended_early
            and observed_dataset_cutoff is not None
            and coverage_end == observed_dataset_cutoff
            else "symbol_coverage_ended_before_dataset_cutoff"
        )

        if failed_reason is not None:
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = failed_reason
        elif not_applicable and track == "corrected_track":
            if coverage_ended_early and delisting_date is None:
                result["status"] = "failed_due_to_data"
                result["censor_reason"] = coverage_failure_reason
            else:
                result["status"] = "right_censored"
                result["censor_reason"] = "exit_rule_not_applicable"
        elif exit_index is not None and exit_price is not None:
            result["status"] = "completed"
            result["exit_date"] = _iso(pd.Timestamp(group.iloc[exit_index]["date"]))
            result["exit_price"] = exit_price
            result["optimistic_exit_price"] = (
                optimistic_exit if optimistic_exit is not None else np.nan
            )
            result["exit_reason"] = exit_reason
            result["gross_return"] = exit_price / entry_price - 1.0
            result["stop_hit"] = stop_hit
            result["target_hit"] = target_hit
        elif maximum_index <= len(group) - 1:
            time_row = group.iloc[maximum_index]
            time_price = _finite_positive(time_row["close"])
            if time_price is None:
                result["status"] = "failed_due_to_data"
                result["censor_reason"] = "invalid_time_exit_close"
            else:
                result["status"] = "completed"
                result["exit_date"] = _iso(pd.Timestamp(time_row["date"]))
                result["exit_price"] = time_price
                result["exit_reason"] = "time_exit"
                result["gross_return"] = time_price / entry_price - 1.0
                result["time_exit"] = True
                result["max_holding_reached"] = True
        elif coverage_ended_early and delisting_date is None:
            result["status"] = "failed_due_to_data"
            result["censor_reason"] = coverage_failure_reason
        else:
            result["status"] = "right_censored"
            result["censor_reason"] = (
                "documented_delisting_before_max_holding"
                if coverage_ended_early
                else "dataset_cutoff_before_max_holding"
            )

        if result["status"] != "completed":
            result["exit_date"] = None
            result["exit_price"] = np.nan
            result["optimistic_exit_price"] = np.nan
            result["exit_reason"] = None
            result["gross_return"] = np.nan
            result["stop_hit"] = False
            result["target_hit"] = False
            result["time_exit"] = False
            result["max_holding_reached"] = False
        result["remaining_sessions_estimate"] = (
            max(0, holding - int(result["holding_sessions"]))
            if result["status"] == "right_censored"
            else 0 if result["status"] == "completed" else np.nan
        )
        rows.append(result)

    output = pd.DataFrame(rows)
    ordered = RESULT_COLUMNS + [column for column in output if column not in RESULT_COLUMNS]
    return output.loc[:, ordered]


__all__ = [
    "DATASET_CUTOFF",
    "MAX_HOLDING_SESSIONS",
    "PreparedOpportunityExecutionContext",
    "RESULT_COLUMNS",
    "STATUSES",
    "execute_independent_opportunities",
    "prepare_opportunity_execution_context",
]
