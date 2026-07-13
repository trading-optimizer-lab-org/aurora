"""Long-only portfolio sizing and exposure constraints."""

from __future__ import annotations

import pandas as pd


def build_portfolio(trades: pd.DataFrame, portfolio_rule: dict[str, object]) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    result = trades.copy()
    sizing = str(portfolio_rule.get("sizing", "equal"))
    if sizing == "inverse_vol" and "volatility" in result:
        inv = 1.0 / result["volatility"].clip(lower=1e-8)
        result["weight"] = inv / inv.groupby(result["entry_date"]).transform("sum")
    else:
        result["weight"] = result.groupby("entry_date")["symbol"].transform(lambda x: 1.0 / len(x))
    cap = portfolio_rule.get("asset_cap")
    if isinstance(cap, str) and cap.strip().lower() in {"", "none", "null"}:
        cap = None
    if cap is not None:
        result["weight"] = result["weight"].clip(upper=float(cap))
    return result
