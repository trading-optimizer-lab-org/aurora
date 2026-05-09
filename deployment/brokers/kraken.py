"""Kraken broker adapter (krakenex SDK).

The SDK is imported lazily inside ``__init__`` so the broker package
stays importable when ``krakenex`` is not installed.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any, Optional

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
# KrakenAdapter — uses krakenex
# ---------------------------------------------------------------------------

class KrakenAdapter(Broker):
    """Adapter backed by the krakenex SDK."""

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._sdk = _import_or_raise("krakenex", "pip install krakenex")
        api_key = _read_env(config.api_key_env)
        api_secret = _read_env(config.api_secret_env)
        if not api_key or not api_secret:
            raise ValueError(
                f"Kraken credentials missing: set env vars "
                f"{config.api_key_env!r} and {config.api_secret_env!r}"
            )
        try:
            import krakenex
            self._client = krakenex.API(key=api_key, secret=api_secret)
        except Exception as e:
            log_event(_log, "kraken_client_init_failed", level="ERROR",
                      err=str(e))
            raise
        self._seen_client_order_ids: OrderedDict[str, dict] = OrderedDict()
        self._local_positions: dict[str, float] = {}
        # Map of userref (u32) -> client_order_id we already submitted. We
        # use it to surface collisions: two different QuantForge IDs hashing
        # to the same Kraken userref would otherwise become indistinguishable
        # after-the-fact, masking trace failures.
        self._userref_to_cid: dict[int, str] = {}
        self.kill_switch = KillSwitch()
        self.audit_log = AuditLog()
        self._rate_limiter = _RateLimiter(
            max_per_minute=getattr(config, "rate_limit_per_minute", 60),
        )
        log_event(_log, "kraken_adapter_ready", paper=config.paper)

    @staticmethod
    def _client_order_id_to_userref(client_order_id: Optional[str]) -> int:
        """Map QuantForge ``client_order_id`` (string) to a Kraken ``userref``.

        Kraken's REST API accepts ``userref`` as a 32-bit unsigned integer; it
        does NOT honor a free-form ``cl_ord_id`` field on AddOrder. We hash the
        QuantForge id with BLAKE2b (4-byte digest) into a stable u32 so
        callers can trace orders by their own id while still satisfying the
        Kraken contract. BLAKE2b replaces the previous polynomial-rolling
        hash so collisions on real workloads behave like uniform random in a
        u32 space rather than clustering around short-prefix shapes.
        """
        if client_order_id is None:
            return 0
        digest = hashlib.blake2b(str(client_order_id).encode(),
                                 digest_size=4).digest()
        return int.from_bytes(digest, "big")

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
        # Kraken ignores cl_ord_id but accepts userref (u32). Map our id into
        # a 32-bit unsigned integer so we keep traceability on their side.
        userref = self._client_order_id_to_userref(order.client_order_id)
        # Detect cross-client_order_id userref collisions locally. A real
        # collision means two distinct QuantForge IDs hash to the same u32
        # — log it loudly so operators can rotate the upstream ID scheme.
        existing_cid = self._userref_to_cid.get(userref)
        if existing_cid is not None and existing_cid != order.client_order_id:
            log_event(_log, "kraken_userref_collision", level="ERROR",
                      userref=userref,
                      existing_client_order_id=existing_cid,
                      new_client_order_id=order.client_order_id)
        params = {
            "pair": order.symbol,
            "type": order.side,
            "ordertype": order.order_type,
            "volume": str(order.qty),
            "userref": str(userref),
        }
        if order.order_type == "limit":
            params["price"] = str(order.limit_price)
        try:
            resp = self._client.query_private("AddOrder", params)
        except Exception as exc:
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=str(exc))
            raise
        out: dict[str, Any]
        if resp.get("error"):
            out = {"id": order.client_order_id, "status": "rejected",
                   "reason": "; ".join(resp["error"])}
            self._audit("reject", order_id=out["id"],
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=out.get("reason"))
            self._record_idempotent(order.client_order_id, out)
            return out
        txid = (resp.get("result") or {}).get("txid", [None])
        out = {
            "id": txid[0] or order.client_order_id,
            "status": "submitted",
            "client_order_id": order.client_order_id,
            "userref": userref,
        }
        # Gate local position tracking on broker-acknowledged states (see
        # AlpacaAdapter.submit_order for the rationale). Skip on rejected;
        # the explicit Kraken rejection path returned earlier already
        # short-circuits before reaching here.
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
        # Record the userref -> client_order_id mapping for collision detection.
        if order.client_order_id is not None:
            self._userref_to_cid[userref] = order.client_order_id
        self._record_idempotent(order.client_order_id, out)
        return out

    def cancel_order(self, order_id: str) -> bool:
        self._rate_limit_acquire()
        try:
            resp = self._client.query_private("CancelOrder", {"txid": order_id})
        except Exception as e:
            log_event(_log, "kraken_cancel_failed", level="WARNING",
                      order_id=order_id, err=str(e))
            self._audit("reject", order_id=order_id, status="cancel_failed",
                        reason=str(e))
            return False
        if resp.get("error"):
            log_event(_log, "kraken_cancel_failed", level="WARNING",
                      order_id=order_id, err=str(resp.get("error")))
            self._audit("reject", order_id=order_id, status="cancel_failed",
                        reason=str(resp.get("error")))
            return False
        self._audit("cancel", order_id=order_id, status="canceled")
        return True

    def get_positions(self) -> list[Position]:
        resp = self._client.query_private("OpenPositions", {})
        positions = (resp.get("result") or {})
        out: list[Position] = []
        for _, info in positions.items():
            out.append(Position(
                symbol=info.get("pair", ""),
                qty=float(info.get("vol", 0.0)),
                avg_price=float(info.get("cost", 0.0)) /
                          max(float(info.get("vol", 1.0)), 1e-12),
                market_value=float(info.get("value", 0.0)),
                unrealized_pnl=float(info.get("net", 0.0)),
            ))
        return out

    def get_account(self) -> dict:
        resp = self._client.query_private("Balance", {})
        bal = resp.get("result") or {}
        cash = float(bal.get("ZUSD", 0.0)) if "ZUSD" in bal else float(
            next(iter(bal.values()), 0.0))
        return {"cash": cash, "equity": cash, "buying_power": cash}

    def sync(self, tolerance: float = 1e-6) -> dict:
        broker_pos = self.get_positions()
        return _diff_positions(self._local_positions, broker_pos,
                               tolerance=tolerance)


__all__ = ["KrakenAdapter"]
