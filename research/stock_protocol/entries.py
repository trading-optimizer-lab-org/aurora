"""Causal entry-event filters layered on frozen stock selections."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


def _feature_slice(
    features: pd.DataFrame,
    symbol: str,
    signal_date: pd.Timestamp,
    max_wait_sessions: int,
) -> pd.DataFrame:
    subset = features.loc[
        features["symbol"].eq(symbol) & features["date"].ge(signal_date)
    ].sort_values("date")
    return subset.head(max_wait_sessions + 1)


def _emit(candidate: pd.Series, event: pd.Series, entry_rule: str) -> dict[str, object]:
    result = candidate.to_dict()
    event_date = pd.Timestamp(event["date"]).normalize()
    result["selection_date"] = pd.Timestamp(candidate["signal_date"]).normalize()
    result["signal_date"] = event_date
    result["available_at"] = event_date
    result["entry_rule"] = entry_rule
    for column in (
        "atr20",
        "vol_12_1",
        "rvol50",
        "adj_close",
        "adj_high",
        "adj_low",
    ):
        if column in event:
            result[column] = event[column]
    return result


def apply_entry_rule(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    rule: Mapping[str, object],
) -> pd.DataFrame:
    """Turn selected candidates into distinct events known at a daily close."""

    if candidates.empty:
        return candidates.assign(entry_rule=pd.Series(dtype=str))
    required_candidates = {"signal_date", "available_at", "symbol"}
    required_features = {"date", "symbol"}
    if required_candidates - set(candidates.columns):
        raise ValueError("entry candidates lack signal provenance")
    if required_features - set(features.columns):
        raise ValueError("entry features lack date or symbol")
    source = features.copy()
    source["date"] = pd.to_datetime(source["date"], errors="raise").dt.normalize()
    if source["date"].max() >= pd.Timestamp("2021-01-01"):
        raise ValueError("entry features cross locked boundary")
    selected = candidates.copy()
    selected["signal_date"] = pd.to_datetime(selected["signal_date"], errors="raise").dt.normalize()
    kind = str(rule.get("kind", ""))
    max_wait = int(rule.get("max_wait_sessions", 21))
    if max_wait < 0 or max_wait > 252:
        raise ValueError("max_wait_sessions must be between 0 and 252")
    rows: list[dict[str, object]] = []

    for _, candidate in selected.sort_values(["signal_date", "symbol"]).iterrows():
        window = _feature_slice(
            source, str(candidate["symbol"]), pd.Timestamp(candidate["signal_date"]), max_wait
        )
        if window.empty:
            continue
        event: pd.Series | None = None
        label = kind
        if kind in {"immediate_next_open", "close_vs_next_open"}:
            event = window.iloc[0]
        elif kind == "breakout":
            lookback = int(rule["window"])
            column = f"breakout_{lookback}"
            if column not in window:
                raise ValueError(f"entry features missing {column}")
            matches = window.loc[window[column].astype(bool)]
            event = None if matches.empty else matches.iloc[0]
            label = column
        elif kind == "breakout_rvol":
            lookback = int(rule.get("window", 20))
            column = f"breakout_{lookback}"
            if column not in window or "rvol50" not in window:
                raise ValueError("entry features missing breakout or rvol50")
            matches = window.loc[
                window[column].astype(bool)
                & pd.to_numeric(window["rvol50"], errors="coerce").ge(float(rule["threshold"]))
            ]
            event = None if matches.empty else matches.iloc[0]
            label = f"{column}_rvol50_{float(rule['threshold']):g}"
        elif kind == "sma_filter":
            lookback = int(rule["window"])
            column = f"sma_{lookback}"
            if column not in window:
                raise ValueError(f"entry features missing {column}")
            first = window.iloc[0]
            if float(first["adj_close"]) > float(first[column]):
                event = first
            label = f"above_{column}"
        elif kind == "consolidation":
            lookback = int(rule["window"])
            column = f"consolidation_{lookback}"
            if column not in window:
                raise ValueError(f"entry features missing {column}")
            first = window.iloc[0]
            if float(first[column]) <= float(rule.get("max_width", 0.15)):
                event = first
            label = column
        else:
            raise NotImplementedError(f"entry rule {kind!r} is not implemented")
        if event is not None:
            rows.append(_emit(candidate, event, label))
    return pd.DataFrame(rows)
