"""In-memory PaperBroker implementation.

Self-contained adapter with no external SDK dependencies. Used by tests,
backtests, and the lumibot paper-trading wrappers.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from aurora.core.logging import log_event

from .base import (
    AuditLog,
    Broker,
    BrokerConfig,
    KillSwitch,
    Order,
    Position,
    _RateLimiter,
    _log,
    _validate_order,
)


# ---------------------------------------------------------------------------
# PaperBroker — fully self-contained, no SDK
# ---------------------------------------------------------------------------

@dataclass
class _PaperState:
    cash: float = 100_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    open_orders: dict[str, dict] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)


class PaperBroker(Broker):
    """In-memory paper broker. Always available, no external deps.

    Market orders fill instantly at the last known price for the symbol; if
    no price is registered via `set_last_price`, market submission fails
    cleanly. Limit orders are stored open until canceled.
    """

    def __init__(self, config: BrokerConfig, starting_cash: float = 100_000.0,
                 kill_switch: Optional[KillSwitch] = None,
                 audit_log: Optional[AuditLog] = None):
        self.config = config
        self._state = _PaperState(cash=float(starting_cash))
        self.kill_switch = kill_switch if kill_switch is not None else KillSwitch()
        self.audit_log = audit_log if audit_log is not None else AuditLog()
        self._rate_limiter = _RateLimiter(
            max_per_minute=getattr(config, "rate_limit_per_minute", 60),
        )
        # OrderedDict so the bounded idempotency cache evicts FIFO on overflow.
        self._seen_client_order_ids: OrderedDict[str, dict] = OrderedDict()
        self._local_positions: dict[str, float] = {}
        # Pending-order delta: orders that submit_order accepted but whose
        # fills have not yet been reported. PartialFillEvent / fill_event
        # callbacks decrement this and increment _local_positions. Until
        # the live broker callbacks are fully wired, this surface lets risk
        # tooling distinguish "accepted, not yet filled" from "realized".
        self._pending_orders: dict[str, float] = {}
        log_event(_log, "paper_broker_init",
                  starting_cash=starting_cash, paper=config.paper)

    # --- price registration helper used by tests/users ---------------------
    def set_last_price(self, symbol: str, price: float) -> None:
        """Register last-known price for `symbol`. Used to fill market orders."""
        if price <= 0:
            raise ValueError(f"price must be > 0, got {price}")
        self._state.last_prices[symbol] = float(price)

    # --- Broker interface --------------------------------------------------
    def submit_order(self, order: Order) -> dict:
        order = _validate_order(order)
        # Idempotency: a retry with the same client_order_id returns the
        # original response and never reaches the fill engine again.
        prior = self._idempotent_response(order.client_order_id)
        if prior is not None:
            return prior
        # Kill switch: snapshot account/positions OUTSIDE the kill_switch
        # lock (those getters can perform their own I/O / locking and could
        # otherwise hold the kill switch lock for the duration of broker-state
        # queries). Inside the lock, only run check() against the prepared
        # snapshot and read the trigger flag so concurrent arm()/disarm()
        # cannot slip between check() and the rejection decision.
        blocked: Optional[dict] = None
        if self.kill_switch is not None:
            account_snap = self.get_account()
            positions_snap = self.get_positions()
            with self.kill_switch.locked():
                self.kill_switch.check(account_snap, positions_snap)
                blocked = self._kill_switch_blocked()
        else:
            blocked = self._kill_switch_blocked()
        if blocked is not None:
            blocked["id"] = order.client_order_id
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason="kill_switch_triggered")
            log_event(_log, "kill_switch_blocked_order", level="WARNING",
                      order_id=order.client_order_id, symbol=order.symbol)
            self._record_idempotent(order.client_order_id, blocked)
            return blocked
        # Rate limit
        self._rate_limit_acquire()
        # Audit submit
        self._audit("submit", order_id=order.client_order_id,
                    symbol=order.symbol, side=order.side,
                    qty=float(order.qty),
                    price=float(order.limit_price) if order.limit_price else None,
                    status="submitted")
        if order.order_type == "market":
            resp = self._fill_market(order)
        else:
            resp = self._open_limit(order)
        # Audit outcome
        if resp.get("status") == "filled":
            self._audit("fill", order_id=resp.get("id"),
                        symbol=order.symbol, side=order.side,
                        qty=float(resp.get("filled_qty", 0.0)),
                        price=float(resp.get("filled_avg_price", 0.0)),
                        status="filled")
        elif resp.get("status") == "rejected":
            self._audit("reject", order_id=resp.get("id"),
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=str(resp.get("reason", "")))
        self._record_idempotent(order.client_order_id, resp)
        return resp

    def cancel_order(self, order_id: str) -> bool:
        self._rate_limit_acquire()
        if order_id in self._state.open_orders:
            self._state.open_orders.pop(order_id)
            log_event(_log, "paper_cancel", order_id=order_id)
            self._audit("cancel", order_id=order_id, status="canceled")
            return True
        return False

    def partial_fill_event(self, order_id: str, filled_qty: float,
                           remaining_qty: float, price: float) -> None:
        """Apply a partial fill against an open paper limit order.

        Correctness gap (live adapters)
        -------------------------------
        The live adapters (Alpaca, IB, Coinbase, Kraken) update
        ``_local_positions`` at submit time, which over-counts positions when
        a fill is partial or rejected after the wire round-trip. Until each
        adapter wires a real ``fill_event`` callback fed by the broker stream,
        operators should treat ``_local_positions`` after submit as
        "accepted, not realized" and reconcile via ``sync()``. Paper orders
        are atomic so this issue does not manifest here.

        - Updates cash/position the same way a market fill does.
        - Decrements the open order's remaining qty; removes it when 0.
        - Audits the event.
        """
        if filled_qty <= 0:
            raise ValueError(f"filled_qty must be > 0, got {filled_qty}")
        if price <= 0:
            raise ValueError(f"price must be > 0, got {price}")
        rec = self._state.open_orders.get(order_id)
        if rec is None:
            # Still log/audit even if order is unknown (broker callback race).
            super().partial_fill_event(order_id, filled_qty, remaining_qty, price)
            return
        side = rec["side"]
        symbol = rec["symbol"]
        notional = price * filled_qty
        if side == "buy":
            self._state.cash -= notional
            self._update_position(symbol, filled_qty, price)
        else:
            self._state.cash += notional
            self._update_position(symbol, -filled_qty, price)
        # Update remaining qty
        new_remaining = float(remaining_qty)
        if new_remaining <= 0:
            self._state.open_orders.pop(order_id, None)
        else:
            rec["qty"] = new_remaining
        super().partial_fill_event(order_id, filled_qty, remaining_qty, price)

    def reconcile(self, tolerance: float = 1e-6) -> dict:
        """Paper broker is the source of truth — always consistent."""
        return self.sync()

    def get_positions(self) -> list[Position]:
        # Refresh market value with last known price when available.
        out: list[Position] = []
        for sym, pos in self._state.positions.items():
            last = self._state.last_prices.get(sym, pos.avg_price)
            mv = pos.qty * last
            unrealized = (last - pos.avg_price) * pos.qty
            out.append(Position(symbol=sym, qty=pos.qty, avg_price=pos.avg_price,
                                market_value=mv, unrealized_pnl=unrealized))
        return out

    def get_account(self) -> dict:
        equity = self._state.cash + sum(
            p.market_value for p in self.get_positions()
        )
        return {
            "cash": self._state.cash,
            "equity": equity,
            "buying_power": self._state.cash,
            "positions": len(self._state.positions),
            "open_orders": len(self._state.open_orders),
        }

    def sync(self, tolerance: float = 1e-6) -> dict:
        # Paper broker is the source of truth. Always consistent.
        return {"missing_local": [], "missing_broker": [], "qty_mismatch": []}

    # --- internals ---------------------------------------------------------
    def _fill_market(self, order: Order) -> dict:
        last = self._state.last_prices.get(order.symbol)
        if last is None:
            raise ValueError(
                f"PaperBroker has no last price for {order.symbol!r}; "
                "call set_last_price() first."
            )
        notional = last * order.qty
        if order.side == "buy":
            if notional > self._state.cash:
                log_event(_log, "paper_insufficient_cash", level="WARNING",
                          symbol=order.symbol, notional=notional,
                          cash=self._state.cash)
                return {
                    "id": order.client_order_id,
                    "status": "rejected",
                    "reason": "insufficient_cash",
                    "filled_qty": 0.0,
                    "filled_avg_price": 0.0,
                }
            self._state.cash -= notional
            self._update_position(order.symbol, order.qty, last)
        else:  # sell
            cur = self._state.positions.get(order.symbol)
            held = cur.qty if cur else 0.0
            if order.qty > held:
                log_event(_log, "paper_short_disallowed", level="WARNING",
                          symbol=order.symbol, qty=order.qty, held=held)
                return {
                    "id": order.client_order_id,
                    "status": "rejected",
                    "reason": "short_disallowed",
                    "filled_qty": 0.0,
                    "filled_avg_price": 0.0,
                }
            self._state.cash += notional
            self._update_position(order.symbol, -order.qty, last)
        log_event(_log, "paper_fill", symbol=order.symbol, side=order.side,
                  qty=order.qty, price=last)
        return {
            "id": order.client_order_id,
            "status": "filled",
            "filled_qty": order.qty,
            "filled_avg_price": last,
        }

    def _open_limit(self, order: Order) -> dict:
        assert order.client_order_id is not None
        rec = {
            "id": order.client_order_id,
            "status": "open",
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "order_type": "limit",
            "limit_price": order.limit_price,
            "time_in_force": order.time_in_force,
        }
        self._state.open_orders[order.client_order_id] = rec
        log_event(_log, "paper_limit_open", symbol=order.symbol,
                  side=order.side, limit_price=order.limit_price)
        return dict(rec)

    def _update_position(self, symbol: str, signed_qty: float,
                         price: float) -> None:
        cur = self._state.positions.get(symbol)
        if cur is None:
            if signed_qty == 0:
                return
            self._state.positions[symbol] = Position(
                symbol=symbol, qty=signed_qty, avg_price=price,
                market_value=signed_qty * price, unrealized_pnl=0.0,
            )
            self._update_local_position(symbol, signed_qty)
            return
        new_qty = cur.qty + signed_qty
        if abs(new_qty) < 1e-12:
            # Reduced to flat. Drop the position record AND its local cache.
            self._state.positions.pop(symbol)
            self._update_local_position(symbol, signed_qty)
            return
        # Detect side flip: prior qty and new qty have opposite signs and
        # both are non-zero. Treat as a fresh entry at the new fill price.
        cur_sign = 1 if cur.qty > 0 else (-1 if cur.qty < 0 else 0)
        new_sign = 1 if new_qty > 0 else (-1 if new_qty < 0 else 0)
        flipped = (cur_sign != 0 and new_sign != 0 and cur_sign != new_sign)
        if flipped:
            new_avg = price
        elif (cur.qty > 0 and signed_qty > 0) or (cur.qty < 0 and signed_qty < 0):
            # Pure accumulation: weighted-average of cost basis.
            new_avg = (cur.avg_price * cur.qty + price * signed_qty) / new_qty
        else:
            # Partial reduction without flip: avg cost is unchanged.
            new_avg = cur.avg_price
        self._state.positions[symbol] = Position(
            symbol=symbol, qty=new_qty, avg_price=new_avg,
            market_value=new_qty * price, unrealized_pnl=0.0,
        )
        if flipped:
            # Side flip: previous local-cache delta would re-add the wrong
            # signed_qty (e.g. 5 long -> 7-share sell -> net -2 short, but
            # the local cache would still read 5+(-7) = -2 only if we had
            # been tracking cur.qty exactly. Set the cache absolutely to
            # the post-flip qty so any drift from prior partial states is
            # eliminated.
            loc = getattr(self, "_local_positions", None)
            if loc is None:
                loc = {}
                self._local_positions = loc
            if abs(new_qty) < 1e-12:
                loc.pop(symbol, None)
            else:
                loc[symbol] = float(new_qty)
        else:
            self._update_local_position(symbol, signed_qty)


__all__ = ["PaperBroker", "_PaperState"]
