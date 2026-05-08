"""Lit vs dark execution-quality analyzer.

Compares price improvement, effective spread, realized spread, and fill size
distribution between lit (exchange) prints and dark (off-exchange) prints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


_DEFAULT_DARK_CODES = ("D", "FINRA", "TRF", "ADF", "Z")


@dataclass
class LitDarkConfig:
    """Static config.

    Attributes:
        dark_codes: tape codes treated as off-exchange.
        realized_spread_lag_seconds: time horizon used to compute realized spread.
    """
    dark_codes: tuple[str, ...] = _DEFAULT_DARK_CODES
    realized_spread_lag_seconds: int = 60


class LitDarkAnalyzer:
    """Compare execution quality across lit vs dark venues."""

    def __init__(self, config: Optional[LitDarkConfig] = None) -> None:
        self.config = config or LitDarkConfig()
        self._dark = frozenset(self.config.dark_codes)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def compare(
        self,
        trades: pd.DataFrame,
        quotes: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Per-venue execution quality summary table.

        Returns a DataFrame indexed by ``venue_type`` with columns:
        ``n_trades, total_volume, avg_size, vwap, effective_spread_bps,
        price_improvement_bps``.
        """
        if trades.empty:
            return pd.DataFrame(columns=[
                "venue_type", "n_trades", "total_volume", "avg_size", "vwap",
                "effective_spread_bps", "price_improvement_bps",
            ])
        df = self._enrich(trades, quotes)
        rows = []
        for venue in ("lit", "dark"):
            sub = df[df["venue_type"] == venue]
            if sub.empty:
                rows.append({
                    "venue_type": venue, "n_trades": 0, "total_volume": 0.0,
                    "avg_size": 0.0, "vwap": float("nan"),
                    "effective_spread_bps": float("nan"),
                    "price_improvement_bps": float("nan"),
                })
                continue
            tot_size = float(sub["size"].sum())
            vwap = float((sub["price"] * sub["size"]).sum() / tot_size) if tot_size else float("nan")
            rows.append({
                "venue_type": venue,
                "n_trades": int(len(sub)),
                "total_volume": tot_size,
                "avg_size": float(sub["size"].mean()),
                "vwap": vwap,
                "effective_spread_bps": float(sub["effective_spread_bps"].mean()),
                "price_improvement_bps": float(sub["price_improvement_bps"].mean()),
            })
        return pd.DataFrame(rows)

    def routing_summary(
        self,
        trades: pd.DataFrame,
        quotes: Optional[pd.DataFrame] = None,
    ) -> dict:
        """One-line preference signal: which venue gave better execution."""
        cmp_df = self.compare(trades, quotes)
        if cmp_df.empty or len(cmp_df) < 2:
            return {"preferred": None, "lit_quality": float("nan"),
                    "dark_quality": float("nan")}
        lit_q = cmp_df.loc[cmp_df["venue_type"] == "lit",
                           "effective_spread_bps"].iloc[0]
        dark_q = cmp_df.loc[cmp_df["venue_type"] == "dark",
                            "effective_spread_bps"].iloc[0]
        # Lower effective spread = better execution. NaN treated as worst.
        if np.isnan(lit_q) and np.isnan(dark_q):
            preferred = None
        elif np.isnan(lit_q):
            preferred = "dark"
        elif np.isnan(dark_q):
            preferred = "lit"
        else:
            preferred = "dark" if dark_q < lit_q else "lit"
        return {
            "preferred": preferred,
            "lit_quality": float(lit_q),
            "dark_quality": float(dark_q),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _enrich(
        self, trades: pd.DataFrame, quotes: Optional[pd.DataFrame],
    ) -> pd.DataFrame:
        df = trades.copy()
        if "exchange" not in df.columns:
            df["exchange"] = ""
        df["venue_type"] = np.where(
            df["exchange"].astype(str).isin(self._dark), "dark", "lit",
        )
        # Compute midpoint at trade time using as-of merge.
        if quotes is not None and not quotes.empty:
            q = quotes[["timestamp", "bid", "ask"]].sort_values("timestamp").copy()
            q["midpoint"] = (q["bid"] + q["ask"]) / 2.0
            df = df.sort_values("timestamp").reset_index(drop=True)
            merged = pd.merge_asof(
                df, q[["timestamp", "midpoint", "bid", "ask"]],
                on="timestamp", direction="backward",
            )
            df["midpoint"] = merged["midpoint"].ffill()
            df["bid"] = merged["bid"]
            df["ask"] = merged["ask"]
        else:
            df["midpoint"] = df["price"].rolling(5, min_periods=1).mean()
            df["bid"] = df["midpoint"] - 0.01
            df["ask"] = df["midpoint"] + 0.01
        # Effective spread: 2 * |price - midpoint| / midpoint, in basis points.
        with np.errstate(divide="ignore", invalid="ignore"):
            df["effective_spread_bps"] = (
                2.0 * (df["price"] - df["midpoint"]).abs()
                / df["midpoint"].replace(0, np.nan) * 1e4
            ).fillna(0.0)
            # Price improvement: (midpoint - price) / midpoint relative to
            # spread side. Positive = price improvement to the buyer.
            df["price_improvement_bps"] = (
                (df["midpoint"] - df["price"])
                / df["midpoint"].replace(0, np.nan) * 1e4
            ).fillna(0.0)
        return df
