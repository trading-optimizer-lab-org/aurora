"""Alpaca broker adapter (alpaca-py SDK).

The SDK is imported lazily inside ``__init__`` so the broker package
stays importable when ``alpaca-py`` is not installed.
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
    _read_env,
    _validate_order,
)


# ---------------------------------------------------------------------------
# AlpacaAdapter — uses alpaca-py
# ---------------------------------------------------------------------------

class AlpacaAdapter(Broker):
    """Adapter backed by the alpaca-py SDK.

    The SDK is imported lazily inside __init__. Credentials come from the
    environment via BrokerConfig.api_key_env / api_secret_env.
    """

    def __init__(self, config: BrokerConfig):
        self.config = config
        # Lazy import — keeps Aurora importable without alpaca-py.
        self._sdk = _import_or_raise("alpaca", "pip install alpaca-py")
        api_key = _read_env(config.api_key_env)
        api_secret = _read_env(config.api_secret_env)
        if not api_key or not api_secret:
            raise ValueError(
                f"Alpaca credentials missing: set env vars "
                f"{config.api_key_env!r} and {config.api_secret_env!r}"
            )
        # Build trading client. Real implementations use TradingClient.
        try:
            from alpaca.trading.client import TradingClient
            self._client = TradingClient(api_key, api_secret, paper=config.paper)
        except Exception as e:
            log_event(_log, "alpaca_client_init_failed", level="ERROR",
                      err=str(e))
            raise
        self._seen_client_order_ids: OrderedDict[str, dict] = OrderedDict()
        self._local_positions: dict[str, float] = {}
        # Risk-gate triad: same surface as PaperBroker so live submits go
        # through kill_switch/audit/rate_limit before reaching the SDK.
        self.kill_switch = KillSwitch()
        self.audit_log = AuditLog()
        self._rate_limiter = _RateLimiter(
            max_per_minute=getattr(config, "rate_limit_per_minute", 60),
        )
        log_event(_log, "alpaca_adapter_ready", paper=config.paper)

    def submit_order(self, order: Order) -> dict:
        order = _validate_order(order)
        prior = self._idempotent_response(order.client_order_id)
        if prior is not None:
            return prior
        # Kill switch: snapshot account/positions outside the lock, evaluate
        # under the lock, and reject early when triggered.
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
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
        )
        side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL
        tif_map = {"day": TimeInForce.DAY, "gtc": TimeInForce.GTC,
                   "ioc": TimeInForce.IOC}
        tif = tif_map[order.time_in_force]
        if order.order_type == "market":
            req = MarketOrderRequest(symbol=order.symbol, qty=order.qty,
                                     side=side, time_in_force=tif,
                                     client_order_id=order.client_order_id)
        else:
            req = LimitOrderRequest(symbol=order.symbol, qty=order.qty,
                                    side=side, time_in_force=tif,
                                    limit_price=order.limit_price,
                                    client_order_id=order.client_order_id)
        try:
            resp = self._client.submit_order(req)
        except Exception as exc:
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=str(exc))
            raise
        out = {"id": str(getattr(resp, "id", order.client_order_id)),
               "status": getattr(resp, "status", "submitted"),
               "client_order_id": order.client_order_id}
        # Gate local position tracking on broker-acknowledged states. Status
        # values map to one of:
        #   submitted / accepted / filled / partially_filled -> track delta
        #   rejected (or any unknown / error state)           -> skip update
        # The previous code unconditionally applied the delta, so a rejected
        # round-trip silently inflated _local_positions and the next sync()
        # falsely reported a missing-broker position.
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
        try:
            self._client.cancel_order_by_id(order_id)
            self._audit("cancel", order_id=order_id, status="canceled")
            return True
        except Exception as e:
            log_event(_log, "alpaca_cancel_failed", level="WARNING",
                      order_id=order_id, err=str(e))
            self._audit("reject", order_id=order_id, status="cancel_failed",
                        reason=str(e))
            return False

    def get_positions(self) -> list[Position]:
        out: list[Position] = []
        for p in self._client.get_all_positions():
            out.append(Position(
                symbol=p.symbol,
                qty=float(p.qty),
                avg_price=float(p.avg_entry_price),
                market_value=float(p.market_value),
                unrealized_pnl=float(p.unrealized_pl),
            ))
        return out

    def get_account(self) -> dict:
        a = self._client.get_account()
        return {
            "cash": float(a.cash),
            "equity": float(a.equity),
            "buying_power": float(a.buying_power),
        }

    def sync(self, tolerance: float = 1e-6) -> dict:
        # Compare local position tracking against live broker view.
        broker_pos = self.get_positions()
        return _diff_positions(self._local_positions, broker_pos,
                               tolerance=tolerance)


__all__ = ["AlpacaAdapter"]
