"""Interactive Brokers adapter (ib_insync SDK).

The SDK is imported lazily inside ``__init__`` so the broker package
stays importable when ``ib_insync`` is not installed.
"""
from __future__ import annotations

from collections import OrderedDict
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
    _diff_positions,
    _import_or_raise,
    _log,
    _validate_order,
)


# ---------------------------------------------------------------------------
# IBAdapter — uses ib_insync
# ---------------------------------------------------------------------------

class IBAdapter(Broker):
    """Adapter backed by ib_insync (Interactive Brokers TWS / Gateway).

    Credentials are unused for IB (login is via TWS / Gateway), but
    BrokerConfig.base_url is interpreted as 'host:port' for ib_insync.
    """

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._sdk = _import_or_raise("ib_insync", "pip install ib_insync")
        try:
            from ib_insync import IB
            self._ib = IB()
            host, port = "127.0.0.1", 7497 if config.paper else 7496
            if config.base_url:
                if ":" in config.base_url:
                    h, p = config.base_url.split(":", 1)
                    host, port = h, int(p)
            self._ib.connect(host, port, clientId=1, readonly=False)
        except Exception as e:
            log_event(_log, "ib_connect_failed", level="ERROR", err=str(e))
            raise
        self._seen_client_order_ids: OrderedDict[str, dict] = OrderedDict()
        self._local_positions: dict[str, float] = {}
        self.kill_switch = KillSwitch()
        self.audit_log = AuditLog()
        self._rate_limiter = _RateLimiter(
            max_per_minute=getattr(config, "rate_limit_per_minute", 60),
        )
        log_event(_log, "ib_adapter_ready", paper=config.paper)

    def submit_order(self, order: Order) -> dict:
        order = _validate_order(order)
        prior = self._idempotent_response(order.client_order_id)
        if prior is not None:
            return prior
        blocked: Optional[dict] = None
        if self.kill_switch is not None:
            try:
                account_snap = self.get_account()
                positions_snap = self.get_positions()
            except Exception:
                account_snap = {"equity": 0.0}
                positions_snap = []
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
        self._rate_limit_acquire()
        self._audit("submit", order_id=order.client_order_id,
                    symbol=order.symbol, side=order.side,
                    qty=float(order.qty),
                    price=float(order.limit_price) if order.limit_price else None,
                    status="submitted")
        from ib_insync import LimitOrder, MarketOrder, Stock
        contract = Stock(order.symbol, "SMART", "USD")
        action = "BUY" if order.side == "buy" else "SELL"
        if order.order_type == "market":
            ib_order = MarketOrder(action, order.qty)
        else:
            ib_order = LimitOrder(action, order.qty, order.limit_price)
        ib_order.tif = order.time_in_force.upper()
        try:
            trade = self._ib.placeOrder(contract, ib_order)
        except Exception as exc:
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=str(exc))
            raise
        out = {"id": str(getattr(trade.order, "permId", "")) or
                     order.client_order_id,
               "status": getattr(trade.orderStatus, "status", "submitted"),
               "client_order_id": order.client_order_id}
        # Gate local position tracking on broker-acknowledged states (see
        # AlpacaAdapter.submit_order for the rationale). Skip on rejected so
        # a refused IB order does not inflate _local_positions.
        status = str(out.get("status", "")).lower()
        if status in ("submitted", "accepted", "filled", "partially_filled"):
            signed_qty = (float(order.qty)
                          if order.side == "buy" else -float(order.qty))
            self._update_local_position(order.symbol, signed_qty)
            if status in ("filled", "partially_filled"):
                self._audit("fill", order_id=out["id"],
                            symbol=order.symbol, side=order.side,
                            qty=float(order.qty),
                            status=status)
        elif status == "rejected":
            self._audit("reject", order_id=out["id"],
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected")
        self._record_idempotent(order.client_order_id, out)
        return out

    def cancel_order(self, order_id: str) -> bool:
        self._rate_limit_acquire()
        for t in self._ib.openTrades():
            if str(getattr(t.order, "permId", "")) == str(order_id):
                try:
                    self._ib.cancelOrder(t.order)
                    self._audit("cancel", order_id=order_id, status="canceled")
                    return True
                except Exception as e:
                    log_event(_log, "ib_cancel_failed", level="WARNING",
                              order_id=order_id, err=str(e))
                    self._audit("reject", order_id=order_id,
                                status="cancel_failed", reason=str(e))
                    return False
        return False

    def get_positions(self) -> list[Position]:
        out: list[Position] = []
        for p in self._ib.positions():
            out.append(Position(
                symbol=p.contract.symbol,
                qty=float(p.position),
                avg_price=float(p.avgCost),
                market_value=float(p.position) * float(p.avgCost),
                unrealized_pnl=0.0,
            ))
        return out

    def get_account(self) -> dict:
        rows = self._ib.accountSummary()
        cash = next((float(r.value) for r in rows if r.tag == "TotalCashValue"), 0.0)
        equity = next((float(r.value) for r in rows if r.tag == "NetLiquidation"), 0.0)
        return {"cash": cash, "equity": equity, "buying_power": cash}

    def sync(self, tolerance: float = 1e-6) -> dict:
        broker_pos = self.get_positions()
        return _diff_positions(self._local_positions, broker_pos,
                               tolerance=tolerance)


__all__ = ["IBAdapter"]
