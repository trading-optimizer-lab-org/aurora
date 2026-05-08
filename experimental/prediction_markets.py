"""Polymarket adapter — pull prediction-market odds as alt signal.

The actual HTTP client (``requests``) is a lazy import. By default the
adapter runs in mock mode and returns deterministic synthetic odds, so
tests are offline.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Optional


def _mock_fetch(market_id: str) -> dict:
    """Return deterministic mock odds for ``market_id``."""
    h = hashlib.sha256(market_id.encode("utf-8")).hexdigest()
    yes = (int(h[:6], 16) % 9001) / 10000.0  # in [0.0, 0.9001]
    yes = max(0.01, min(0.99, yes))
    return {"yes": yes, "no": 1.0 - yes}


@dataclass
class PolymarketAdapter:
    """Pull Polymarket odds as an alternative signal.

    Parameters
    ----------
    mock : bool
        If True (default), use the deterministic mock fetcher and never
        hit the network.
    fetcher : Callable[[str], dict], optional
        Override fetcher for tests. Takes a market id, returns a dict
        with ``yes`` and ``no`` floats in [0, 1].
    """

    mock: bool = True
    fetcher: Optional[Callable[[str], dict]] = None

    def __post_init__(self) -> None:
        if self.fetcher is None:
            if self.mock:
                self.fetcher = _mock_fetch
            else:  # pragma: no cover - real network path
                self.fetcher = self._live_fetch

    def _live_fetch(self, market_id: str) -> dict:  # pragma: no cover
        import requests  # type: ignore

        url = f"https://clob.polymarket.com/markets/{market_id}"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        yes = float(data.get("yes_price", 0.5))
        return {"yes": yes, "no": 1.0 - yes}

    def odds(self, market_id: str) -> dict:
        """Return current odds and a derived signal."""
        if not market_id:
            raise ValueError("market_id is required")
        raw = self.fetcher(market_id)  # type: ignore[misc]
        yes = float(raw.get("yes", 0.5))
        yes = max(0.0, min(1.0, yes))
        signal = 2.0 * yes - 1.0  # map [0,1] -> [-1, 1]
        return {
            "market_id": market_id,
            "yes": yes,
            "no": 1.0 - yes,
            "signal": signal,
        }
