"""Tax-loss harvesting suggester.

Identifies positions whose unrealized loss is past the wash-sale window and
proposes a sell + replacement pair. Wash-sale window defaults to 30 calendar
days (US IRS Rule).

Output is a 1-row DataFrame keyed by suggestion target asset; the value is
the SIGNED suggested trade (negative = sell) in shares, plus a separate
``replacements`` Series mapping sold ticker -> proposed replacement ticker.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TLHConfig:
    """Configuration for :class:`TaxLossHarvester`."""
    wash_sale_days: int = 30
    min_loss_usd: float = 500.0       # ignore tiny losses
    min_loss_pct: float = 0.03        # only flag losses >=3% of cost basis
    replacement_map: dict = field(default_factory=dict)  # ticker -> replacement


@dataclass
class TLHResult:
    """Output of :meth:`TaxLossHarvester.allocate`."""
    weights: pd.DataFrame              # 1-row, columns = sell candidates, value = -shares
    replacements: pd.Series            # ticker -> proposed replacement
    realized_loss: pd.Series           # ticker -> $ loss to realise
    wash_sale_blocked: list            # tickers skipped due to wash-sale window


class TaxLossHarvester:
    """Identify tax-loss harvest candidates.

    Args:
        config: :class:`TLHConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[TLHConfig] = None):
        self.config = config or TLHConfig()
        if self.config.wash_sale_days < 0:
            raise ValueError("wash_sale_days must be >= 0")

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        prices: pd.DataFrame,
        positions: pd.DataFrame,
        recent_buys: Optional[pd.DataFrame] = None,
        as_of: Optional[datetime] = None,
    ) -> TLHResult:
        """Identify TLH candidates and propose replacements.

        Args:
            prices: TxN price DataFrame (last row = current marks).
            positions: DataFrame with at least columns
                ``['ticker', 'shares', 'cost_basis', 'purchase_date']``.
                ``cost_basis`` is per-share, ``purchase_date`` a Timestamp.
            recent_buys: optional DataFrame with columns
                ``['ticker', 'purchase_date']`` for purchases in the wash-sale
                window. If a candidate appears here it is skipped.
            as_of: evaluation date; defaults to ``prices.index[-1]`` or
                ``utcnow``.
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if not isinstance(positions, pd.DataFrame):
            raise TypeError("positions must be a pd.DataFrame")
        required = {"ticker", "shares", "cost_basis", "purchase_date"}
        missing = required - set(positions.columns)
        if missing:
            raise ValueError(f"positions missing columns: {sorted(missing)}")

        if as_of is None:
            try:
                as_of = pd.to_datetime(prices.index[-1])
            except Exception:
                as_of = datetime.utcnow()
        as_of = pd.to_datetime(as_of)
        cutoff = as_of - timedelta(days=self.config.wash_sale_days)

        last_prices = prices.iloc[-1]
        recent_set: set[str] = set()
        if recent_buys is not None and len(recent_buys) > 0:
            mask = pd.to_datetime(recent_buys["purchase_date"]) >= cutoff
            recent_set = set(recent_buys.loc[mask, "ticker"].tolist())

        suggestions: dict[str, float] = {}
        replacements: dict[str, str] = {}
        losses: dict[str, float] = {}
        blocked: list[str] = []

        for _, row in positions.iterrows():
            ticker = row["ticker"]
            shares = float(row["shares"])
            cost = float(row["cost_basis"])
            if shares <= 0 or ticker not in last_prices.index:
                continue
            mark = float(last_prices[ticker])
            unreal = (mark - cost) * shares
            loss_pct = (cost - mark) / cost if cost > 0 else 0.0
            # Loss only if unreal < 0
            if unreal >= 0:
                continue
            if abs(unreal) < self.config.min_loss_usd:
                continue
            if loss_pct < self.config.min_loss_pct:
                continue
            # Wash-sale blocks if (a) the ticker was bought again recently or
            # (b) the original purchase is within the wash-sale window.
            purchase_dt = pd.to_datetime(row["purchase_date"])
            if ticker in recent_set or purchase_dt >= cutoff:
                blocked.append(ticker)
                continue
            suggestions[ticker] = -shares
            replacements[ticker] = self.config.replacement_map.get(
                ticker, ticker  # fall back: no swap, just mark for sell
            )
            losses[ticker] = float(unreal)

        cols = list(suggestions.keys()) or ["__noop__"]
        if "__noop__" in cols:
            data = [[0.0]]
        else:
            data = [[suggestions[c] for c in cols]]
        weights_df = pd.DataFrame(data, index=["tlh"], columns=cols)
        return TLHResult(
            weights=weights_df,
            replacements=pd.Series(replacements, dtype=object),
            realized_loss=pd.Series(losses),
            wash_sale_blocked=blocked,
        )
