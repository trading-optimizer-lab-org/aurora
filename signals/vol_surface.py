"""Implied volatility surface signal.

Source: yfinance options chain (lazy-imported). Computes 25-delta put-call
skew time series. Skew steepening (puts more expensive vs calls) -> risk-off.

Signal mapping:
  - skew above rolling +threshold std -> -1 (risk-off short)
  - skew below rolling -threshold std -> +1 (risk-on long)
  - else -> 0

When yfinance unavailable or chain empty, signals returns an empty/zero
series and `compute_skew_from_chain` accepts a pre-fetched DataFrame for
fully offline testing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import math
import numpy as np
import pandas as pd


@dataclass
class VolSurfaceConfig:
    """Config."""
    rolling_window: int = 60
    z_threshold: float = 1.0
    target_delta: float = 0.25  # 25-delta wings
    min_periods: int = 20


class VolSurfaceSignal:
    """25-delta put-call skew signal driver.

    Public API:
        compute_skew_from_chain(chain_df) -> float (one snapshot)
        signals(skew_series) -> pd.Series of {-1, 0, 1}
        fetch_skew_history(ticker, dates) -> pd.Series  (uses yfinance)
    """

    def __init__(self, config: Optional[VolSurfaceConfig] = None):
        self.config = config or VolSurfaceConfig()

    @staticmethod
    def _bs_call_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Black-Scholes call delta. Used to map IV -> approximate delta."""
        if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
            return 0.0
        from math import log, sqrt
        d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
        # Standard normal CDF approximation
        return 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))

    def compute_skew_from_chain(
        self,
        chain_df: pd.DataFrame,
        spot: float,
        T_years: float,
        r: float = 0.0,
    ) -> float:
        """Compute put-call IV skew at +/- target_delta wings.

        Args:
            chain_df: rows=options. Required cols: strike, impliedVolatility, type ('call'|'put').
            spot: current underlying price.
            T_years: time to expiry in years.
            r: risk-free rate (default 0).

        Returns:
            skew = IV_put_25d - IV_call_25d. NaN if no calibration possible.
        """
        if not isinstance(chain_df, pd.DataFrame) or chain_df.empty:
            return float("nan")
        req = {"strike", "impliedVolatility", "type"}
        if not req.issubset(chain_df.columns):
            return float("nan")
        td = self.config.target_delta

        # Estimate delta for each row using its own IV
        deltas = []
        for _, row in chain_df.iterrows():
            sigma = float(row["impliedVolatility"])
            K = float(row["strike"])
            t = str(row["type"]).lower()
            cd = self._bs_call_delta(spot, K, T_years, r, sigma)
            if t.startswith("p"):
                # put delta = call delta - 1
                d = cd - 1.0
            else:
                d = cd
            deltas.append(d)
        chain = chain_df.copy()
        chain["_delta"] = deltas

        calls = chain[chain["type"].str.lower().str.startswith("c")]
        puts = chain[chain["type"].str.lower().str.startswith("p")]
        if calls.empty or puts.empty:
            return float("nan")
        # Find row closest to +td (calls) and -td (puts)
        ic = (calls["_delta"] - td).abs().idxmin()
        ip = (puts["_delta"] + td).abs().idxmin()
        iv_c = float(calls.loc[ic, "impliedVolatility"])
        iv_p = float(puts.loc[ip, "impliedVolatility"])
        return iv_p - iv_c

    def signals(self, skew: pd.Series) -> pd.Series:
        """Convert skew time series into discrete {-1, 0, +1} signal."""
        if not isinstance(skew, pd.Series):
            raise TypeError("skew must be pd.Series")
        cfg = self.config
        s = skew.astype(float)
        mu = s.rolling(cfg.rolling_window, min_periods=cfg.min_periods).mean()
        sd = s.rolling(cfg.rolling_window, min_periods=cfg.min_periods).std(ddof=0)
        z = (s - mu) / sd.replace(0.0, np.nan)
        out = pd.Series(0, index=s.index, dtype=int)
        out[z > cfg.z_threshold] = -1
        out[z < -cfg.z_threshold] = 1
        return out

    def fetch_skew_history(self, ticker: str, dates: pd.DatetimeIndex) -> pd.Series:
        """Fetch skew using yfinance. Lazy import + soft-fail.

        Returns NaN-filled series if yfinance unavailable or no chain.
        Use compute_skew_from_chain directly for offline tests.
        """
        try:
            import yfinance as yf
        except ImportError:
            return pd.Series(np.nan, index=dates)
        try:
            tk = yf.Ticker(ticker)
            expiries = list(tk.options)
            if not expiries:
                return pd.Series(np.nan, index=dates)
            exp = expiries[0]
            chain = tk.option_chain(exp)
            calls = chain.calls.assign(type="call")
            puts = chain.puts.assign(type="put")
            df = pd.concat([calls, puts], ignore_index=True)
            spot = float(tk.history(period="1d")["Close"].iloc[-1])
            T_years = max((pd.Timestamp(exp) - pd.Timestamp.now()).days / 365.0, 1.0 / 365)
            sk = self.compute_skew_from_chain(df, spot, T_years)
            return pd.Series(sk, index=dates)
        except Exception:
            return pd.Series(np.nan, index=dates)
