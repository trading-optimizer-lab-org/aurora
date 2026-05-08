"""Pegged order types: mid-peg, primary peg, market peg.

Pegged orders track a reference price (mid, primary, opposite-side) and
re-price as the reference moves, optionally with an offset. This module
computes the live limit price and a re-price decision given a stream
of (bid, ask) quotes.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PeggedQuote:
    """A best-bid / best-ask snapshot."""
    bid: float
    ask: float

    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)


@dataclass(frozen=True)
class PeggedConfig:
    """Configuration for :class:`PeggedOrderTypes`."""
    peg_type: str = "mid"        # "mid", "primary", "market"
    side: str = "buy"
    offset: float = 0.0          # absolute offset added (signed by side)
    cap_price: Optional[float] = None  # don't cross this price
    floor_price: Optional[float] = None

    def __post_init__(self):
        if self.peg_type not in ("mid", "primary", "market"):
            raise ValueError("peg_type must be 'mid', 'primary' or 'market'")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")


class PeggedOrderTypes:
    """Compute pegged limit prices and re-price events."""

    def __init__(self, config: Optional[PeggedConfig] = None):
        self.config = config or PeggedConfig()

    def reference_price(self, quote: PeggedQuote) -> float:
        cfg = self.config
        if quote.bid > quote.ask:
            raise ValueError("crossed/locked book: bid > ask")
        if cfg.peg_type == "mid":
            return quote.mid()
        if cfg.peg_type == "primary":
            # primary = same-side
            return quote.bid if cfg.side == "buy" else quote.ask
        # market peg = opposite-side
        return quote.ask if cfg.side == "buy" else quote.bid

    def limit_price(self, quote: PeggedQuote) -> float:
        """Compute the pegged limit price given the current quote."""
        cfg = self.config
        ref = self.reference_price(quote)
        # offset is "more aggressive" for buys when positive; flip for sells
        sign = 1.0 if cfg.side == "buy" else -1.0
        px = ref + sign * cfg.offset
        if cfg.cap_price is not None and cfg.side == "buy":
            px = min(px, cfg.cap_price)
        if cfg.floor_price is not None and cfg.side == "sell":
            px = max(px, cfg.floor_price)
        return float(px)

    def schedule(
        self,
        quotes: List[PeggedQuote],
    ) -> List[dict]:
        """Compute a re-price event for each quote in a sequence."""
        out: List[dict] = []
        last_px: Optional[float] = None
        for i, q in enumerate(quotes):
            px = self.limit_price(q)
            event = {
                "tick": i,
                "ref": self.reference_price(q),
                "limit_price": px,
                "reprice": last_px is None or abs(px - last_px) > 1e-12,
            }
            out.append(event)
            last_px = px
        return out

    def execute(
        self,
        quotes: List[PeggedQuote],
        qty: float,
        broker,
    ) -> List[dict]:
        """Submit/replace a single child order across each quote."""
        if qty <= 0:
            raise ValueError("qty must be > 0")
        cfg = self.config
        results = []
        last_px: Optional[float] = None
        order_id: Optional[str] = None
        for i, q in enumerate(quotes):
            px = self.limit_price(q)
            should_reprice = last_px is None or abs(px - last_px) > 1e-12
            if should_reprice:
                if order_id is not None and hasattr(broker, "cancel_order"):
                    broker.cancel_order(order_id)
                order = {
                    "symbol": getattr(broker, "symbol", "TEST"),
                    "qty": qty,
                    "side": cfg.side,
                    "order_type": "limit",
                    "limit_price": px,
                    "tick": i,
                }
                res = broker.submit_order(order)
                order_id = res.get("order_id")
                results.append(res)
            last_px = px
        return results
