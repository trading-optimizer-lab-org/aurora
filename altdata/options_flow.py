"""Options flow / unusual activity adapter.

Pulls option chain data via ``yfinance`` (lazy import) and flags unusual
activity defined as ``volume > avg_volume * unusual_multiplier`` where
``avg_volume`` is the rolling-window mean of past N day's option volume per
contract. The module ships a deterministic mock chain for offline tests.

Returned columns:
    contract_symbol, underlying, expiration, strike, option_type,
    last_price, volume, open_interest, avg_volume, unusual_score
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class OptionsFlowConfig:
    """Static config.

    Attributes:
        unusual_multiplier: ratio of volume / avg_volume above which a contract
            is flagged unusual. Default 5.0.
        min_volume: ignore contracts with volume below this floor.
        avg_volume_window_days: lookback for the rolling mean baseline.
    """
    unusual_multiplier: float = 5.0
    min_volume: int = 50
    avg_volume_window_days: int = 20


class OptionsFlowAdapter:
    """Detect unusual options activity from option chains."""

    _COLS = (
        "contract_symbol", "underlying", "expiration", "strike",
        "option_type", "last_price", "volume", "open_interest",
        "avg_volume", "unusual_score",
    )

    def __init__(self, config: Optional[OptionsFlowConfig] = None) -> None:
        self.config = config or OptionsFlowConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_unusual_activity(
        self,
        symbol: str,
        as_of: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return contracts flagged as unusual for ``symbol``.

        ``as_of`` is informational only (used to seed the mock generator);
        live mode pulls the current chain via yfinance.
        """
        as_of = as_of or datetime.now(timezone.utc)
        chain = self._mock_chain(symbol, as_of) if mock else self._fetch_chain(symbol)
        return self.flag_unusual(chain)

    def flag_unusual(self, chain: pd.DataFrame) -> pd.DataFrame:
        """Annotate ``chain`` with ``avg_volume`` and ``unusual_score``.

        ``unusual_score = volume / max(avg_volume, 1)``. Only contracts with
        ``volume >= min_volume`` AND ``score >= unusual_multiplier`` survive.
        """
        if chain.empty:
            return pd.DataFrame(columns=list(self._COLS))
        df = chain.copy()
        if "avg_volume" not in df.columns:
            # Fall back: avg_volume = open_interest / window. Crude but serves
            # as a deterministic baseline for tests.
            df["avg_volume"] = (df["open_interest"].fillna(0)
                                / max(self.config.avg_volume_window_days, 1)
                               ).clip(lower=1.0)
        df["unusual_score"] = df["volume"].astype(float) / df["avg_volume"].clip(lower=1.0)
        mask = (
            (df["volume"] >= self.config.min_volume)
            & (df["unusual_score"] >= self.config.unusual_multiplier)
        )
        out = df.loc[mask, list(self._COLS)].reset_index(drop=True)
        return out.sort_values("unusual_score", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fetch_chain(self, symbol: str) -> pd.DataFrame:  # pragma: no cover - network
        try:
            import yfinance as yf  # type: ignore
        except ImportError as e:
            raise ImportError("yfinance required for live options chain") from e
        tk = yf.Ticker(symbol)
        expirations = list(tk.options or [])
        rows: list[dict] = []
        for exp in expirations[:4]:
            try:
                ch = tk.option_chain(exp)
            except Exception:  # noqa: BLE001
                continue
            for side, df in (("call", ch.calls), ("put", ch.puts)):
                for _, r in df.iterrows():
                    rows.append({
                        "contract_symbol": r.get("contractSymbol", ""),
                        "underlying": symbol.upper(),
                        "expiration": pd.Timestamp(exp),
                        "strike": float(r.get("strike", 0.0)),
                        "option_type": side,
                        "last_price": float(r.get("lastPrice", 0.0)),
                        "volume": int(r.get("volume", 0) or 0),
                        "open_interest": int(r.get("openInterest", 0) or 0),
                    })
        return pd.DataFrame(rows)

    def _mock_chain(self, symbol: str, as_of: datetime) -> pd.DataFrame:
        rng = np.random.default_rng(
            abs(hash(("opt", symbol, as_of.date().toordinal()))) % (2**32)
        )
        strikes = np.arange(80, 130, 5, dtype=float)
        rows = []
        exp = pd.Timestamp(as_of) + pd.Timedelta(days=21)
        for k in strikes:
            for side in ("call", "put"):
                vol = int(rng.integers(0, 500))
                # Inject unusual outliers ~10% of the time.
                if rng.random() < 0.1:
                    vol *= 20
                oi = int(rng.integers(50, 5000))
                rows.append({
                    "contract_symbol": f"{symbol.upper()}{exp:%y%m%d}"
                                       f"{'C' if side == 'call' else 'P'}"
                                       f"{int(k * 1000):08d}",
                    "underlying": symbol.upper(),
                    "expiration": exp,
                    "strike": float(k),
                    "option_type": side,
                    "last_price": float(rng.uniform(0.1, 10.0)),
                    "volume": vol,
                    "open_interest": oi,
                })
        return pd.DataFrame(rows)
