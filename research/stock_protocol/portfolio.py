"""Long-only sizing and daily cash/position portfolio accounting."""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from .dataset import ResearchPanel
from .locked_access import LockedDataAuthorization, assert_locked_access


class UnsupportedPortfolioData(ValueError):
    """A requested portfolio constraint lacks honest point-in-time data."""


def _normalise_cap(value: object) -> float | None:
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
        return None
    if value is None:
        return None
    cap = float(value)
    if not 0 < cap <= 1:
        raise ValueError("asset_cap must be between zero and one")
    return cap


def _correlation_filter(
    trades: pd.DataFrame,
    panel: ResearchPanel,
    cap: float,
    lookback: int,
) -> pd.Series:
    prices = panel.frame[["date", "symbol", "adj_close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    accepted = pd.Series(True, index=trades.index, dtype=bool)
    for entry_date, group in trades.groupby("entry_date", sort=True):
        date = pd.Timestamp(entry_date).normalize()
        history = prices.loc[prices["date"].lt(date)]
        pivot = history.pivot(index="date", columns="symbol", values="adj_close").tail(
            lookback + 1
        )
        returns = pivot.pct_change(fill_method=None).dropna(how="all")
        chosen: list[str] = []
        ordered = group.sort_values(
            ["score", "symbol"] if "score" in group else ["symbol"],
            ascending=[False, True] if "score" in group else [True],
        )
        for index, row in ordered.iterrows():
            symbol = str(row["symbol"])
            if symbol not in returns or returns[symbol].dropna().shape[0] < 3:
                accepted.loc[index] = False
                continue
            redundant = False
            for prior in chosen:
                paired = returns[[symbol, prior]].dropna()
                if len(paired) < 3 or abs(float(paired.corr().iloc[0, 1])) > cap:
                    redundant = True
                    break
            if redundant:
                accepted.loc[index] = False
            else:
                chosen.append(symbol)
    return accepted


def _regime_exposure(
    panel: ResearchPanel,
    entry_dates: pd.Series,
    rule: dict[str, object],
) -> pd.Series:
    regime = str(rule.get("regime", "constant"))
    if regime == "constant":
        return pd.Series(1.0, index=entry_dates.index)
    benchmark = panel.frame.loc[panel.frame["symbol"].eq("SPY"), ["date", "adj_close"]].copy()
    if benchmark.empty:
        raise UnsupportedPortfolioData("SPY benchmark is required for regime exposure")
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="raise").dt.normalize()
    benchmark = benchmark.sort_values("date")
    window = int(rule.get("regime_sma_window", 200))
    values: dict[pd.Timestamp, float] = {}
    for date in pd.to_datetime(entry_dates.unique()):
        history = benchmark.loc[benchmark["date"].lt(date)].tail(max(window, 64))
        if len(history) < window:
            raise UnsupportedPortfolioData("insufficient prior SPY history for regime exposure")
        close = float(history["adj_close"].iloc[-1])
        average = float(history["adj_close"].tail(window).mean())
        volatility = float(
            history["adj_close"].pct_change(fill_method=None).tail(63).std(ddof=1)
            * np.sqrt(252.0)
        )
        if regime == "sma_200":
            exposure = 1.0 if close > average else 0.5
        elif regime == "vol_cap":
            exposure = float(np.clip(0.15 / max(volatility, 1e-9), 0.25, 1.0))
        elif regime == "conditional_panic":
            exposure = 0.25 if close <= average and volatility >= 0.25 else 1.0
        else:
            raise NotImplementedError(f"portfolio regime {regime} is not implemented")
        values[pd.Timestamp(date).normalize()] = exposure
    normalized = pd.to_datetime(entry_dates).dt.normalize()
    return normalized.map(values).astype(float)


def build_portfolio(
    trades: pd.DataFrame,
    portfolio_rule: dict[str, object],
    *,
    panel: ResearchPanel | None = None,
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
    result["portfolio_rejected_reason"] = ""
    if "sector_cap" in portfolio_rule:
        raise UnsupportedPortfolioData(
            "sector cap requires historical point-in-time sector classification"
        )
    eligible = pd.Series(True, index=result.index, dtype=bool)
    if "corr_cap" in portfolio_rule:
        if panel is None:
            raise UnsupportedPortfolioData("correlation cap requires a daily price panel")
        eligible = _correlation_filter(
            result,
            panel,
            float(portfolio_rule["corr_cap"]),
            int(portfolio_rule.get("corr_lookback", 252)),
        )
        result.loc[~eligible, "portfolio_rejected_reason"] = "correlation_cap"
    sizing = str(portfolio_rule.get("sizing", "equal"))
    cap = _normalise_cap(portfolio_rule.get("asset_cap"))
    if sizing == "capped_inverse_vol" and cap is None:
        cap = 0.10
    result["weight"] = 0.0
    active = result.loc[eligible].copy()
    if sizing in {"inverse_vol", "capped_inverse_vol"}:
        if "volatility" not in result.columns:
            raise ValueError("inverse volatility sizing requires volatility")
        volatility = pd.to_numeric(active["volatility"], errors="coerce")
        usable_volatility = volatility.gt(0) & np.isfinite(volatility)
        rejected_index = volatility.index[~usable_volatility]
        result.loc[rejected_index, "portfolio_rejected_reason"] = "invalid_volatility"
        active = active.loc[usable_volatility].copy()
        volatility = volatility.loc[usable_volatility]
        if active.empty:
            raise UnsupportedPortfolioData(
                "inverse volatility sizing requires positive finite volatility"
            )
        inverse = 1.0 / volatility
        result.loc[active.index, "weight"] = inverse / inverse.groupby(active["entry_date"]).transform("sum")
    elif sizing == "equal":
        result.loc[active.index, "weight"] = active.groupby("entry_date")["symbol"].transform(
            lambda symbols: 1.0 / len(symbols)
        )
    else:
        raise NotImplementedError(f"portfolio sizing {sizing} is not implemented")
    if cap is not None:
        result["weight"] = result["weight"].clip(upper=cap)
    if panel is not None or str(portfolio_rule.get("regime", "constant")) != "constant":
        if panel is None:
            raise UnsupportedPortfolioData("regime exposure requires a daily price panel")
        result["regime_exposure"] = _regime_exposure(
            panel, result["entry_date"], portfolio_rule
        )
    else:
        result["regime_exposure"] = 1.0
    result["weight"] = result["weight"].mul(result["regime_exposure"])
    grouped_weight = result.groupby("entry_date")["weight"].transform("sum")
    if grouped_weight.gt(1.0 + 1e-12).any():
        result["weight"] = result["weight"].div(grouped_weight.clip(lower=1.0))
        grouped_weight = result.groupby("entry_date")["weight"].transform("sum")
    result["cash_weight"] = (1.0 - grouped_weight).clip(lower=0.0)
    return result


class _PricePoint(NamedTuple):
    open: float
    close: float
    volume: float
    dividends: float
    stock_splits: float


def _price_map(
    panel: ResearchPanel,
    *,
    symbols: set[str] | None = None,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
    locked_authorization: LockedDataAuthorization | None = None,
) -> tuple[pd.DataFrame, dict[tuple[pd.Timestamp, str], _PricePoint]]:
    source = panel.frame
    dates = pd.to_datetime(source["date"], errors="raise").dt.normalize()
    date_mask = pd.Series(True, index=source.index)
    if start_date is not None:
        date_mask &= dates.ge(pd.Timestamp(start_date).normalize())
    if end_date is not None:
        date_mask &= dates.le(pd.Timestamp(end_date).normalize())
    calendar = pd.DataFrame(
        {"date": dates.loc[date_mask].drop_duplicates().sort_values().to_numpy()}
    )
    mask = date_mask.copy()
    if symbols is not None:
        mask &= source["symbol"].astype(str).isin(symbols)
    required = ["date", "symbol", "open", "close", "volume"]
    optional = ["dividends", "stock_splits"]
    missing = set(required) - set(source.columns)
    if missing:
        raise ValueError(f"portfolio source missing columns: {sorted(missing)}")
    prices = source.loc[mask, required + [c for c in optional if c in source]].copy()
    prices["date"] = dates.loc[mask].to_numpy()
    for column in optional:
        if column not in prices:
            prices[column] = 0.0
    if calendar["date"].max() >= pd.Timestamp("2021-01-01"):
        assert_locked_access(
            locked_authorization,
            latest_date=calendar["date"].max(),
        )
    prices = prices.sort_values(["date", "symbol"]).drop_duplicates(["date", "symbol"], keep="last")
    lookup = {
        (pd.Timestamp(date), str(symbol)): _PricePoint(
            float(open_price),
            float(close_price),
            float(volume),
            float(dividends),
            float(stock_splits),
        )
        for date, symbol, open_price, close_price, volume, dividends, stock_splits
        in prices[[
            "date",
            "symbol",
            "open",
            "close",
            "volume",
            "dividends",
            "stock_splits",
        ]].itertuples(index=False, name=None)
    }
    return calendar, lookup


def simulate_daily_portfolio(
    trades: pd.DataFrame,
    panel: ResearchPanel,
    *,
    initial_capital: float = 100_000.0,
    cost_bps_per_side: float = 0.0,
    max_volume_participation: float = 0.10,
    locked_authorization: LockedDataAuthorization | None = None,
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

    ledger = trades.copy().reset_index(drop=True)
    ledger["trade_id"] = np.arange(len(ledger), dtype=int)
    for column in ("entry_date", "exit_date"):
        ledger[column] = pd.to_datetime(ledger[column], errors="raise").dt.normalize()
    if (ledger["exit_date"] < ledger["entry_date"]).any():
        raise ValueError("exit_date cannot precede entry_date")
    if ledger["exit_date"].max() >= pd.Timestamp("2021-01-01"):
        assert_locked_access(
            locked_authorization,
            latest_date=ledger["exit_date"].max(),
        )
    prices, lookup = _price_map(
        panel,
        symbols=set(ledger["symbol"].astype(str)),
        start_date=ledger["entry_date"].min(),
        end_date=ledger["exit_date"].max(),
        locked_authorization=locked_authorization,
    )
    ledger["entry_cost"] = 0.0
    ledger["exit_cost"] = 0.0
    ledger["shares"] = 0.0
    ledger["entry_notional"] = 0.0
    ledger["exit_notional"] = 0.0
    ledger["capacity_reduced"] = False
    ledger["split_adjustment_count"] = 0
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

        for symbol, position in positions.items():
            row = lookup.get((timestamp, symbol))
            if row is None:
                continue
            split_ratio = float(row.stock_splits or 0.0)
            if split_ratio > 0 and not np.isclose(split_ratio, 1.0):
                position["shares"] = float(position["shares"]) * split_ratio
                trade_id = int(position["trade_id"])
                ledger.loc[ledger["trade_id"].eq(trade_id), "split_adjustment_count"] += 1

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
            mark = (
                float(row.open)
                if row is not None
                else float(position["last_close"])
            )
            open_value += float(position["shares"]) * mark

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
            volume_capacity = float(row.volume) * entry_price * max_volume_participation
            affordable = cash / (1.0 + cost_rate)
            notional = min(desired, volume_capacity, affordable)
            if notional <= 0:
                ledger.loc[index, "status"] = "rejected_insufficient_capital"
                continue
            shares = notional / entry_price
            entry_cost = notional * cost_rate
            cash -= notional + entry_cost
            positions[symbol] = {
                "shares": shares,
                "trade_id": int(trade["trade_id"]),
                "last_close": entry_price,
            }
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
            carried_forward = row is None
            if row is not None:
                dividend = float(row.dividends or 0.0)
                if dividend:
                    cash += float(position["shares"]) * dividend
                position["last_close"] = float(row.close)
            close = float(position["last_close"])
            value = float(position["shares"]) * close
            market_value += value
            position_rows.append(
                {
                    "date": timestamp,
                    "symbol": symbol,
                    "trade_id": int(position["trade_id"]),
                    "shares": float(position["shares"]),
                    "close": close,
                    "market_value": value,
                    "price_carried_forward": carried_forward,
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
