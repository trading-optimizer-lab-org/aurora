"""Long-only sizing and daily cash/position portfolio accounting."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .dataset import ResearchPanel


def _normalise_cap(value: object) -> float | None:
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
        return None
    if value is None:
        return None
    cap = float(value)
    if not 0 < cap <= 1:
        raise ValueError("asset_cap must be between zero and one")
    return cap


def build_portfolio(
    trades: pd.DataFrame, portfolio_rule: dict[str, object]
) -> pd.DataFrame:
    """Assign implementable target weights; unallocated capital remains cash."""

    if trades.empty:
        result = trades.copy()
        result["weight"] = pd.Series(dtype=float)
        result["cash_weight"] = pd.Series(dtype=float)
        return result
    required = {"entry_date", "symbol"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"trades missing sizing columns: {sorted(missing)}")
    result = trades.copy()
    sizing = str(portfolio_rule.get("sizing", "equal"))
    cap = _normalise_cap(portfolio_rule.get("asset_cap"))
    if sizing == "capped_inverse_vol" and cap is None:
        cap = 0.10
    if sizing in {"inverse_vol", "capped_inverse_vol"}:
        if "volatility" not in result.columns:
            raise ValueError("inverse volatility sizing requires volatility")
        volatility = pd.to_numeric(result["volatility"], errors="coerce")
        if volatility.isna().any() or volatility.le(0).any():
            raise ValueError("inverse volatility sizing requires positive finite volatility")
        inverse = 1.0 / volatility
        result["weight"] = inverse / inverse.groupby(result["entry_date"]).transform("sum")
    elif sizing == "equal":
        result["weight"] = result.groupby("entry_date")["symbol"].transform(
            lambda symbols: 1.0 / len(symbols)
        )
    else:
        raise NotImplementedError(f"portfolio sizing {sizing} is not implemented")
    if cap is not None:
        result["weight"] = result["weight"].clip(upper=cap)
    grouped_weight = result.groupby("entry_date")["weight"].transform("sum")
    if grouped_weight.gt(1.0 + 1e-12).any():
        result["weight"] = result["weight"].div(grouped_weight.clip(lower=1.0))
        grouped_weight = result.groupby("entry_date")["weight"].transform("sum")
    result["cash_weight"] = (1.0 - grouped_weight).clip(lower=0.0)
    return result


def _price_map(panel: ResearchPanel) -> tuple[pd.DataFrame, dict[tuple[pd.Timestamp, str], pd.Series]]:
    prices = panel.frame.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    if prices["date"].max() >= pd.Timestamp("2021-01-01"):
        raise ValueError("portfolio source crosses locked boundary")
    prices = prices.sort_values(["date", "symbol"]).drop_duplicates(["date", "symbol"], keep="last")
    lookup = {
        (pd.Timestamp(row.date), str(row.symbol)): pd.Series(row._asdict())
        for row in prices.itertuples(index=False)
    }
    return prices, lookup


def simulate_daily_portfolio(
    trades: pd.DataFrame,
    panel: ResearchPanel,
    *,
    initial_capital: float = 100_000.0,
    cost_bps_per_side: float = 0.0,
    max_volume_participation: float = 0.10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Convert weighted trades into cash, positions and one daily equity curve."""

    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital must be positive and finite")
    if cost_bps_per_side < 0:
        raise ValueError("cost_bps_per_side cannot be negative")
    if not 0 < max_volume_participation <= 1:
        raise ValueError("max_volume_participation must be in (0, 1]")
    if trades.empty:
        raise ValueError("cannot simulate an empty trade ledger")
    required = {"symbol", "entry_date", "entry_price", "exit_date", "exit_price", "weight"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"trade ledger missing columns: {sorted(missing)}")

    prices, lookup = _price_map(panel)
    ledger = trades.copy().reset_index(drop=True)
    ledger["trade_id"] = np.arange(len(ledger), dtype=int)
    for column in ("entry_date", "exit_date"):
        ledger[column] = pd.to_datetime(ledger[column], errors="raise").dt.normalize()
    if (ledger["exit_date"] < ledger["entry_date"]).any():
        raise ValueError("exit_date cannot precede entry_date")
    if ledger["exit_date"].max() >= pd.Timestamp("2021-01-01"):
        raise ValueError("trade ledger crosses locked boundary")
    ledger["entry_cost"] = 0.0
    ledger["exit_cost"] = 0.0
    ledger["shares"] = 0.0
    ledger["entry_notional"] = 0.0
    ledger["exit_notional"] = 0.0
    ledger["capacity_reduced"] = False
    ledger["status"] = "pending"

    calendar = prices.loc[
        prices["date"].between(ledger["entry_date"].min(), ledger["exit_date"].max()),
        "date",
    ].drop_duplicates().sort_values()
    if calendar.empty:
        raise ValueError("no prices overlap the trade ledger")

    cash = float(initial_capital)
    positions: dict[str, dict[str, Any]] = {}
    curve_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    prior_equity = float(initial_capital)
    cost_rate = float(cost_bps_per_side) / 10_000.0

    for date in calendar:
        timestamp = pd.Timestamp(date)
        day_costs = 0.0
        day_traded = 0.0

        exiting = ledger.loc[(ledger["exit_date"] == timestamp) & ledger["status"].eq("open")]
        for index, trade in exiting.iterrows():
            symbol = str(trade["symbol"])
            position = positions.pop(symbol, None)
            if position is None:
                continue
            exit_notional = float(position["shares"]) * float(trade["exit_price"])
            exit_cost = exit_notional * cost_rate
            cash += exit_notional - exit_cost
            day_costs += exit_cost
            day_traded += exit_notional
            ledger.loc[index, ["exit_notional", "exit_cost", "status"]] = [
                exit_notional,
                exit_cost,
                "closed",
            ]

        open_value = cash
        for symbol, position in positions.items():
            row = lookup.get((timestamp, symbol))
            if row is None:
                raise ValueError(f"missing daily valuation for {symbol} on {timestamp.date()}")
            open_value += float(position["shares"]) * float(row["open"])

        entering = ledger.loc[(ledger["entry_date"] == timestamp) & ledger["status"].eq("pending")]
        for index, trade in entering.sort_values(["weight", "symbol"], ascending=[False, True]).iterrows():
            symbol = str(trade["symbol"])
            if symbol in positions:
                ledger.loc[index, "status"] = "rejected_duplicate_position"
                continue
            row = lookup.get((timestamp, symbol))
            if row is None:
                ledger.loc[index, "status"] = "rejected_missing_price"
                continue
            entry_price = float(trade["entry_price"])
            desired = max(0.0, float(trade["weight"])) * open_value
            volume_capacity = float(row["volume"]) * entry_price * max_volume_participation
            affordable = cash / (1.0 + cost_rate)
            notional = min(desired, volume_capacity, affordable)
            if notional <= 0:
                ledger.loc[index, "status"] = "rejected_insufficient_capital"
                continue
            shares = notional / entry_price
            entry_cost = notional * cost_rate
            cash -= notional + entry_cost
            positions[symbol] = {"shares": shares, "trade_id": int(trade["trade_id"])}
            day_costs += entry_cost
            day_traded += notional
            ledger.loc[index, ["shares", "entry_notional", "entry_cost", "capacity_reduced", "status"]] = [
                shares,
                notional,
                entry_cost,
                bool(notional + 1e-9 < desired),
                "open",
            ]

        same_day_exits = ledger.loc[(ledger["exit_date"] == timestamp) & ledger["status"].eq("open")]
        for index, trade in same_day_exits.iterrows():
            if trade["entry_date"] != timestamp:
                continue
            symbol = str(trade["symbol"])
            position = positions.pop(symbol)
            exit_notional = float(position["shares"]) * float(trade["exit_price"])
            exit_cost = exit_notional * cost_rate
            cash += exit_notional - exit_cost
            day_costs += exit_cost
            day_traded += exit_notional
            ledger.loc[index, ["exit_notional", "exit_cost", "status"]] = [exit_notional, exit_cost, "closed"]

        market_value = 0.0
        for symbol, position in positions.items():
            row = lookup.get((timestamp, symbol))
            if row is None:
                raise ValueError(f"missing daily valuation for {symbol} on {timestamp.date()}")
            dividend = float(row.get("dividends", 0.0) or 0.0)
            if dividend:
                cash += float(position["shares"]) * dividend
            value = float(position["shares"]) * float(row["close"])
            market_value += value
            position_rows.append(
                {
                    "date": timestamp,
                    "symbol": symbol,
                    "trade_id": int(position["trade_id"]),
                    "shares": float(position["shares"]),
                    "close": float(row["close"]),
                    "market_value": value,
                }
            )
        equity = cash + market_value
        if not np.isfinite(equity) or equity <= 0:
            raise ValueError("portfolio equity became non-positive or non-finite")
        curve_rows.append(
            {
                "date": timestamp,
                "cash": cash,
                "market_value": market_value,
                "equity": equity,
                "gross_exposure": market_value / equity,
                "turnover": day_traded / prior_equity if prior_equity > 0 else 0.0,
                "costs": day_costs,
            }
        )
        prior_equity = equity

    ledger["net_return"] = np.where(
        ledger["status"].eq("closed") & ledger["entry_notional"].gt(0),
        (ledger["exit_notional"] - ledger["exit_cost"])
        / (ledger["entry_notional"] + ledger["entry_cost"])
        - 1.0,
        np.nan,
    )
    curve = pd.DataFrame(curve_rows)
    positions_frame = pd.DataFrame(position_rows)
    return curve, positions_frame, ledger
