"""Coinbase broker adapter (official ``coinbase`` SDK, Advanced Trade).

The SDK is imported lazily inside ``__init__`` so the broker package
stays importable when ``coinbase-advanced-py`` is not installed.
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
# CoinbaseAdapter — uses official 'coinbase' SDK
# ---------------------------------------------------------------------------

class CoinbaseAdapter(Broker):
    """Adapter backed by the official 'coinbase' SDK (Advanced Trade)."""

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._sdk = _import_or_raise("coinbase", "pip install coinbase-advanced-py")
        api_key = _read_env(config.api_key_env)
        api_secret = _read_env(config.api_secret_env)
        if not api_key or not api_secret:
            raise ValueError(
                f"Coinbase credentials missing: set env vars "
                f"{config.api_key_env!r} and {config.api_secret_env!r}"
            )
        try:
            from coinbase.rest import RESTClient
            self._client = RESTClient(api_key=api_key, api_secret=api_secret)
        except Exception as e:
            log_event(_log, "coinbase_client_init_failed", level="ERROR",
                      err=str(e))
            raise
        self._seen_client_order_ids: OrderedDict[str, dict] = OrderedDict()
        self._local_positions: dict[str, float] = {}
        self.kill_switch = KillSwitch()
        self.audit_log = AuditLog()
        self._rate_limiter = _RateLimiter(
            max_per_minute=getattr(config, "rate_limit_per_minute", 60),
        )
        log_event(_log, "coinbase_adapter_ready", paper=config.paper)

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
        side = order.side.upper()
        try:
            if order.order_type == "market":
                resp = self._client.create_order(
                    client_order_id=order.client_order_id,
                    product_id=order.symbol,
                    side=side,
                    order_configuration={
                        "market_market_ioc": {"base_size": str(order.qty)}
                    },
                )
            else:
                resp = self._client.create_order(
                    client_order_id=order.client_order_id,
                    product_id=order.symbol,
                    side=side,
                    order_configuration={
                        "limit_limit_gtc": {
                            "base_size": str(order.qty),
                            "limit_price": str(order.limit_price),
                        }
                    },
                )
        except Exception as exc:
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=str(exc))
            raise
        out = {"id": getattr(resp, "order_id", order.client_order_id),
               "status": "submitted",
               "client_order_id": order.client_order_id}
        # Gate local position tracking on broker-acknowledged states (see
        # AlpacaAdapter.submit_order for the rationale). Skip on rejected.
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
            self._client.cancel_orders(order_ids=[order_id])
            self._audit("cancel", order_id=order_id, status="canceled")
            return True
        except Exception as e:
            log_event(_log, "coinbase_cancel_failed", level="WARNING",
                      order_id=order_id, err=str(e))
            self._audit("reject", order_id=order_id, status="cancel_failed",
                        reason=str(e))
            return False

    def get_positions(self) -> list[Position]:
        out: list[Position] = []
        accounts = self._client.get_accounts().accounts
        for a in accounts:
            qty = float(a.available_balance.value)
            if qty <= 0:
                continue
            currency = getattr(a, "currency", "")
            # Skip the quote currency itself: a USD account balance is cash,
            # not a "USD/USD" position. Surfacing it as a position double-
            # counts buying power and pollutes sync() with a phantom row.
            if str(currency).upper() == "USD":
                continue
            sym = f"{currency}/USD"
            out.append(Position(symbol=sym, qty=qty, avg_price=0.0,
                                market_value=0.0, unrealized_pnl=0.0))
        return out

    def get_account(self) -> dict:
        accounts = self._client.get_accounts().accounts
        cash = next((float(a.available_balance.value) for a in accounts
                     if a.currency == "USD"), 0.0)
        return {"cash": cash, "equity": cash, "buying_power": cash}

    def sync(self, tolerance: float = 1e-6) -> dict:
        broker_pos = self.get_positions()
        return _diff_positions(self._local_positions, broker_pos,
                               tolerance=tolerance)


__all__ = ["CoinbaseAdapter"]
