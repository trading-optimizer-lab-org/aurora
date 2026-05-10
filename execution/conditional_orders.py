"""Conditional order types: bracket OCO, trailing stops, stop-limits.

Each helper class encapsulates state for one parent order and exposes
``on_tick(price)`` to drive the lifecycle from a stream of trades.
``ConditionalOrderManager`` is a thin registry that routes ticks to all
active conditional orders and surfaces triggered child orders.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class _ConditionalOrder(Protocol):
    """Structural type for any object handled by ``ConditionalOrderManager``.

    The registry holds StopLimit / TrailingStop / BracketOrder instances,
    each of which exposes ``on_tick``.
    """

    def on_tick(self, price: float) -> Any: ...


@dataclass(frozen=True)
class ConditionalConfig:
    """Configuration for :class:`ConditionalOrderManager`."""
    track_history: bool = True


@dataclass
class StopLimit:
    """Stop-limit: triggers a limit order once stop is hit."""
    side: str            # "buy" or "sell"
    qty: float
    stop_price: float
    limit_price: float
    triggered: bool = False
    history: List[dict] = field(default_factory=list)

    def on_tick(self, price: float) -> Optional[dict]:
        if self.triggered:
            return None
        hit = (
            (self.side == "buy" and price >= self.stop_price)
            or (self.side == "sell" and price <= self.stop_price)
        )
        if hit:
            self.triggered = True
            child = {
                "type": "limit",
                "side": self.side,
                "qty": self.qty,
                "limit_price": self.limit_price,
                "trigger_price": price,
            }
            self.history.append({"event": "trigger", "price": price})
            return child
        self.history.append({"event": "tick", "price": price})
        return None


@dataclass
class TrailingStop:
    """Trailing stop: tracks favorable price, triggers when reversal exceeds trail."""
    side: str            # "sell" trails up, "buy" trails down
    qty: float
    trail_amount: float  # absolute price units
    extreme: Optional[float] = None
    stop_price: Optional[float] = None
    triggered: bool = False
    history: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.trail_amount <= 0:
            raise ValueError("trail_amount must be > 0")
        if self.qty <= 0:
            raise ValueError("qty must be > 0")

    def on_tick(self, price: float) -> Optional[dict]:
        if self.triggered:
            return None
        if self.extreme is None:
            self.extreme = price
        if self.side == "sell":
            if price > self.extreme:
                self.extreme = price
            self.stop_price = self.extreme - self.trail_amount
            hit = price <= self.stop_price
        else:
            if price < self.extreme:
                self.extreme = price
            self.stop_price = self.extreme + self.trail_amount
            hit = price >= self.stop_price
        self.history.append({
            "event": "tick",
            "price": price,
            "extreme": self.extreme,
            "stop": self.stop_price,
        })
        if hit:
            self.triggered = True
            return {
                "type": "market",
                "side": self.side,
                "qty": self.qty,
                "trigger_price": price,
                "stop_price": self.stop_price,
            }
        return None


@dataclass
class BracketOrder:
    """Bracket OCO: take-profit + stop-loss; whichever fires cancels the other."""
    side: str            # exit side: "sell" if long, "buy" if short
    qty: float
    take_profit: float
    stop_loss: float
    triggered_leg: Optional[str] = None  # "tp", "sl", or None
    history: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.qty <= 0:
            raise ValueError("qty must be > 0")
        if self.side == "sell":
            # exiting a long: TP should be ABOVE entry, SL BELOW
            if self.take_profit <= self.stop_loss:
                raise ValueError("for long bracket: take_profit > stop_loss")
        else:
            if self.take_profit >= self.stop_loss:
                raise ValueError("for short bracket: take_profit < stop_loss")

    def on_tick(self, price: float) -> Optional[dict]:
        if self.triggered_leg is not None:
            return None
        tp_hit, sl_hit = False, False
        if self.side == "sell":  # exiting long
            tp_hit = price >= self.take_profit
            sl_hit = price <= self.stop_loss
        else:                     # exiting short
            tp_hit = price <= self.take_profit
            sl_hit = price >= self.stop_loss
        if tp_hit:
            self.triggered_leg = "tp"
            self.history.append({"event": "tp_hit", "price": price})
            return {
                "type": "limit",
                "side": self.side,
                "qty": self.qty,
                "limit_price": self.take_profit,
                "leg": "tp",
                "cancels": "sl",
            }
        if sl_hit:
            self.triggered_leg = "sl"
            self.history.append({"event": "sl_hit", "price": price})
            return {
                "type": "market",
                "side": self.side,
                "qty": self.qty,
                "stop_price": self.stop_loss,
                "leg": "sl",
                "cancels": "tp",
            }
        self.history.append({"event": "tick", "price": price})
        return None


class ConditionalOrderManager:
    """Registry of active conditional orders, driven by a price tick stream."""

    def __init__(self, config: Optional[ConditionalConfig] = None):
        self.config = config or ConditionalConfig()
        self._registry: Dict[str, _ConditionalOrder] = {}
        self._next_id = 1

    def _new_id(self, prefix: str) -> str:
        oid = f"{prefix}-{self._next_id}"
        self._next_id += 1
        return oid

    def add_stop_limit(self, **kwargs) -> str:
        sl = StopLimit(**kwargs)
        oid = self._new_id("stop_limit")
        self._registry[oid] = sl
        return oid

    def add_trailing_stop(self, **kwargs) -> str:
        ts = TrailingStop(**kwargs)
        oid = self._new_id("trailing")
        self._registry[oid] = ts
        return oid

    def add_bracket(self, **kwargs) -> str:
        br = BracketOrder(**kwargs)
        oid = self._new_id("bracket")
        self._registry[oid] = br
        return oid

    def get(self, order_id: str):
        return self._registry.get(order_id)

    def on_tick(self, price: float) -> List[dict]:
        """Push a price tick to every active order; collect triggered child orders."""
        triggered = []
        for oid, ord_obj in self._registry.items():
            child = ord_obj.on_tick(price)
            if child is not None:
                triggered.append({"order_id": oid, **child})
        return triggered

    def schedule(self, prices: List[float]) -> List[dict]:
        """Replay a price path and return all triggered child orders."""
        out = []
        for p in prices:
            out.extend(self.on_tick(p))
        return out

    def execute(self, prices: List[float], broker) -> List[dict]:
        """Drive ``prices`` through the registry, submit each triggered child."""
        results = []
        for child in self.schedule(prices):
            order = {
                "symbol": getattr(broker, "symbol", "TEST"),
                "qty": child["qty"],
                "side": child["side"],
                "order_type": child["type"],
            }
            if child.get("limit_price") is not None:
                order["limit_price"] = child["limit_price"]
            if child.get("stop_price") is not None:
                order["stop_price"] = child["stop_price"]
            res = broker.submit_order(order)
            res["origin_order_id"] = child.get("order_id")
            results.append(res)
        return results
