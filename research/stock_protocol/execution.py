"""Causal next-open execution and conservative daily-bar exits."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .dataset import ResearchPanel
from .locked_access import LockedDataAuthorization, assert_locked_access


MAX_HOLDING_SESSIONS = 252


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "symbol",
            "signal_date",
            "entry_date",
            "entry_price",
            "exit_date",
            "exit_price",
            "optimistic_exit_price",
            "exit_reason",
            "gross_return",
            "volatility",
            "score",
        ]
    )


def _levels(
    signal: Mapping[str, Any], entry: float, rule: Mapping[str, object]
) -> tuple[float | None, float | None]:
    kind = str(rule.get("kind", "none"))
    atr = float(signal.get("atr20", 0.0) or 0.0)
    stop: float | None = None
    target: float | None = None
    if kind in {"catastrophe_atr", "stop_and_target"} and "k" in rule:
        stop = entry - float(rule["k"]) * atr
    if kind == "catastrophe_atr":
        stop = entry - float(rule.get("k", 3.0)) * atr
    if kind in {"initial_stop_pct", "stop_and_target"} and "stop_pct" in rule:
        stop = entry * (1.0 - float(rule["stop_pct"]) / 100.0)
    if kind in {"take_profit", "stop_and_target"}:
        target = entry * (1.0 + float(rule.get("target_pct", 10.0)) / 100.0)
    return stop, target


def _validate_rule(rule: Mapping[str, object]) -> int:
    holding = int(rule.get("holding_sessions", 63))
    if holding < 1 or holding > MAX_HOLDING_SESSIONS:
        raise ValueError("holding_sessions must be between 1 and 252")
    supported = {
        "none",
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
    kind = str(rule.get("kind", "none"))
    if kind not in supported:
        raise NotImplementedError(f"exit rule {kind} is not implemented")
    return holding


def _prior_level(group: pd.DataFrame, index: int, kind: str) -> float | None:
    if kind in {"min_10", "min_20"}:
        window = int(kind.split("_", 1)[1])
        values = pd.to_numeric(group["low"], errors="coerce").iloc[:index]
        if len(values) < window:
            return None
        return float(values.tail(window).min())
    if kind == "sma_50":
        values = pd.to_numeric(group["adj_close"], errors="coerce").iloc[:index]
        if len(values) < 50:
            return None
        return float(values.tail(50).mean())
    return None


def _evaluate_bar(
    *,
    row: pd.Series,
    stop: float | None,
    target: float | None,
) -> tuple[float, float | None, str] | None:
    open_price = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    if stop is not None and open_price <= stop:
        return open_price, target, "gap_through_stop"
    if target is not None and open_price >= target:
        return open_price, target, "gap_through_target"
    stop_hit = stop is not None and low <= stop
    target_hit = target is not None and high >= target
    if stop_hit and target_hit:
        return float(stop), float(target), "stop_target_conflict_conservative"
    if stop_hit:
        return float(stop), target, "stop"
    if target_hit:
        return float(target), target, "take_profit"
    return None


def execute_next_open(
    signal_frame: pd.DataFrame,
    panel: ResearchPanel,
    exit_rule: dict[str, object],
    *,
    ranking_keep: pd.DataFrame | None = None,
    locked_authorization: LockedDataAuthorization | None = None,
) -> pd.DataFrame:
    """Execute distinct signal events at next open, one live trade per symbol."""

    holding = _validate_rule(exit_rule)
    if signal_frame.empty:
        return _empty_trades()
    required = {"signal_date", "available_at", "symbol"}
    missing = required - set(signal_frame.columns)
    if missing:
        raise ValueError(f"signal frame missing columns: {sorted(missing)}")
    signals = signal_frame.copy()
    signals["signal_date"] = pd.to_datetime(signals["signal_date"], errors="raise")
    signals["available_at"] = pd.to_datetime(signals["available_at"], errors="raise")
    if (signals["available_at"] > signals["signal_date"]).any():
        raise ValueError("signal cannot be used before available_at")
    signals = signals.sort_values(["signal_date", "symbol", "score"], ascending=[True, True, False])
    source = panel.frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    source["date"] = pd.to_datetime(source["date"], errors="raise").dt.normalize()
    if source["date"].max() >= pd.Timestamp("2021-01-01"):
        assert_locked_access(
            locked_authorization,
            latest_date=source["date"].max(),
        )
    by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in source.groupby("symbol", sort=False)
    }
    unavailable_until: dict[str, pd.Timestamp] = {}
    trades: list[dict[str, object]] = []
    kind = str(exit_rule.get("kind", "none"))
    keep_by_date: dict[pd.Timestamp, set[str]] = {}
    if kind == "ranking_hysteresis":
        if ranking_keep is None or not {"signal_date", "symbol"} <= set(ranking_keep.columns):
            raise ValueError("ranking hysteresis requires causal keep-set observations")
        keep_frame = ranking_keep.copy()
        keep_frame["signal_date"] = pd.to_datetime(
            keep_frame["signal_date"], errors="raise"
        ).dt.normalize()
        keep_by_date = {
            pd.Timestamp(date): set(group["symbol"].astype(str))
            for date, group in keep_frame.groupby("signal_date", sort=True)
        }

    for signal in signals.itertuples(index=False):
        signal_values = signal._asdict()
        symbol = str(signal_values["symbol"])
        group = by_symbol.get(symbol)
        if group is None:
            continue
        signal_date = pd.Timestamp(signal_values["signal_date"]).normalize()
        entry_candidates = group.index[group["date"] > signal_date]
        if len(entry_candidates) == 0:
            continue
        entry_idx = int(entry_candidates[0])
        entry_date = pd.Timestamp(group.iloc[entry_idx]["date"])
        if symbol in unavailable_until and entry_date <= unavailable_until[symbol]:
            continue
        entry_price = float(group.iloc[entry_idx]["open"])
        if not np.isfinite(entry_price) or entry_price <= 0:
            continue
        stop, target = _levels(signal_values, entry_price, exit_rule)
        end_idx = min(entry_idx + holding, len(group) - 1)
        exit_idx = end_idx
        exit_price = float(group.iloc[end_idx]["close"])
        optimistic_exit_price: float | None = None
        exit_reason = "time_exit"
        trailing_high = entry_price
        breakout_level = signal_values.get("breakout_level")

        for index in range(entry_idx, end_idx + 1):
            row = group.iloc[index]
            row_date = pd.Timestamp(row["date"]).normalize()
            if (
                kind == "ranking_hysteresis"
                and row_date > signal_date
                and row_date in keep_by_date
                and symbol not in keep_by_date[row_date]
                and index + 1 < len(group)
            ):
                exit_idx = index + 1
                exit_price = float(group.iloc[exit_idx]["open"])
                exit_reason = "ranking_hysteresis_next_open"
                break
            if kind == "trailing_atr":
                atr = float(signal_values.get("atr20", 0.0) or 0.0)
                trailing_stop = trailing_high - float(exit_rule.get("k", 3.0)) * atr
                stop = trailing_stop if stop is None else max(stop, trailing_stop)
            elif kind in {"min_10", "min_20", "sma_50"}:
                stop = _prior_level(group, index, kind)
            elif kind == "breakout_failure" and breakout_level is not None:
                elapsed = index - entry_idx
                stop = (
                    float(breakout_level)
                    if elapsed < int(exit_rule.get("failure_window", 1))
                    else None
                )

            outcome = _evaluate_bar(row=row, stop=stop, target=target)
            if outcome is not None:
                exit_price, optimistic_exit_price, exit_reason = outcome
                exit_idx = index
                break
            trailing_high = max(trailing_high, float(row["high"]))

        exit_date = pd.Timestamp(group.iloc[exit_idx]["date"])
        unavailable_until[symbol] = exit_date
        trades.append(
            {
                "symbol": symbol,
                "signal_date": signal_date.date().isoformat(),
                "entry_date": entry_date.date().isoformat(),
                "entry_price": entry_price,
                "exit_date": exit_date.date().isoformat(),
                "exit_price": exit_price,
                "optimistic_exit_price": optimistic_exit_price,
                "exit_reason": exit_reason,
                "gross_return": exit_price / entry_price - 1.0,
                "volatility": float(signal_values.get("vol_12_1", np.nan)),
                "score": float(signal_values.get("score", np.nan)),
            }
        )
    return pd.DataFrame(trades) if trades else _empty_trades()
