"""Causal next-open trade execution for daily OHLC data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dataset import ResearchPanel


def _exit_level(row: pd.Series, entry: float, rule: dict[str, object]) -> tuple[float | None, str | None]:
    kind = str(rule.get("kind", "none"))
    if kind == "catastrophe_atr":
        return entry - float(rule.get("k", 3)) * float(row.get("atr20", 0.0) or 0.0), "catastrophe_stop"
    if kind == "take_profit":
        return entry * (1.0 + float(rule.get("target_pct", 10)) / 100.0), "take_profit"
    return None, None


def execute_next_open(
    signal_frame: pd.DataFrame,
    panel: ResearchPanel,
    exit_rule: dict[str, object],
) -> pd.DataFrame:
    """Execute a signal at the next available open and realize a causal trade."""

    if signal_frame.empty:
        return pd.DataFrame(columns=["symbol", "signal_date", "entry_date", "entry_price", "exit_date", "exit_price", "exit_reason", "gross_return"])
    source = panel.frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    by_symbol = {symbol: group.reset_index(drop=True) for symbol, group in source.groupby("symbol")}
    trades: list[dict[str, object]] = []
    hold = int(exit_rule.get("holding_sessions", 63))
    for signal in signal_frame.itertuples(index=False):
        group = by_symbol.get(signal.symbol)
        if group is None:
            continue
        idxs = group.index[group["date"] > pd.Timestamp(signal.signal_date)]
        if len(idxs) == 0:
            continue
        entry_idx = int(idxs[0])
        entry_row = group.iloc[entry_idx]
        entry = float(entry_row["open"])
        if not np.isfinite(entry) or entry <= 0:
            continue
        stop, stop_reason = _exit_level(signal._asdict(), entry, exit_rule)
        end_idx = min(entry_idx + hold, len(group) - 1)
        exit_idx = end_idx
        exit_price = float(group.iloc[end_idx]["close"])
        exit_reason = "time_exit"
        for idx in range(entry_idx, end_idx + 1):
            row = group.iloc[idx]
            if stop is not None:
                if float(row["open"]) <= stop:
                    exit_idx, exit_price, exit_reason = idx, float(row["open"]), "gap_through_stop"
                    break
                if float(row["low"]) <= stop:
                    exit_idx, exit_price, exit_reason = idx, float(stop), stop_reason or "stop"
                    break
            if str(exit_rule.get("kind")) == "take_profit" and stop is not None and float(row["high"]) >= stop:
                target = stop
                exit_idx, exit_price, exit_reason = idx, target, "take_profit"
                break
        trades.append({
            "symbol": signal.symbol,
            "signal_date": pd.Timestamp(signal.signal_date).date().isoformat(),
            "entry_date": group.iloc[entry_idx]["date"].date().isoformat(),
            "entry_price": entry,
            "exit_date": group.iloc[exit_idx]["date"].date().isoformat(),
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "gross_return": exit_price / entry - 1.0,
        })
    return pd.DataFrame(trades)
