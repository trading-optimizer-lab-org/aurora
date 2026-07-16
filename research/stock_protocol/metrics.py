"""Strict metrics computed from one chronological daily portfolio curve."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


TRADING_DAYS = 252.0


def _validated_curve(equity_curve: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "equity"}
    missing = required - set(equity_curve.columns)
    if missing:
        raise ValueError(f"equity curve missing columns: {sorted(missing)}")
    curve = equity_curve.copy()
    curve["date"] = pd.to_datetime(curve["date"], errors="raise").dt.normalize()
    if not curve["date"].is_monotonic_increasing or not curve["date"].is_unique:
        raise ValueError("equity curve dates must be unique and sorted")
    equity = pd.to_numeric(curve["equity"], errors="coerce")
    if equity.isna().any() or not np.isfinite(equity).all() or equity.le(0).any():
        raise ValueError("equity must be finite and strictly positive")
    curve["equity"] = equity.astype(float)
    if curve["date"].max() >= pd.Timestamp("2021-01-01"):
        raise ValueError("equity curve crosses locked boundary")
    returns = curve["equity"].pct_change(fill_method=None)
    if returns.dropna().le(-1.0).any() or not np.isfinite(returns.dropna()).all():
        raise ValueError("equity returns are invalid")
    curve["return"] = returns.fillna(0.0)
    return curve


def yearly_returns(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Return within-year first-to-last equity changes."""

    curve = _validated_curve(equity_curve)
    rows = []
    for year, group in curve.groupby(curve["date"].dt.year):
        rows.append(
            {
                "year": int(year),
                "return": float(group["equity"].iloc[-1] / group["equity"].iloc[0] - 1.0),
            }
        )
    return pd.DataFrame(rows)


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"metric {name} is non-finite")
    return result


def compute_portfolio_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, float]:
    """Compute portfolio and trade metrics without silently coercing failures."""

    curve = _validated_curve(equity_curve)
    returns = curve["return"].iloc[1:]
    total_return = float(curve["equity"].iloc[-1] / curve["equity"].iloc[0] - 1.0)
    elapsed_days = max(int((curve["date"].iloc[-1] - curve["date"].iloc[0]).days), 1)
    years = elapsed_days / 365.2425
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0)
    volatility = float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(returns) > 1 else 0.0
    mean_return = float(returns.mean()) if len(returns) else 0.0
    sharpe = float(mean_return / returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0
    negative = returns.loc[returns < 0]
    downside_deviation = float(np.sqrt((negative.pow(2)).mean()) * np.sqrt(TRADING_DAYS)) if not negative.empty else 0.0
    sortino = float(mean_return * TRADING_DAYS / downside_deviation) if downside_deviation > 0 else 0.0
    drawdowns = curve["equity"].div(curve["equity"].cummax()).sub(1.0)
    max_drawdown = float(drawdowns.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    tail_count = max(1, int(math.ceil(max(len(returns), 1) * 0.05)))
    expected_shortfall = float(returns.nsmallest(tail_count).mean()) if len(returns) else 0.0
    worst_day = float(returns.min()) if len(returns) else 0.0
    indexed = curve.set_index("date")["equity"]
    monthly = indexed.resample("ME").last().pct_change(fill_method=None).dropna()
    worst_month = float(monthly.min()) if not monthly.empty else 0.0
    turnover = float(pd.to_numeric(curve.get("turnover", 0.0), errors="coerce").sum())
    average_exposure = float(pd.to_numeric(curve.get("gross_exposure", 0.0), errors="coerce").mean())
    total_costs = float(pd.to_numeric(curve.get("costs", 0.0), errors="coerce").sum())

    closed = trades.copy()
    trade_returns = pd.to_numeric(
        closed.get("net_return", closed.get("gross_return", pd.Series(dtype=float))),
        errors="coerce",
    ).dropna()
    gains = trade_returns.loc[trade_returns > 0]
    losses = trade_returns.loc[trade_returns < 0]
    gross_profit = float(gains.sum())
    gross_loss = float(-losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit / 1e-12 if gross_profit > 0 else 0.0)
    durations = pd.Series(dtype=float)
    if {"entry_date", "exit_date"} <= set(closed.columns) and not closed.empty:
        durations = (
            pd.to_datetime(closed["exit_date"], errors="raise")
            - pd.to_datetime(closed["entry_date"], errors="raise")
        ).dt.days.astype(float)
        if durations.lt(0).any():
            raise ValueError("trade duration cannot be negative")
    profit_concentration = float(gains.nlargest(min(5, len(gains))).sum() / gross_profit) if gross_profit > 0 else 0.0
    capital_days = float((curve["gross_exposure"] if "gross_exposure" in curve else 0.0).sum())
    return_per_capital_day = total_return / capital_days if capital_days > 0 else 0.0
    gross_trade_profit_money = float(
        pd.to_numeric(closed.get("exit_notional", 0.0), errors="coerce").sum()
        - pd.to_numeric(closed.get("entry_notional", 0.0), errors="coerce").sum()
    )
    cost_pct_gross_profit = total_costs / gross_trade_profit_money if gross_trade_profit_money > 0 else 0.0

    values = {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_return": mean_return * TRADING_DAYS,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "expected_shortfall_5": expected_shortfall,
        "worst_day": worst_day,
        "worst_month": worst_month,
        "turnover": turnover,
        "average_exposure": average_exposure,
        "return_per_capital_day": return_per_capital_day,
        "average_days_invested": float(durations.mean()) if not durations.empty else 0.0,
        "median_days_invested": float(durations.median()) if not durations.empty else 0.0,
        "trades": float(len(trade_returns)),
        "win_rate": float((trade_returns > 0).mean()) if len(trade_returns) else 0.0,
        "average_gain": float(gains.mean()) if not gains.empty else 0.0,
        "average_loss": float(losses.mean()) if not losses.empty else 0.0,
        "profit_factor": profit_factor,
        "profit_concentration_top5": profit_concentration,
        "total_costs": total_costs,
        "cost_pct_gross_profit": cost_pct_gross_profit,
    }
    return {name: _finite(value, name) for name, value in values.items()}


def compute_metrics(
    returns: pd.Series,
    trades: pd.DataFrame,
    costs_bps: int = 0,
) -> dict[str, float]:
    """Compatibility wrapper; scientific protocol uses compute_portfolio_metrics."""

    values = pd.to_numeric(returns, errors="raise").astype(float)
    if values.empty:
        return {
            "cagr": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "return_per_capital_day": 0.0,
        }
    if not np.isfinite(values).all() or values.le(-1.0).any():
        raise ValueError("returns must be finite and greater than -100%")
    net = values - float(costs_bps) / 10_000.0
    dates = pd.bdate_range("2000-01-03", periods=len(net) + 1)
    equity = pd.Series([1.0, *((1.0 + net).cumprod().tolist())])
    curve = pd.DataFrame(
        {
            "date": dates,
            "equity": equity,
            "gross_exposure": [0.0] + [1.0] * len(net),
            "turnover": [0.0] * (len(net) + 1),
            "costs": [0.0] * (len(net) + 1),
        }
    )
    metrics = compute_portfolio_metrics(curve, trades)
    metrics["costs_bps"] = float(costs_bps)
    return metrics
