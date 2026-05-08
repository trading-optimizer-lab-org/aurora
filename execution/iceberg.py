"""Iceberg order manager.

An iceberg shows ``display_qty`` to the market while keeping the rest
hidden. As fills come in, it auto-replenishes the displayed slice from
the hidden remainder until the parent quantity is exhausted.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class IcebergConfig:
    """Configuration for :class:`IcebergOrderManager`."""
    display_qty: float = 100.0
    side: str = "buy"
    limit_price: Optional[float] = None
    max_replenishments: int = 10000

    def __post_init__(self):
        if self.display_qty <= 0:
            raise ValueError("display_qty must be > 0")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.max_replenishments < 1:
            raise ValueError("max_replenishments must be >= 1")


@dataclass
class IcebergState:
    """Tracks the lifecycle of an iceberg parent order."""
    parent_qty: float
    filled_qty: float = 0.0
    displayed_qty: float = 0.0
    hidden_qty: float = 0.0
    replenishments: int = 0
    history: List[dict] = field(default_factory=list)
    closed: bool = False

    @property
    def remaining(self) -> float:
        return max(self.parent_qty - self.filled_qty, 0.0)


class IcebergOrderManager:
    """Manages display + hidden quantity replenishment for one parent order."""

    def __init__(self, config: Optional[IcebergConfig] = None):
        self.config = config or IcebergConfig()

    def open(self, parent_qty: float) -> IcebergState:
        """Start a new iceberg parent of ``parent_qty`` shares."""
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        state = IcebergState(parent_qty=float(parent_qty))
        self._refresh_display(state, initial=True)
        return state

    def _refresh_display(self, state: IcebergState, initial: bool = False) -> None:
        cfg = self.config
        if state.closed:
            return
        if state.remaining <= 0:
            state.displayed_qty = 0.0
            state.hidden_qty = 0.0
            state.closed = True
            return
        new_display = min(cfg.display_qty, state.remaining)
        new_hidden = max(state.remaining - new_display, 0.0)
        state.displayed_qty = float(new_display)
        state.hidden_qty = float(new_hidden)
        event = "open" if initial else "replenish"
        state.history.append({
            "event": event,
            "displayed": state.displayed_qty,
            "hidden": state.hidden_qty,
            "filled": state.filled_qty,
        })

    def on_fill(self, state: IcebergState, fill_qty: float) -> IcebergState:
        """Process a fill; auto-replenish display from hidden if needed."""
        if state.closed:
            raise ValueError("iceberg is already closed")
        if fill_qty <= 0:
            raise ValueError("fill_qty must be > 0")
        if fill_qty > state.displayed_qty + 1e-9:
            raise ValueError(
                f"fill_qty {fill_qty} exceeds displayed {state.displayed_qty}"
            )
        state.filled_qty += fill_qty
        state.displayed_qty -= fill_qty
        state.history.append({
            "event": "fill",
            "filled_now": fill_qty,
            "filled_total": state.filled_qty,
            "remaining": state.remaining,
        })
        if state.displayed_qty < 1e-9 and state.remaining > 0:
            if state.replenishments >= self.config.max_replenishments:
                state.closed = True
                state.history.append({"event": "max_replenishments_hit"})
                return state
            state.replenishments += 1
            self._refresh_display(state)
        if state.remaining <= 0:
            state.closed = True
            state.history.append({"event": "complete"})
        return state

    def execute(
        self,
        state: IcebergState,
        broker,
        fills: List[float],
    ) -> List[dict]:
        """Drive a sequence of fills through the manager + broker.

        ``fills`` is a list of fill quantities to apply in order. Each
        triggers a child order submission on ``broker``.
        """
        results = []
        cfg = self.config
        for q in fills:
            if state.closed:
                break
            order = {
                "symbol": getattr(broker, "symbol", "TEST"),
                "qty": min(q, state.displayed_qty),
                "side": cfg.side,
                "order_type": "limit",
                "limit_price": cfg.limit_price,
            }
            res = broker.submit_order(order)
            results.append(res)
            actual = float(res.get("filled_qty", order["qty"]))
            if actual <= 0:
                continue
            self.on_fill(state, actual)
        return results
