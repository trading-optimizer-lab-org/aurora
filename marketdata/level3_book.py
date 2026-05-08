"""Level 3 limit order book with order IDs and queue position.

Maintains the full book at the order level (not just aggregated by price).
Supports add / cancel / match operations and exposes the top-of-book and
queue position for any live order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Level3Order:
    """A single resting order on the book."""
    order_id: str
    side: str  # "bid" or "ask"
    price: float
    size: int
    timestamp: float = 0.0


@dataclass
class Level3Config:
    """Static config.

    Attributes:
        max_levels: cap on price levels per side returned by ``snapshot``.
        tick_size: minimum price increment used for normalization.
    """
    max_levels: int = 10
    tick_size: float = 0.01


class Level3OrderBook:
    """Full L3 book keyed by order ID with FIFO queues per price level."""

    def __init__(self, symbol: str, config: Optional[Level3Config] = None) -> None:
        self.symbol = symbol.upper()
        self.config = config or Level3Config()
        # Order ID lookup: order_id -> Level3Order.
        self._orders: dict[str, Level3Order] = {}
        # Per-price FIFO queues (list of order_ids in arrival order).
        self._bid_levels: dict[float, list[str]] = {}
        self._ask_levels: dict[float, list[str]] = {}
        # Trade tape produced by ``match``.
        self._tape: list[dict] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def add(self, order: Level3Order) -> None:
        """Insert a new order at the back of its price-level FIFO."""
        if order.order_id in self._orders:
            raise ValueError(f"duplicate order_id {order.order_id}")
        if order.side not in ("bid", "ask"):
            raise ValueError("side must be 'bid' or 'ask'")
        levels = self._bid_levels if order.side == "bid" else self._ask_levels
        price = self._normalize_price(order.price)
        levels.setdefault(price, []).append(order.order_id)
        self._orders[order.order_id] = order

    def cancel(self, order_id: str) -> Optional[Level3Order]:
        """Remove order by id; returns the order or None if missing."""
        order = self._orders.pop(order_id, None)
        if order is None:
            return None
        levels = self._bid_levels if order.side == "bid" else self._ask_levels
        price = self._normalize_price(order.price)
        queue = levels.get(price)
        if queue and order_id in queue:
            queue.remove(order_id)
            if not queue:
                del levels[price]
        return order

    def match(self, side: str, size: int) -> list[dict]:
        """Aggressor takes liquidity from the opposite side.

        Returns a list of fill dicts: ``{order_id, price, size}``. Fills are
        produced in price-priority then time-priority order.
        """
        if side not in ("bid", "ask"):
            raise ValueError("side must be 'bid' or 'ask'")
        if size <= 0:
            return []
        opposite = self._ask_levels if side == "bid" else self._bid_levels
        # Buy aggressor sweeps lowest asks first; sell aggressor sweeps
        # highest bids first.
        prices = sorted(opposite.keys(), reverse=(side == "ask"))
        remaining = int(size)
        fills: list[dict] = []
        for price in prices:
            if remaining <= 0:
                break
            queue = opposite.get(price, [])
            while queue and remaining > 0:
                resting_id = queue[0]
                resting = self._orders[resting_id]
                fill_size = min(resting.size, remaining)
                fills.append({
                    "order_id": resting_id,
                    "price": resting.price,
                    "size": int(fill_size),
                })
                remaining -= fill_size
                resting.size -= fill_size
                if resting.size <= 0:
                    queue.pop(0)
                    self._orders.pop(resting_id, None)
            if not queue:
                opposite.pop(price, None)
        self._tape.extend(fills)
        return fills

    def queue_position(self, order_id: str) -> Optional[int]:
        """Return zero-indexed FIFO position; None if order not on book."""
        order = self._orders.get(order_id)
        if order is None:
            return None
        levels = self._bid_levels if order.side == "bid" else self._ask_levels
        queue = levels.get(self._normalize_price(order.price), [])
        try:
            return queue.index(order_id)
        except ValueError:
            return None

    def best_bid(self) -> Optional[tuple[float, int]]:
        """``(price, total_size)`` at best bid; None if empty."""
        if not self._bid_levels:
            return None
        price = max(self._bid_levels.keys())
        total = sum(self._orders[oid].size for oid in self._bid_levels[price])
        return (price, int(total))

    def best_ask(self) -> Optional[tuple[float, int]]:
        """``(price, total_size)`` at best ask; None if empty."""
        if not self._ask_levels:
            return None
        price = min(self._ask_levels.keys())
        total = sum(self._orders[oid].size for oid in self._ask_levels[price])
        return (price, int(total))

    def snapshot(self) -> dict:
        """Aggregated top-N levels per side plus tape length."""
        bids = sorted(self._bid_levels.keys(), reverse=True)[: self.config.max_levels]
        asks = sorted(self._ask_levels.keys())[: self.config.max_levels]
        bid_levels = [
            (p, sum(self._orders[o].size for o in self._bid_levels[p])) for p in bids
        ]
        ask_levels = [
            (p, sum(self._orders[o].size for o in self._ask_levels[p])) for p in asks
        ]
        return {
            "symbol": self.symbol,
            "bids": bid_levels,
            "asks": ask_levels,
            "n_orders": len(self._orders),
            "n_trades": len(self._tape),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _normalize_price(self, price: float) -> float:
        ts = self.config.tick_size
        if ts <= 0:
            return float(price)
        return round(round(price / ts) * ts, 8)
