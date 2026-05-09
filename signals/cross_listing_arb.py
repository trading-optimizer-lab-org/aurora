"""Cross-listing arbitrage signal: same security, two exchanges.

E.g. ASML on AEX (EUR) vs ASML on NASDAQ (USD). Convert to common currency,
compute spread = price_a / fx - price_b. Z-score the spread; entry when
|z| > entry_z; exit when |z| < exit_z. Convergence trade: if a is rich
(z>0), short a + long b. Per-leg weights in {-0.5, 0, +0.5}.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CrossListingArbConfig:
    """Config."""
    lookback: int = 60
    entry_z: float = 2.0
    exit_z: float = 0.5
    fx_inverse: bool = False  # if True, divide instead of multiply by fx


class CrossListingArbSignal:
    """Convergence trade between same-security listings on two exchanges."""

    def __init__(self, config: CrossListingArbConfig | None = None):
        self.config = config or CrossListingArbConfig()
        if self.config.lookback < 5:
            raise ValueError("lookback >= 5 required")
        if self.config.entry_z <= 0 or self.config.exit_z < 0:
            raise ValueError("invalid z thresholds")
        if self.config.exit_z >= self.config.entry_z:
            self.config.exit_z = self.config.entry_z * 0.99

    def signals(
        self,
        price_a: pd.Series,
        price_b: pd.Series,
        fx: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """Compute per-leg signals.

        Args:
            price_a: listing A series.
            price_b: listing B series.
            fx: optional currency conversion (apply to price_a). If None, treat as 1.

        Returns:
            DataFrame with columns ['leg_a', 'leg_b'], values in {-0.5, 0, +0.5}.
        """
        if not isinstance(price_a, pd.Series) or not isinstance(price_b, pd.Series):
            raise TypeError("price_a/b must be pd.Series")
        idx = price_a.index.intersection(price_b.index)
        if fx is not None:
            idx = idx.intersection(fx.index)
        if len(idx) < self.config.lookback + 2:
            raise ValueError("insufficient overlap")
        pa = price_a.reindex(idx).astype(float).ffill().values
        pb = price_b.reindex(idx).astype(float).ffill().values
        if fx is None:
            fx_v: np.ndarray = np.ones(len(idx), dtype=float)
        else:
            fx_v = fx.reindex(idx).astype(float).ffill().values
        if self.config.fx_inverse:
            pa_eq = pa / fx_v
        else:
            pa_eq = pa * fx_v
        spread = pa_eq - pb
        s = pd.Series(spread, index=idx)
        L = self.config.lookback
        mu = s.rolling(L, min_periods=L).mean()
        sd = s.rolling(L, min_periods=L).std(ddof=0)
        z = (s - mu) / sd.replace(0.0, np.nan)
        out = pd.DataFrame(0.0, index=idx, columns=["leg_a", "leg_b"])
        cur = 0.0
        ez = self.config.entry_z
        xz = self.config.exit_z
        for i, (ts, zi) in enumerate(z.items()):
            if not np.isfinite(zi):
                cur = 0.0
                continue
            if cur == 0.0:
                if zi > ez:
                    cur = -1.0  # a rich -> short a, long b
                elif zi < -ez:
                    cur = 1.0
            else:
                if abs(zi) < xz:
                    cur = 0.0
            out.iat[i, 0] = cur * 0.5
            out.iat[i, 1] = -cur * 0.5
        return out
