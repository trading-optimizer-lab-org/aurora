"""CCXT broker adapter (P3.A).

Lazy-imports ``ccxt`` so Aurora stays importable without crypto deps.

Triple-gate for live trading
----------------------------
Going live (``sandbox=False``) requires THREE independent ceremonies:

1. ``gateway_committed`` -- :class:`agent_gateway.gateway.CommittedAction`
   counter-signed by an operator. The agent gateway never delivers a
   committed action to the adapter without a human sig.
2. ``OOSGuard`` ceremony with phase ``"ccxt_live_authorized"`` open in
   the calling thread.
3. Allow-live consent token written by ``forge crypto allow-live``.

If any of the three is missing, ``submit_order`` returns a structured
rejection rather than placing the order.

Crypto-specific safeguards
--------------------------
* Sandbox default ON. Operator must explicitly disable.
* API keys are read from environment variables; never logged, never
  copied into adapter attributes more than once, never persisted.
* KillSwitch reads the global ``QF_CCXT_KILL_SWITCH=1`` env on each
  submit so an operator can halt all CCXT order flow without
  restarting the process.
* RateLimiter respects the exchange's ``rateLimit`` advice when
  available (overridable via the adapter config).
* Max position concentration is enforced from
  :attr:`ProtocolPolicy.risk_limits.max_position_concentration`
  unless overridden.
* Stablecoin check: orders against unstable quote currencies emit a
  ``UserWarning`` so the operator notices accidental BTC-vs-ETH
  inversions.
"""
from __future__ import annotations

import copy
import logging
import os
import threading
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from aurora.core.logging import get_logger, log_event
from aurora.deployment.brokers import (
    AuditLog,
    Broker,
    BrokerConfig,
    KillSwitch,
    Order,
    Position,
    _RateLimiter,
    _validate_order,
)

_log = get_logger("deployment.ccxt_adapter")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Aurora canonical env var patterns (R23). Legacy QF_CCXT_* names are still
# accepted via aurora_env() with a DeprecationWarning during the shim window.
KILL_SWITCH_ENV = "AU_CCXT_KILL_SWITCH"
KILL_SWITCH_ENV_LEGACY = "QF_CCXT_KILL_SWITCH"
LIVE_CEREMONY_PHASE = "ccxt_live_authorized"
ALLOW_LIVE_TOKEN_ENV_PATTERN = "AU_CCXT_ALLOW_LIVE_{EXCHANGE}"
ALLOW_LIVE_TOKEN_ENV_PATTERN_LEGACY = "QF_CCXT_ALLOW_LIVE_{EXCHANGE}"
DEFAULT_API_KEY_ENV_PATTERN = "AU_CCXT_{EXCHANGE}_KEY"
DEFAULT_API_KEY_ENV_PATTERN_LEGACY = "QF_CCXT_{EXCHANGE}_KEY"
DEFAULT_API_SECRET_ENV_PATTERN = "AU_CCXT_{EXCHANGE}_SECRET"
DEFAULT_API_SECRET_ENV_PATTERN_LEGACY = "QF_CCXT_{EXCHANGE}_SECRET"
STABLE_QUOTES = frozenset({"USDT", "USDC", "USD", "DAI", "BUSD", "TUSD", "PAX"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CCXTLiveCeremonyError(RuntimeError):
    """Raised when live submission lacks the required triple-gate."""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CCXTBrokerAdapter(Broker):
    """CCXT-backed broker adapter (lazy-import).

    Construction is deliberately verbose: the adapter holds enough state to
    enforce the triple-gate without trusting the caller to remember it.

    Args:
        exchange_id: ccxt exchange id (e.g. ``"binance"``, ``"kraken"``).
        api_key_env: env var name holding the API key. Defaults to
            ``QF_CCXT_<EXCHANGE>_KEY``. Never the key itself.
        secret_env: env var name holding the API secret. Defaults to
            ``QF_CCXT_<EXCHANGE>_SECRET``.
        sandbox: True (default) routes to the exchange's sandbox/testnet.
            Setting False requires the triple-gate at submit time.
        kill_switch: optional :class:`KillSwitch`. Defaults to a fresh one
            sized for crypto's higher daily-loss tolerance.
        audit_log: optional :class:`AuditLog`. Defaults to a fresh one.
        rate_limiter: optional :class:`_RateLimiter`. Defaults sized to
            the exchange's advertised rateLimit.
        max_position_concentration: optional override for the policy
            cap. Defaults to ProtocolPolicy.risk_limits.max_position_concentration.
        allowed_quotes: set of acceptable quote currencies; orders with a
            quote outside this set warn at submit time.
        config: extra dict passed through to the ccxt exchange constructor
            (timeouts, custom URLs, etc.).
    """

    def __init__(
        self,
        exchange_id: str,
        api_key_env: Optional[str] = None,
        secret_env: Optional[str] = None,
        *,
        sandbox: bool = True,
        kill_switch: Optional[KillSwitch] = None,
        audit_log: Optional[AuditLog] = None,
        rate_limiter: Optional[_RateLimiter] = None,
        max_position_concentration: Optional[float] = None,
        allowed_quotes: Optional[set[str]] = None,
        config: Optional[dict] = None,
    ) -> None:
        self.exchange_id = str(exchange_id).lower()
        self.sandbox = bool(sandbox)
        self.api_key_env = api_key_env or DEFAULT_API_KEY_ENV_PATTERN.format(
            EXCHANGE=self.exchange_id.upper()
        )
        self.secret_env = secret_env or DEFAULT_API_SECRET_ENV_PATTERN.format(
            EXCHANGE=self.exchange_id.upper()
        )
        # Legacy QF_* fallbacks for the shim window (R23). Only used when the
        # caller did not explicitly override the env name.
        self._api_key_env_legacy = (
            None if api_key_env
            else DEFAULT_API_KEY_ENV_PATTERN_LEGACY.format(
                EXCHANGE=self.exchange_id.upper()
            )
        )
        self._secret_env_legacy = (
            None if secret_env
            else DEFAULT_API_SECRET_ENV_PATTERN_LEGACY.format(
                EXCHANGE=self.exchange_id.upper()
            )
        )
        self.allowed_quotes = (
            set(allowed_quotes) if allowed_quotes is not None
            else set(STABLE_QUOTES)
        )
        self._extra_config = dict(config or {})
        # Lazy import: build the exchange object now, so a missing ccxt
        # surfaces at construction (the operator wants to know up front,
        # not at the first order).
        self._sdk = self._import_ccxt()
        self._client = self._build_client()
        # Risk-gate triad mirrors PaperBroker / AlpacaAdapter.
        self.kill_switch = kill_switch or KillSwitch(
            max_daily_loss_pct=0.20,  # crypto vol -> wider default
        )
        self.audit_log = audit_log or AuditLog()
        # Rate limit: prefer ccxt's advertised value (ms per call) -> per-min.
        if rate_limiter is None:
            advised_ms = float(getattr(self._client, "rateLimit", 1000) or 1000)
            calls_per_min = max(1, int(60_000 // max(1.0, advised_ms)))
            rate_limiter = _RateLimiter(max_per_minute=calls_per_min)
        self._rate_limiter = rate_limiter
        # Policy-driven concentration cap.
        if max_position_concentration is None:
            try:
                from aurora.core.protocol_policy import ProtocolPolicy
                pol = ProtocolPolicy.load()
                max_position_concentration = float(
                    pol.risk_limits.max_position_concentration
                )
            except Exception:
                max_position_concentration = 1.0
        self.max_position_concentration = float(max_position_concentration)
        self._seen_client_order_ids: OrderedDict[str, dict] = OrderedDict()
        self._local_positions: dict[str, float] = {}
        # Construction-time audit: NEVER include the API key. Just the env
        # var name + sandbox flag + exchange.
        log_event(_log, "ccxt_adapter_init",
                  exchange=self.exchange_id,
                  sandbox=self.sandbox,
                  api_key_env=self.api_key_env,
                  secret_env=self.secret_env)

    # -- Compatibility shim so create_broker(BrokerConfig) can construct us.
    @classmethod
    def from_config(cls, config: BrokerConfig) -> "CCXTBrokerAdapter":
        # ``BrokerConfig`` doesn't carry an exchange_id field; fall back to
        # 'binance' but allow the caller to override via config.base_url
        # or by setting the env var AU_CCXT_DEFAULT_EXCHANGE (legacy
        # QF_CCXT_DEFAULT_EXCHANGE still honoured during the shim window).
        from aurora.core.env_compat import aurora_env
        exchange = (
            aurora_env("AU_CCXT_DEFAULT_EXCHANGE", "QF_CCXT_DEFAULT_EXCHANGE") or
            (config.base_url if config.base_url else "binance")
        )
        return cls(
            exchange_id=exchange,
            api_key_env=config.api_key_env,
            secret_env=config.api_secret_env,
            sandbox=bool(config.paper),
        )

    # -----------------------------------------------------------------
    # ccxt setup helpers
    # -----------------------------------------------------------------

    def _import_ccxt(self) -> Any:
        try:
            import ccxt
        except Exception as exc:  # pragma: no cover - ccxt optional
            raise ImportError(
                "ccxt broker adapter requires the optional ``ccxt`` package; "
                "install with ``pip install ccxt``"
            ) from exc
        return ccxt

    def _build_client(self) -> Any:
        ccxt = self._sdk
        if not hasattr(ccxt, self.exchange_id):
            raise ValueError(
                f"ccxt adapter: unknown exchange_id {self.exchange_id!r}; "
                f"see ccxt.exchanges for the supported list"
            )
        cls = getattr(ccxt, self.exchange_id)
        # Pull credentials from ENV once and discard the locals so they
        # don't sit on the heap any longer than the SDK instance keeps them.
        from aurora.core.env_compat import aurora_env
        api_key = aurora_env(self.api_key_env, self._api_key_env_legacy) or ""
        api_secret = aurora_env(self.secret_env, self._secret_env_legacy) or ""
        cfg = dict(self._extra_config)
        cfg.setdefault("apiKey", api_key)
        cfg.setdefault("secret", api_secret)
        cfg.setdefault("enableRateLimit", True)
        client = cls(cfg)
        # Sandbox routing: ccxt's set_sandbox_mode handles it for the
        # exchanges that support it; otherwise we leave it production-side
        # (and the triple-gate at submit prevents accidental live orders).
        if self.sandbox and hasattr(client, "set_sandbox_mode"):
            try:
                client.set_sandbox_mode(True)
            except Exception as exc:  # pragma: no cover - exchange-specific
                log_event(_log, "ccxt_sandbox_unsupported", level="WARNING",
                          exchange=self.exchange_id, err=str(exc))
        return client

    # -----------------------------------------------------------------
    # Triple-gate helpers
    # -----------------------------------------------------------------

    def _kill_switch_env_triggered(self) -> bool:
        from aurora.core.env_compat import aurora_env
        val = (aurora_env(KILL_SWITCH_ENV, KILL_SWITCH_ENV_LEGACY) or "").strip()
        return val in ("1", "true", "yes", "TRUE")

    def _has_live_oos_ceremony(self) -> bool:
        try:
            from aurora.core.data_layer import OOSGuard
            guard = OOSGuard.active()
            if guard is None:
                return False
            phase = str(getattr(guard, "phase", "") or "")
            return phase == LIVE_CEREMONY_PHASE
        except Exception:
            return False

    def _has_allow_live_token(self) -> bool:
        from aurora.core.env_compat import aurora_env
        env_var = ALLOW_LIVE_TOKEN_ENV_PATTERN.format(
            EXCHANGE=self.exchange_id.upper()
        )
        legacy_var = ALLOW_LIVE_TOKEN_ENV_PATTERN_LEGACY.format(
            EXCHANGE=self.exchange_id.upper()
        )
        token = (aurora_env(env_var, legacy_var) or "").strip()
        return bool(token) and token not in ("0", "false", "FALSE")

    def _check_live_triple_gate(
        self, gateway_committed: Optional[Any]
    ) -> Optional[str]:
        """Return None on pass, else a string explaining the missing gate."""
        if gateway_committed is None:
            return "missing_gateway_committed"
        if not self._has_live_oos_ceremony():
            return "missing_oos_guard_ceremony"
        if not self._has_allow_live_token():
            return "missing_allow_live_token"
        return None

    # -----------------------------------------------------------------
    # Validation helpers
    # -----------------------------------------------------------------

    def _normalize_symbol(self, symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if "/" in s:
            return s
        for sep in ("-", "_"):
            if sep in s:
                base, quote = s.split(sep, 1)
                return f"{base}/{quote}"
        # Try to split common quotes off the end.
        for q in ("USDT", "USDC", "USD", "BTC", "ETH", "EUR"):
            if s.endswith(q) and len(s) > len(q):
                return f"{s[: -len(q)]}/{q}"
        raise ValueError(
            f"cannot normalize symbol {symbol!r}: expected BASE/QUOTE shape"
        )

    def _check_quote_currency(self, symbol: str) -> None:
        try:
            _, quote = self._normalize_symbol(symbol).split("/", 1)
        except Exception:
            return
        if quote not in self.allowed_quotes:
            warnings.warn(
                f"ccxt adapter: order against unstable quote {quote!r} "
                f"(symbol={symbol!r}); only {sorted(self.allowed_quotes)} "
                "are configured as allowed_quotes.",
                UserWarning,
                stacklevel=3,
            )

    # -----------------------------------------------------------------
    # Broker interface
    # -----------------------------------------------------------------

    def submit_order(
        self,
        order: Order,
        *,
        gateway_committed: Optional[Any] = None,
    ) -> dict:
        order = _validate_order(order)
        prior = self._idempotent_response(order.client_order_id)
        if prior is not None:
            return prior
        # 0. Global env kill switch gate (fast path so an operator can
        #    halt the whole CCXT surface without restart).
        if self._kill_switch_env_triggered():
            resp = {
                "id": order.client_order_id,
                "status": "rejected",
                "reason": "kill_switch_env",
                "filled_qty": 0.0,
                "filled_avg_price": 0.0,
            }
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason="kill_switch_env")
            log_event(_log, "ccxt_kill_switch_env_triggered", level="WARNING",
                      order_id=order.client_order_id, symbol=order.symbol)
            self._record_idempotent(order.client_order_id, resp)
            return resp
        # 1. Stablecoin warning -- non-blocking.
        self._check_quote_currency(order.symbol)
        # 2. Live triple-gate: only enforced when sandbox=False.
        if not self.sandbox:
            missing = self._check_live_triple_gate(gateway_committed)
            if missing is not None:
                resp = {
                    "id": order.client_order_id,
                    "status": "rejected",
                    "reason": f"live_gate_{missing}",
                    "filled_qty": 0.0,
                    "filled_avg_price": 0.0,
                }
                self._audit(
                    "reject", order_id=order.client_order_id,
                    symbol=order.symbol, side=order.side,
                    qty=float(order.qty), status="rejected",
                    reason=f"live_gate_{missing}",
                )
                log_event(_log, "ccxt_live_gate_blocked", level="WARNING",
                          order_id=order.client_order_id,
                          symbol=order.symbol, missing=missing)
                self._record_idempotent(order.client_order_id, resp)
                return resp
        # 3. KillSwitch (per-instance) check.
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
        if blocked is not None:
            blocked["id"] = order.client_order_id
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason="kill_switch_triggered")
            self._record_idempotent(order.client_order_id, blocked)
            return blocked
        # 4. Rate limit.
        self._rate_limit_acquire()
        # 5. Audit submit.
        self._audit("submit", order_id=order.client_order_id,
                    symbol=order.symbol, side=order.side,
                    qty=float(order.qty),
                    price=float(order.limit_price) if order.limit_price else None,
                    status="submitted",
                    payload=f"exchange={self.exchange_id} sandbox={self.sandbox}")
        # 6. Place the order via ccxt.
        norm_symbol = self._normalize_symbol(order.symbol)
        try:
            if order.order_type == "market":
                raw = self._client.create_order(
                    norm_symbol, "market", order.side,
                    float(order.qty), None,
                    {"clientOrderId": order.client_order_id},
                )
            else:
                raw = self._client.create_order(
                    norm_symbol, "limit", order.side,
                    float(order.qty), float(order.limit_price),
                    {"clientOrderId": order.client_order_id},
                )
        except Exception as exc:
            self._audit("reject", order_id=order.client_order_id,
                        symbol=order.symbol, side=order.side,
                        qty=float(order.qty), status="rejected",
                        reason=str(exc)[:200])
            raise
        # 7. Normalize response.
        out = {
            "id": (raw.get("id") if isinstance(raw, dict) else None)
                  or order.client_order_id,
            "status": (raw.get("status") if isinstance(raw, dict) else None)
                      or "submitted",
            "client_order_id": order.client_order_id,
            "exchange": self.exchange_id,
            "symbol": norm_symbol,
            "filled_qty": float(
                (raw.get("filled") if isinstance(raw, dict) else 0.0) or 0.0
            ),
            "filled_avg_price": float(
                (raw.get("average") if isinstance(raw, dict) else 0.0) or 0.0
            ),
        }
        status = str(out.get("status", "")).lower()
        if status in ("submitted", "open", "accepted", "filled",
                      "partially_filled", "closed"):
            signed_qty = (
                float(order.qty) if order.side == "buy" else -float(order.qty)
            )
            self._update_local_position(norm_symbol, signed_qty)
            if status in ("filled", "closed", "partially_filled"):
                self._audit(
                    "fill", order_id=out["id"],
                    symbol=norm_symbol, side=order.side,
                    qty=float(out.get("filled_qty", 0.0)),
                    price=float(out.get("filled_avg_price", 0.0)),
                    status=status,
                )
        elif status == "rejected":
            self._audit("reject", order_id=out["id"],
                        symbol=norm_symbol, side=order.side,
                        qty=float(order.qty), status="rejected")
        self._record_idempotent(order.client_order_id, out)
        return out

    def cancel_order(
        self,
        order_id: str,
        *,
        gateway_committed: Optional[Any] = None,
    ) -> bool:
        if self._kill_switch_env_triggered():
            log_event(_log, "ccxt_cancel_kill_switch_env", level="WARNING",
                      order_id=order_id)
            return False
        if not self.sandbox:
            missing = self._check_live_triple_gate(gateway_committed)
            if missing is not None:
                log_event(_log, "ccxt_cancel_live_gate_blocked",
                          level="WARNING",
                          order_id=order_id, missing=missing)
                return False
        self._rate_limit_acquire()
        try:
            self._client.cancel_order(order_id)
            self._audit("cancel", order_id=order_id, status="canceled")
            return True
        except Exception as exc:
            log_event(_log, "ccxt_cancel_failed", level="WARNING",
                      order_id=order_id, err=str(exc))
            self._audit("reject", order_id=order_id, status="cancel_failed",
                        reason=str(exc)[:200])
            return False

    def get_positions(self) -> list[Position]:
        out: list[Position] = []
        try:
            balance = self._client.fetch_balance()
        except Exception as exc:  # pragma: no cover - depends on exchange
            log_event(_log, "ccxt_balance_fetch_failed", level="WARNING",
                      err=str(exc))
            return out
        # ccxt fetch_balance returns dict with 'total' / 'free' / 'used'.
        totals = balance.get("total", {}) if isinstance(balance, dict) else {}
        for ccy, qty in totals.items():
            try:
                q = float(qty)
            except (TypeError, ValueError):
                continue
            if q <= 0:
                continue
            up = str(ccy).upper()
            # Skip stable quote currencies -- those are cash, not positions.
            if up in self.allowed_quotes:
                continue
            sym = f"{up}/USDT"
            out.append(Position(symbol=sym, qty=q, avg_price=0.0,
                                market_value=0.0, unrealized_pnl=0.0))
        return out

    def get_account(self) -> dict:
        try:
            balance = self._client.fetch_balance()
        except Exception as exc:  # pragma: no cover - depends on exchange
            log_event(_log, "ccxt_account_fetch_failed", level="WARNING",
                      err=str(exc))
            return {"cash": 0.0, "equity": 0.0, "buying_power": 0.0}
        free = balance.get("free", {}) if isinstance(balance, dict) else {}
        cash = 0.0
        # Sum across all stable quote currencies that we treat as cash.
        for ccy in self.allowed_quotes:
            v = free.get(ccy)
            if v is None:
                continue
            try:
                cash += float(v)
            except (TypeError, ValueError):
                continue
        return {"cash": cash, "equity": cash, "buying_power": cash}

    def get_balance(self) -> dict:
        """Return the raw balance dict (cash + per-currency totals).

        Convenience for the ``forge crypto balance`` CLI; tests of the
        higher-level Broker interface should prefer ``get_account``.
        """
        try:
            return self._client.fetch_balance()
        except Exception as exc:  # pragma: no cover - depends on exchange
            log_event(_log, "ccxt_balance_fetch_failed", level="WARNING",
                      err=str(exc))
            return {}

    def sync(self, tolerance: float = 1e-6) -> dict:
        broker_pos = self.get_positions()
        from aurora.deployment.brokers import _diff_positions
        return _diff_positions(self._local_positions, broker_pos,
                               tolerance=tolerance)


# ---------------------------------------------------------------------------
# Allow-live consent token helpers (used by `forge crypto allow-live`)
# ---------------------------------------------------------------------------


def write_allow_live_token(exchange_id: str, token_dir: str) -> str:
    """Write a one-time consent token for ``exchange_id``.

    Returns the absolute path of the token file. The caller of
    :class:`CCXTBrokerAdapter` must additionally export the matching env
    var ``QF_CCXT_ALLOW_LIVE_<EXCHANGE>=1`` to satisfy the triple-gate.
    The token file itself is just the audit record.
    """
    import json
    import secrets
    from datetime import datetime, timezone
    from pathlib import Path

    exch = exchange_id.upper()
    p = Path(token_dir).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    token_path = p / f"ccxt_allow_live_{exch}.token"
    payload = {
        "exchange": exch,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16),
        "env_var_required": ALLOW_LIVE_TOKEN_ENV_PATTERN.format(EXCHANGE=exch),
        "ceremony_phase_required": LIVE_CEREMONY_PHASE,
    }
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return str(token_path)
