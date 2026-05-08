"""Crypto perpetual + dated futures basis trader.

Computes annualised cash-and-carry yield from the spread between perpetual
funding-implied price and a dated futures contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CryptoBasisConfig:
    """Settings for the basis trader.

    Attributes:
        symbols: crypto base symbols (BTC, ETH, ...).
        seed: mock seed.
        funding_rate_8h: typical 8-hour funding rate (decimal) for perp.
        days_to_dated_expiry: days until the dated future expires.
    """
    symbols: tuple[str, ...] = ("BTC", "ETH", "SOL")
    seed: int = 29
    funding_rate_8h: float = 0.0001
    days_to_dated_expiry: int = 30


class CryptoBasisTrader:
    """Mock perp + dated price feed and basis analytics."""

    _COLS = ("symbol", "spot", "perp", "dated", "days_to_expiry",
             "funding_rate_8h")

    def __init__(self, config: Optional[CryptoBasisConfig] = None) -> None:
        self.config = config or CryptoBasisConfig()

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        if not mock:
            raise NotImplementedError("Live crypto feed not configured.")
        return self._mock_quotes()

    def signals(self, quotes: pd.DataFrame) -> pd.DataFrame:
        """Annualised cash-and-carry yields + funding annualised."""
        if quotes.empty:
            return pd.DataFrame(columns=["symbol", "dated_carry_apy",
                                         "perp_funding_apy",
                                         "basis_signal"])
        rows = []
        for _, r in quotes.iterrows():
            spot = float(r["spot"])
            dated = float(r["dated"])
            dte = max(int(r["days_to_expiry"]), 1)
            fund_8h = float(r["funding_rate_8h"])
            # Dated carry: ((F/S) - 1) annualised on a 365-day basis.
            dated_carry = (dated / spot - 1.0) * (365.0 / dte) if spot > 0 else 0.0
            # Perp funding: 3 fundings/day -> 1095/year.
            perp_carry = fund_8h * 3 * 365
            # Signal: long basis (sell future, buy spot) if carry > 5% APY.
            signal = 1 if dated_carry > 0.05 else (-1 if dated_carry < -0.05 else 0)
            rows.append({"symbol": r["symbol"],
                         "dated_carry_apy": float(dated_carry),
                         "perp_funding_apy": float(perp_carry),
                         "basis_signal": signal})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_quotes(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        rows = []
        bases = {"BTC": 65000.0, "ETH": 3500.0, "SOL": 165.0}
        for sym in self.config.symbols:
            spot = bases.get(sym, 1000.0)
            # Dated typically trades at small premium in bullish environments.
            dated = spot * (1 + rng.normal(0.01, 0.005))
            perp = spot * (1 + rng.normal(0.0005, 0.0002))
            rows.append({
                "symbol": sym,
                "spot": float(spot),
                "perp": float(perp),
                "dated": float(dated),
                "days_to_expiry": self.config.days_to_dated_expiry,
                "funding_rate_8h": self.config.funding_rate_8h,
            })
        return pd.DataFrame(rows, columns=list(self._COLS))
