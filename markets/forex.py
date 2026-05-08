"""Forex universe adapter.

Builds a universe of FX majors + crosses with pip / spread metadata. Provides
a deterministic mock OHLC generator and a simple pip-based signals method.

Pair convention: ``BASE/QUOTE``. Pip size is 0.0001 except for JPY pairs
(0.01).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# 7 USD majors + sample crosses (28 entries in spec is loose; real majors are
# 7 USD pairs and crosses are derived combinations).
_USD_MAJORS = (
    "EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
)
_CROSSES = (
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD", "EUR/NZD",
    "GBP/CHF", "GBP/AUD", "GBP/CAD", "GBP/NZD",
    "AUD/JPY", "AUD/CHF", "AUD/CAD", "AUD/NZD",
    "CAD/JPY", "CHF/JPY", "NZD/JPY",
    "CAD/CHF", "NZD/CHF", "NZD/CAD",
)


@dataclass
class ForexConfig:
    """Universe + spread settings.

    Attributes:
        include_crosses: include non-USD crosses.
        spread_pips_default: typical bid/ask spread in pips for liquid majors.
        mock_days: bars to generate in mock OHLC.
    """
    include_crosses: bool = True
    spread_pips_default: float = 1.0
    mock_days: int = 90
    pairs_override: Optional[tuple[str, ...]] = None
    seed: int = 7


class ForexUniverse:
    """FX universe with pip + spread handling."""

    _OHLC_COLS = ("date", "pair", "open", "high", "low", "close", "spread_pips")

    def __init__(self, config: Optional[ForexConfig] = None) -> None:
        self.config = config or ForexConfig()

    def pairs(self) -> list[str]:
        if self.config.pairs_override:
            return list(self.config.pairs_override)
        out = list(_USD_MAJORS)
        if self.config.include_crosses:
            out.extend(_CROSSES)
        return out

    @staticmethod
    def pip_size(pair: str) -> float:
        """Pip size for a pair: 0.01 if quote is JPY, 0.0001 otherwise."""
        if "/" not in pair:
            return 0.0001
        return 0.01 if pair.split("/")[1].upper() == "JPY" else 0.0001

    def spread_value(self, pair: str, pips: Optional[float] = None) -> float:
        """Convert a spread in pips to price units for ``pair``."""
        p = pips if pips is not None else self.config.spread_pips_default
        return p * self.pip_size(pair)

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        """Return per-pair OHLC mock and spread/pip metadata."""
        if not mock:
            raise NotImplementedError("Live FX feed not configured.")
        return self._mock_ohlc()

    def signals(self, ohlc: pd.DataFrame) -> pd.DataFrame:
        """Simple breakout signal: close - 20bar mean / pip_size in pips.

        Returns columns: pair, momentum_pips, signal in {-1, 0, 1}.
        """
        if ohlc.empty:
            return pd.DataFrame(columns=["pair", "momentum_pips", "signal"])
        out_rows = []
        for pair, grp in ohlc.groupby("pair"):
            g = grp.sort_values("date")
            if len(g) < 20:
                continue
            mean20 = g["close"].rolling(20).mean().iloc[-1]
            last = g["close"].iloc[-1]
            mom = (last - mean20) / self.pip_size(pair)
            sig = int(np.sign(mom)) if abs(mom) > 5 else 0
            out_rows.append({"pair": pair, "momentum_pips": float(mom),
                             "signal": sig})
        return pd.DataFrame(out_rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_ohlc(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        dates = pd.date_range("2024-01-01", periods=self.config.mock_days,
                              freq="B")
        rows: list[dict] = []
        for pair in self.pairs():
            base_price = 110.0 if pair.endswith("JPY") else 1.10
            drift = rng.normal(0, 0.0005, size=len(dates)).cumsum()
            close = base_price * (1 + drift)
            high = close * (1 + np.abs(rng.normal(0, 0.0008, len(dates))))
            low = close * (1 - np.abs(rng.normal(0, 0.0008, len(dates))))
            open_ = np.concatenate([[close[0]], close[:-1]])
            for i, d in enumerate(dates):
                rows.append({
                    "date": d, "pair": pair,
                    "open": float(open_[i]), "high": float(high[i]),
                    "low": float(low[i]), "close": float(close[i]),
                    "spread_pips": self.config.spread_pips_default,
                })
        return pd.DataFrame(rows, columns=list(self._OHLC_COLS))
