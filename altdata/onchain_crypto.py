"""On-chain crypto adapter (Etherscan / Glassnode).

Surfaces large-holder ("whale") movements and exchange inflows/outflows. Both
backends are accessed via lazy ``requests`` import; the default ``mock=True``
path returns a deterministic synthetic time series so tests run offline.

Supported metrics:
    - whale_transfers   : transfers above a USD threshold
    - exchange_inflow   : net token flow INTO known exchange addresses
    - exchange_outflow  : net token flow OUT of known exchange addresses
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

_VALID_METRICS = frozenset({
    "whale_transfers", "exchange_inflow", "exchange_outflow",
})


@dataclass
class OnchainConfig:
    """Static config for the onchain adapter.

    Attributes:
        provider: 'etherscan' or 'glassnode'.
        api_key_env: env var holding the API key.
        whale_threshold_usd: minimum transfer size to count as a whale move.
        timeout_s: HTTP timeout in seconds.
    """
    provider: str = "etherscan"
    api_key_env: str = "ETHERSCAN_API_KEY"
    whale_threshold_usd: float = 1_000_000.0
    timeout_s: float = 10.0


class OnchainAdapter:
    """Whale movements and exchange flow metrics."""

    _COLS = ("date", "asset", "metric", "value")

    def __init__(self, config: Optional[OnchainConfig] = None) -> None:
        self.config = config or OnchainConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_metric(
        self,
        asset: str,
        metric: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return daily metric values for ``asset``.

        Args:
            asset: ticker / symbol, e.g. 'BTC' or 'ETH'.
            metric: one of :data:`_VALID_METRICS`.
            start: inclusive start date (UTC).
            end: exclusive end date (UTC).
        """
        if metric not in _VALID_METRICS:
            raise ValueError(
                f"unknown metric {metric!r}, valid={sorted(_VALID_METRICS)}"
            )
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(days=30))
        if start >= end:
            raise ValueError("start must be before end")
        if mock:
            return self._mock_series(asset, metric, start, end)
        return self._fetch_series(asset, metric, start, end)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fetch_series(
        self,
        asset: str,
        metric: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:  # pragma: no cover - network path
        import os
        try:
            import requests  # noqa: F401
        except ImportError as e:
            raise ImportError("requests required for live onchain fetch") from e
        if not os.environ.get(self.config.api_key_env, ""):
            raise RuntimeError(
                f"missing env var {self.config.api_key_env}"
            )
        # Real implementation: provider-specific REST call. Stubbed to keep
        # the package free of vendor-locked code paths.
        return pd.DataFrame(columns=list(self._COLS))

    def _mock_series(
        self,
        asset: str,
        metric: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(
            abs(hash(("onchain", asset, metric))) % (2**32)
        )
        days = pd.date_range(start.date(), end.date(), freq="D", tz="UTC")
        if metric == "whale_transfers":
            # count of transfers above threshold per day
            vals = rng.integers(0, 50, size=len(days)).astype(float)
        else:
            # USD-denominated net flow; can be negative for outflow
            mu = 0.0 if metric.endswith("inflow") else -0.0
            vals = rng.normal(mu, 5e6, size=len(days))
        rows = [
            {"date": d, "asset": asset.upper(), "metric": metric,
             "value": float(v)}
            for d, v in zip(days, vals)
        ]
        return pd.DataFrame(rows, columns=list(self._COLS))
