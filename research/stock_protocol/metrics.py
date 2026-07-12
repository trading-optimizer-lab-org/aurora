"""Common metrics for compact protocol results."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_metrics(returns: pd.Series, trades: pd.DataFrame, costs_bps: int = 0) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if values.empty:
        return {"cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0, "calmar": 0.0, "profit_factor": 0.0, "win_rate": 0.0, "return_per_capital_day": 0.0}
    net = values - (float(costs_bps) / 10000.0)
    equity = (1.0 + net).cumprod()
    years = max(len(net) / 252.0, 1.0 / 252.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    sd = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    downside = net.clip(upper=0.0)
    downside_sd = float(np.sqrt((downside**2).mean()))
    sharpe = float(np.sqrt(252.0) * net.mean() / sd) if sd > 1e-12 else 0.0
    sortino = float(np.sqrt(252.0) * net.mean() / downside_sd) if downside_sd > 1e-12 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0
    gross_profit = float(net[net > 0].sum())
    gross_loss = float(-net[net < 0].sum())
    trade_returns = pd.to_numeric(trades.get("gross_return", pd.Series(dtype=float)), errors="coerce").dropna() if not trades.empty else pd.Series(dtype=float)
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else 0.0,
        "win_rate": float((trade_returns > 0).mean()) if not trade_returns.empty else 0.0,
        "return_per_capital_day": float(net.sum() / max(len(net), 1)),
        "trades": float(len(trade_returns)),
        "costs_bps": float(costs_bps),
    }

