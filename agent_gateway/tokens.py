"""Scoped, signed tokens for non-human actors.

Each token grants a frozen set of :class:`TokenScope` permissions to a
single actor (LLM model id, scheduled job name, etc). Tokens are signed
with HMAC-SHA256 against the server secret loaded from the
``QF_GATEWAY_SECRET`` environment variable.

Tokens carry hard caps on per-order notional, daily notional, and a
cooldown floor so a runaway actor cannot drain the account. The
``paper_only`` flag overrides :data:`TokenScope.LIVE_TRADE` regardless
of how the token was issued.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional

import pandas as pd


# Aurora canonical name (R23). Legacy QF_GATEWAY_SECRET still honoured via
# aurora_env() during the shim window (removed in v1.6).
SERVER_SECRET_ENV = "AU_GATEWAY_SECRET"
SERVER_SECRET_ENV_LEGACY = "QF_GATEWAY_SECRET"


def _server_secret() -> bytes:
    """Return the server signing secret as bytes.

    Raises ``RuntimeError`` if the env var is unset or empty so the
    gateway fails loud instead of silently signing tokens with an
    empty key.
    """
    from aurora.core.env_compat import aurora_env
    raw = aurora_env(SERVER_SECRET_ENV, SERVER_SECRET_ENV_LEGACY) or ""
    if not raw:
        raise RuntimeError(
            f"{SERVER_SECRET_ENV} is not set. AgentGateway refuses to "
            "issue or verify tokens without a server signing secret."
        )
    return raw.encode("utf-8")


class TokenScope(str, Enum):
    """Bounded scope set. Inherits ``str`` so JSON round-trip is trivial."""

    READ_DATA = "read_data"
    READ_REPORTS = "read_reports"
    PROPOSE_STRATEGY = "propose"
    RUN_BACKTEST_IS = "backtest_is"
    RUN_VALIDATION_OOS_DEV = "valid_oos_dev"
    PAPER_TRADE = "paper_trade"
    LIVE_TRADE = "live_trade"


READ_SCOPES: FrozenSet[TokenScope] = frozenset({
    TokenScope.READ_DATA,
    TokenScope.READ_REPORTS,
})


@dataclass(frozen=True)
class AgentToken:
    """Frozen, signed capability token issued to a non-human actor.

    Attributes:
        token_id: uuid4 hex identifier.
        actor: free-form actor name (LLM model id, cron job slug, ...).
        scopes: frozenset of granted :class:`TokenScope` values.
        issued_at: UTC issue time as ``pd.Timestamp``.
        expires_at: UTC expiry time. ``is_expired()`` checks against
            ``pd.Timestamp.utcnow()``.
        allowlist_symbols: empty frozenset means "any symbol". Only
            consulted for read scopes; trade scopes always validate.
        max_order_notional_usd: hard cap per single order.
        max_daily_notional_usd: rolling daily cap (UTC). The gateway
            aggregates across all committed orders for the token within
            the calendar UTC day.
        cooldown_seconds: minimum seconds between any two stage()
            calls for the same token.
        paper_only: when True, :data:`TokenScope.LIVE_TRADE` is denied
            even if the token nominally carries that scope.
        signature: hex hmac-sha256 of canonical token payload.
    """

    token_id: str
    actor: str
    scopes: FrozenSet[TokenScope]
    issued_at: pd.Timestamp
    expires_at: pd.Timestamp
    allowlist_symbols: FrozenSet[str]
    max_order_notional_usd: float
    max_daily_notional_usd: float
    cooldown_seconds: int
    paper_only: bool
    signature: str

    # ------------------------------------------------------------------
    # Canonicalization
    # ------------------------------------------------------------------
    def _canonical_payload(self) -> Dict[str, Any]:
        """Return the deterministic dict hashed to produce ``signature``.

        ``signature`` itself is NEVER part of the canonical payload, since
        a self-referential signature cannot be verified.
        """
        return {
            "token_id": self.token_id,
            "actor": self.actor,
            "scopes": sorted(s.value for s in self.scopes),
            "issued_at": pd.Timestamp(self.issued_at).isoformat(),
            "expires_at": pd.Timestamp(self.expires_at).isoformat(),
            "allowlist_symbols": sorted(self.allowlist_symbols),
            "max_order_notional_usd": float(self.max_order_notional_usd),
            "max_daily_notional_usd": float(self.max_daily_notional_usd),
            "cooldown_seconds": int(self.cooldown_seconds),
            "paper_only": bool(self.paper_only),
        }

    # ------------------------------------------------------------------
    # Verification helpers
    # ------------------------------------------------------------------
    def expected_signature(self) -> str:
        """Recompute the signature using the server secret."""
        payload = json.dumps(
            self._canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hmac.new(_server_secret(), payload, hashlib.sha256).hexdigest()

    def verify_signature(self) -> bool:
        """Constant-time comparison of stored vs recomputed signature."""
        return hmac.compare_digest(self.signature, self.expected_signature())

    def is_expired(self, now: Optional[pd.Timestamp] = None) -> bool:
        """True iff ``now`` (or current UTC) is past ``expires_at``."""
        cur = now if now is not None else pd.Timestamp.utcnow().tz_localize(None)
        # Normalize both sides to tz-naive UTC for comparison.
        exp = pd.Timestamp(self.expires_at)
        if exp.tzinfo is not None:
            exp = exp.tz_convert(None) if exp.tz is not None else exp
            try:
                exp = exp.tz_localize(None)
            except (TypeError, AttributeError):
                pass
        cur_naive = cur
        if cur_naive.tzinfo is not None:
            try:
                cur_naive = cur_naive.tz_localize(None)
            except (TypeError, AttributeError):
                cur_naive = cur_naive.tz_convert(None)
        return cur_naive >= exp

    def has_scope(self, scope: TokenScope) -> bool:
        """``LIVE_TRADE`` is always denied when ``paper_only`` is set."""
        if scope == TokenScope.LIVE_TRADE and self.paper_only:
            return False
        return scope in self.scopes

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        d = dict(self._canonical_payload())
        d["signature"] = self.signature
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentToken":
        return cls(
            token_id=str(data["token_id"]),
            actor=str(data["actor"]),
            scopes=frozenset(TokenScope(s) for s in data["scopes"]),
            issued_at=pd.Timestamp(data["issued_at"]),
            expires_at=pd.Timestamp(data["expires_at"]),
            allowlist_symbols=frozenset(data.get("allowlist_symbols") or []),
            max_order_notional_usd=float(data["max_order_notional_usd"]),
            max_daily_notional_usd=float(data["max_daily_notional_usd"]),
            cooldown_seconds=int(data["cooldown_seconds"]),
            paper_only=bool(data["paper_only"]),
            signature=str(data["signature"]),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def issue_token(
    *,
    actor: str,
    scopes: FrozenSet[TokenScope],
    expires_in_days: int,
    allowlist_symbols: Optional[FrozenSet[str]] = None,
    max_order_notional_usd: float = 10_000.0,
    max_daily_notional_usd: float = 50_000.0,
    cooldown_seconds: int = 5,
    paper_only: bool = True,
    issued_at: Optional[pd.Timestamp] = None,
) -> AgentToken:
    """Mint a fresh signed :class:`AgentToken`.

    Args:
        actor: actor name (LLM model id, cron job slug, ...).
        scopes: frozenset of :class:`TokenScope` to grant.
        expires_in_days: token lifetime in days from ``issued_at``.
        allowlist_symbols: optional symbol allowlist. Empty means "any".
        max_order_notional_usd: per-order cap in USD.
        max_daily_notional_usd: rolling 24h UTC cap in USD.
        cooldown_seconds: minimum seconds between actions.
        paper_only: when True, ``LIVE_TRADE`` is denied even if granted.
        issued_at: override issue time (test hook).

    Returns:
        A signed :class:`AgentToken`.
    """
    if expires_in_days <= 0:
        raise ValueError("expires_in_days must be positive")
    if max_order_notional_usd < 0 or max_daily_notional_usd < 0:
        raise ValueError("notional caps must be non-negative")
    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be non-negative")

    issued = issued_at or pd.Timestamp.utcnow().tz_localize(None)
    if isinstance(issued, pd.Timestamp) and issued.tzinfo is not None:
        try:
            issued = issued.tz_localize(None)
        except (TypeError, AttributeError):
            issued = issued.tz_convert(None)
    expires = issued + pd.Timedelta(days=int(expires_in_days))
    scope_set = frozenset(scopes)
    allow = frozenset(allowlist_symbols or [])

    scaffold = AgentToken(
        token_id=uuid.uuid4().hex,
        actor=actor,
        scopes=scope_set,
        issued_at=issued,
        expires_at=expires,
        allowlist_symbols=allow,
        max_order_notional_usd=float(max_order_notional_usd),
        max_daily_notional_usd=float(max_daily_notional_usd),
        cooldown_seconds=int(cooldown_seconds),
        paper_only=bool(paper_only),
        signature="",
    )
    return replace(scaffold, signature=scaffold.expected_signature())


def sign_payload(payload: str, *, secret_env: str = SERVER_SECRET_ENV) -> str:
    """Return hex hmac-sha256 of ``payload`` using the env-loaded secret.

    Used by the operator counter-sign step (``commit``) so the operator
    side reuses the same primitive without depending on the dataclass
    layout.
    """
    from aurora.core.env_compat import aurora_env
    legacy = SERVER_SECRET_ENV_LEGACY if secret_env == SERVER_SECRET_ENV else None
    raw = aurora_env(secret_env, legacy) or ""
    if not raw:
        raise RuntimeError(f"{secret_env} is not set")
    return hmac.new(raw.encode("utf-8"), payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


__all__ = [
    "AgentToken",
    "TokenScope",
    "READ_SCOPES",
    "SERVER_SECRET_ENV",
    "issue_token",
    "sign_payload",
]
