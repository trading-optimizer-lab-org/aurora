"""AgentGateway: stage / commit / push for non-human actors.

Three-step ceremony:

* :meth:`AgentGateway.stage` -- agent submits an :class:`ActionRequest`,
  the gateway authenticates the token, authorizes the request against
  scopes / caps / cooldown, and records a ``staged`` entry in the audit
  trail. Returns a :class:`StagedAction` with a 5-minute expiry.

* :meth:`AgentGateway.commit` -- a human counter-signs the
  ``staged_id`` with a signature derived from
  ``QF_OPERATOR_KEY``. For paper actions the policy may allow
  auto-commit (still audited).

* :meth:`AgentGateway.push` -- finally executes via the broker / data
  layer adapter. Records ``executed`` or ``failed``.

Live-trade ceremony adds three orthogonal gates on top of the cap /
scope checks:

1. ``token.paper_only`` must be False.
2. ``QF_AGENT_LIVE_AUTH=1`` must be set in the process env.
3. An :class:`OOSGuard` with phase ``"agent_live_authorized"`` must
   currently be active on the calling thread.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from quantforge.agent_gateway.audit import (
    AgentAudit, AgentAuditConfig, request_hash,
)
from quantforge.agent_gateway.tokens import (
    AgentToken, READ_SCOPES, TokenScope, sign_payload,
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


class ActionStatus(str, Enum):
    """Lifecycle status of a gateway action."""

    STAGED = "staged"
    COMMITTED = "committed"
    EXECUTED = "executed"
    FAILED = "failed"
    EXPIRED = "expired"
    DENIED = "denied"


@dataclass(frozen=True)
class ActionRequest:
    """Self-contained description of what the agent wants to do.

    The ``kind`` field is a free-form action name (e.g. ``"paper_order"``,
    ``"live_order"``, ``"backtest_is"``, ``"propose_strategy"``). Concrete
    handlers are registered via :meth:`AgentGateway.register_executor`.
    """

    kind: str
    scope: TokenScope
    symbol: Optional[str] = None
    notional_usd: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StagedAction:
    """A request that has passed authn/authz and is awaiting commit."""

    staged_id: str
    token_id: str
    actor: str
    action: ActionRequest
    staged_at: pd.Timestamp
    expires_at: pd.Timestamp
    request_digest: str

    def is_expired(self, now: Optional[pd.Timestamp] = None) -> bool:
        cur = now if now is not None else pd.Timestamp.utcnow().tz_localize(None)
        if cur.tzinfo is not None:
            try:
                cur = cur.tz_localize(None)
            except (TypeError, AttributeError):
                cur = cur.tz_convert(None)
        exp = self.expires_at
        if exp.tzinfo is not None:
            try:
                exp = exp.tz_localize(None)
            except (TypeError, AttributeError):
                exp = exp.tz_convert(None)
        return cur >= exp


@dataclass
class CommittedAction:
    """A staged action a human (or auto-policy) has counter-signed."""

    committed_id: str
    staged: StagedAction
    committed_at: pd.Timestamp
    human_signature: str


@dataclass
class ExecutionResult:
    """Outcome of :meth:`AgentGateway.push`."""

    committed_id: str
    status: ActionStatus
    response: Dict[str, Any]
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass
class GatewayPolicy:
    """Static config knobs that govern gateway behavior.

    Attributes:
        paper_only_default: every newly-issued token starts ``paper_only``
            unless an operator explicitly overrides it.
        require_human_commit_for_live: live trade always needs a human
            signature on commit. Cannot be auto-committed.
        require_human_commit_for_paper: when False, paper actions may be
            auto-committed during ``stage`` (still audited).
        audit_chain_verify_on_startup: when True, ``__init__`` verifies
            the existing audit chain and raises ``RuntimeError`` on any
            tamper detection.
        max_token_lifetime_days: cap on token validity at issue time.
        allow_self_modify: when False, agents cannot use their token to
            modify the gateway / protocol itself.
        staged_action_ttl_seconds: time window between stage and commit.
    """

    paper_only_default: bool = True
    require_human_commit_for_live: bool = True
    require_human_commit_for_paper: bool = False
    audit_chain_verify_on_startup: bool = True
    max_token_lifetime_days: int = 30
    allow_self_modify: bool = False
    staged_action_ttl_seconds: int = 300


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GatewayError(RuntimeError):
    """Base class for AgentGateway errors. Always logged + audited."""


class AuthenticationError(GatewayError):
    """Token signature, expiry, or paper_only violation."""


class AuthorizationError(GatewayError):
    """Scope, allowlist, cap, or cooldown violation."""


class CeremonyError(GatewayError):
    """A required ceremony (env flag, OOSGuard, human sig) is missing."""


class GatewayStateError(GatewayError):
    """Token revoked, action expired, or unknown id."""


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


OPERATOR_KEY_ENV = "QF_OPERATOR_KEY"
LIVE_AUTH_ENV = "QF_AGENT_LIVE_AUTH"
LIVE_CEREMONY_PHASE = "agent_live_authorized"


def _commit_signature(staged_id: str, *, env: str = OPERATOR_KEY_ENV) -> str:
    """Return the expected human-commit hmac for ``staged_id``."""
    raw = os.environ.get(env, "")
    if not raw:
        raise CeremonyError(
            f"{env} is not set; commit cannot be verified"
        )
    return hmac.new(raw.encode("utf-8"), staged_id.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def operator_sign(staged_id: str, *, env: str = OPERATOR_KEY_ENV) -> str:
    """Public helper an operator uses to compute their counter-signature."""
    return _commit_signature(staged_id, env=env)


class AgentGateway:
    """Stateful gateway. Single instance per process is the common case."""

    def __init__(
        self,
        policy: GatewayPolicy,
        audit_path: Path,
        *,
        time_fn: Optional[Callable[[], pd.Timestamp]] = None,
    ) -> None:
        self.policy = policy
        self._audit = AgentAudit(AgentAuditConfig(
            log_path=str(audit_path), mirror_soc2=True,
        ))
        if policy.audit_chain_verify_on_startup:
            report = self._audit.verify_chain()
            if not report["ok"]:
                raise RuntimeError(
                    "Agent gateway audit chain integrity check FAILED at "
                    f"index {report['broken_index']}; refusing to start."
                )
        self._tokens: Dict[str, AgentToken] = {}
        self._revoked: set = set()
        self._staged: Dict[str, StagedAction] = {}
        self._committed: Dict[str, CommittedAction] = {}
        self._last_action_at: Dict[str, pd.Timestamp] = {}
        self._executors: Dict[str, Callable[[CommittedAction], Dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._time_fn = time_fn or self._default_now

    # ------------------------------------------------------------------
    # Time helper (test seam)
    # ------------------------------------------------------------------
    @staticmethod
    def _default_now() -> pd.Timestamp:
        return pd.Timestamp.utcnow().tz_localize(None)

    def _now(self) -> pd.Timestamp:
        return self._time_fn()

    # ------------------------------------------------------------------
    # Token registry
    # ------------------------------------------------------------------
    def register_token(self, token: AgentToken) -> None:
        """Make ``token`` known to the gateway. Required before stage()."""
        if token.is_expired(self._now()):
            raise AuthenticationError(f"token {token.token_id} already expired")
        if not token.verify_signature():
            raise AuthenticationError(
                f"token {token.token_id} signature invalid"
            )
        max_life_days = self.policy.max_token_lifetime_days
        if max_life_days > 0:
            life = pd.Timestamp(token.expires_at) - pd.Timestamp(token.issued_at)
            if life > pd.Timedelta(days=max_life_days):
                raise AuthenticationError(
                    f"token {token.token_id} lifetime exceeds policy "
                    f"({life.days}d > {max_life_days}d)"
                )
        with self._lock:
            self._tokens[token.token_id] = token

    def revoke(self, token_id: str) -> None:
        """Future stage() calls for ``token_id`` will be denied."""
        with self._lock:
            self._revoked.add(token_id)
        self._audit.append(
            actor=self._tokens.get(token_id, _ActorShim(token_id)).actor
            if token_id in self._tokens else "unknown",
            token_id=token_id, action="revoke", scope="-",
            request_hash="-", outcome="approved",
            details={},
        )

    def list_active(self) -> List[AgentToken]:
        """Return all currently registered, non-revoked, non-expired tokens."""
        now = self._now()
        with self._lock:
            return [
                t for tid, t in self._tokens.items()
                if tid not in self._revoked and not t.is_expired(now)
            ]

    def register_executor(
        self, kind: str,
        fn: Callable[[CommittedAction], Dict[str, Any]],
    ) -> None:
        """Wire a concrete executor for a given action ``kind``."""
        self._executors[kind] = fn

    # ------------------------------------------------------------------
    # Authentication / Authorization
    # ------------------------------------------------------------------
    def authenticate(self, token: AgentToken) -> None:
        """Verify signature, expiry, and revocation."""
        if not token.verify_signature():
            raise AuthenticationError("invalid token signature")
        if token.is_expired(self._now()):
            raise AuthenticationError("token expired")
        with self._lock:
            if token.token_id in self._revoked:
                raise AuthenticationError("token revoked")
            if token.token_id not in self._tokens:
                raise AuthenticationError("token not registered")

    def authorize(self, token: AgentToken, action: ActionRequest) -> None:
        """Scope, allowlist, cap, cooldown checks."""
        # Scope
        if not token.has_scope(action.scope):
            raise AuthorizationError(
                f"token lacks scope {action.scope.value}"
            )
        # Self-modify guard
        if not self.policy.allow_self_modify and action.kind in (
            "modify_gateway", "modify_protocol", "issue_token",
        ):
            raise AuthorizationError("self-modification disallowed")
        # Allowlist (only enforced when set + symbol present)
        if action.symbol and token.allowlist_symbols:
            if action.symbol not in token.allowlist_symbols:
                raise AuthorizationError(
                    f"symbol {action.symbol} not in allowlist"
                )
        # Per-order notional cap
        if action.notional_usd < 0:
            raise AuthorizationError("notional_usd cannot be negative")
        if action.notional_usd > token.max_order_notional_usd:
            raise AuthorizationError(
                f"order notional ${action.notional_usd:.2f} exceeds "
                f"per-order cap ${token.max_order_notional_usd:.2f}"
            )
        # Daily aggregate cap (UTC day, sum of executed + staged ahead)
        if action.notional_usd > 0:
            used = self._daily_notional_used(token.token_id)
            if used + action.notional_usd > token.max_daily_notional_usd:
                raise AuthorizationError(
                    f"daily cap exceeded: {used:.2f} + "
                    f"{action.notional_usd:.2f} > "
                    f"{token.max_daily_notional_usd:.2f}"
                )
        # Cooldown
        last = self._last_action_at.get(token.token_id)
        if last is not None and token.cooldown_seconds > 0:
            now = self._now()
            elapsed = (now - last).total_seconds()
            if elapsed < token.cooldown_seconds:
                raise AuthorizationError(
                    f"cooldown active: {elapsed:.2f}s < "
                    f"{token.cooldown_seconds}s"
                )

    # ------------------------------------------------------------------
    # Stage
    # ------------------------------------------------------------------
    def stage(self, token: AgentToken, action: ActionRequest) -> StagedAction:
        """Validate + record audit + return a :class:`StagedAction`.

        Raises :class:`AuthenticationError` / :class:`AuthorizationError`
        / :class:`CeremonyError` on rejection. The rejection itself is
        always audited as ``outcome="denied"``.
        """
        digest = request_hash({
            "kind": action.kind, "scope": action.scope.value,
            "symbol": action.symbol, "notional_usd": action.notional_usd,
            "payload": action.payload,
        })
        try:
            self.authenticate(token)
            self.authorize(token, action)
            if action.scope == TokenScope.LIVE_TRADE:
                self._enforce_live_ceremony(token)
        except GatewayError as exc:
            self._audit.append(
                actor=token.actor, token_id=token.token_id,
                action=f"stage:{action.kind}",
                scope=action.scope.value,
                request_hash=digest, outcome="denied",
                details={"error": str(exc),
                         "error_type": type(exc).__name__},
            )
            raise

        now = self._now()
        ttl = self.policy.staged_action_ttl_seconds
        staged = StagedAction(
            staged_id=uuid.uuid4().hex,
            token_id=token.token_id,
            actor=token.actor,
            action=action,
            staged_at=now,
            expires_at=now + pd.Timedelta(seconds=ttl),
            request_digest=digest,
        )
        with self._lock:
            self._staged[staged.staged_id] = staged
            self._last_action_at[token.token_id] = now
        self._audit.append(
            actor=token.actor, token_id=token.token_id,
            action=f"stage:{action.kind}",
            scope=action.scope.value,
            request_hash=digest, outcome="approved",
            details={
                "staged_id": staged.staged_id,
                "symbol": action.symbol,
                "notional_usd": action.notional_usd,
                "expires_at": staged.expires_at.isoformat(),
            },
        )
        return staged

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------
    def commit(self, staged_id: str,
               human_signature: Optional[str] = None) -> CommittedAction:
        """Counter-sign ``staged_id``. Live actions always require a sig."""
        with self._lock:
            staged = self._staged.get(staged_id)
        if staged is None:
            raise GatewayStateError(f"unknown staged_id {staged_id}")
        if staged.is_expired(self._now()):
            with self._lock:
                self._staged.pop(staged_id, None)
            self._audit.append(
                actor=staged.actor, token_id=staged.token_id,
                action=f"commit:{staged.action.kind}",
                scope=staged.action.scope.value,
                request_hash=staged.request_digest,
                outcome="denied",
                details={"error": "staged action expired"},
            )
            raise GatewayStateError(f"staged action {staged_id} expired")

        is_live = staged.action.scope == TokenScope.LIVE_TRADE
        require_sig = (
            (is_live and self.policy.require_human_commit_for_live)
            or (not is_live and self.policy.require_human_commit_for_paper)
        )
        if require_sig:
            if not human_signature:
                self._audit.append(
                    actor=staged.actor, token_id=staged.token_id,
                    action=f"commit:{staged.action.kind}",
                    scope=staged.action.scope.value,
                    request_hash=staged.request_digest,
                    outcome="denied",
                    details={"error": "missing human signature"},
                )
                raise CeremonyError(
                    "human signature required to commit this action"
                )
            expected = _commit_signature(staged_id)
            if not hmac.compare_digest(human_signature, expected):
                self._audit.append(
                    actor=staged.actor, token_id=staged.token_id,
                    action=f"commit:{staged.action.kind}",
                    scope=staged.action.scope.value,
                    request_hash=staged.request_digest,
                    outcome="denied",
                    details={"error": "invalid human signature"},
                )
                raise CeremonyError("invalid human signature")
            sig = human_signature
        else:
            sig = "auto-commit"

        committed = CommittedAction(
            committed_id=uuid.uuid4().hex,
            staged=staged,
            committed_at=self._now(),
            human_signature=sig,
        )
        with self._lock:
            self._committed[committed.committed_id] = committed
            # The staged record stays in memory for traceability but is
            # marked consumed by removing it from the staging map.
            self._staged.pop(staged_id, None)
        self._audit.append(
            actor=staged.actor, token_id=staged.token_id,
            action=f"commit:{staged.action.kind}",
            scope=staged.action.scope.value,
            request_hash=staged.request_digest,
            outcome="approved",
            details={
                "committed_id": committed.committed_id,
                "staged_id": staged_id,
                "auto_commit": sig == "auto-commit",
            },
        )
        return committed

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------
    def push(self, committed: CommittedAction) -> ExecutionResult:
        """Execute via the registered executor for the action ``kind``."""
        with self._lock:
            stored = self._committed.get(committed.committed_id)
        if stored is None:
            raise GatewayStateError(
                f"unknown committed_id {committed.committed_id}"
            )
        kind = committed.staged.action.kind
        executor = self._executors.get(kind)
        if executor is None:
            self._audit.append(
                actor=committed.staged.actor,
                token_id=committed.staged.token_id,
                action=f"push:{kind}",
                scope=committed.staged.action.scope.value,
                request_hash=committed.staged.request_digest,
                outcome="failed",
                details={
                    "committed_id": committed.committed_id,
                    "error": f"no executor for {kind}",
                },
            )
            return ExecutionResult(
                committed_id=committed.committed_id,
                status=ActionStatus.FAILED,
                response={},
                error=f"no executor for {kind}",
            )
        try:
            response = executor(committed) or {}
        except Exception as exc:  # noqa: BLE001 - we re-emit the message in audit
            self._audit.append(
                actor=committed.staged.actor,
                token_id=committed.staged.token_id,
                action=f"push:{kind}",
                scope=committed.staged.action.scope.value,
                request_hash=committed.staged.request_digest,
                outcome="failed",
                details={
                    "committed_id": committed.committed_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return ExecutionResult(
                committed_id=committed.committed_id,
                status=ActionStatus.FAILED,
                response={},
                error=str(exc),
            )
        self._audit.append(
            actor=committed.staged.actor,
            token_id=committed.staged.token_id,
            action=f"push:{kind}",
            scope=committed.staged.action.scope.value,
            request_hash=committed.staged.request_digest,
            outcome="executed",
            details={
                "committed_id": committed.committed_id,
                "response": response,
            },
        )
        with self._lock:
            self._committed.pop(committed.committed_id, None)
        return ExecutionResult(
            committed_id=committed.committed_id,
            status=ActionStatus.EXECUTED,
            response=response,
        )

    # ------------------------------------------------------------------
    # Live ceremony
    # ------------------------------------------------------------------
    def _enforce_live_ceremony(self, token: AgentToken) -> None:
        """Live trade requires paper_only=False, env flag, and OOSGuard."""
        if token.paper_only:
            raise CeremonyError(
                "paper_only token cannot stage LIVE_TRADE actions"
            )
        if os.environ.get(LIVE_AUTH_ENV, "") != "1":
            raise CeremonyError(
                f"{LIVE_AUTH_ENV} must be set to '1' for live actions"
            )
        # Active OOSGuard check
        try:
            from quantforge.core.data_layer import OOSGuard
        except Exception as exc:
            raise CeremonyError(
                f"cannot import OOSGuard for ceremony check: {exc}"
            ) from exc
        stack = OOSGuard._stack_for_thread()
        if not stack:
            raise CeremonyError(
                "no active OOSGuard on calling thread; "
                "live ceremony requires an explicit unlock"
            )
        active_phase = getattr(stack[-1], "phase", "")
        if active_phase != LIVE_CEREMONY_PHASE:
            raise CeremonyError(
                f"active OOSGuard phase '{active_phase}' "
                f"does not match required '{LIVE_CEREMONY_PHASE}'"
            )

    # ------------------------------------------------------------------
    # Aggregations
    # ------------------------------------------------------------------
    def _daily_notional_used(self, token_id: str) -> float:
        """Sum executed + currently staged notional for ``token_id`` today."""
        today_utc = self._now().strftime("%Y-%m-%d")
        total = 0.0
        for entry in self._audit.find(token_id=token_id):
            ts = entry.get("ts", "")
            if not ts.startswith(today_utc):
                continue
            outcome = entry.get("outcome")
            if outcome not in ("approved", "executed"):
                continue
            details = entry.get("details", {})
            action = entry.get("action", "")
            # Only count stage approvals (avoids double-count vs commit/push,
            # which carry the same staged_id but the same notional too).
            if not action.startswith("stage:"):
                continue
            try:
                total += float(details.get("notional_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
        return total

    # ------------------------------------------------------------------
    # Audit access
    # ------------------------------------------------------------------
    @property
    def audit(self) -> AgentAudit:
        return self._audit


# Helper used by ``revoke`` when the actor name has been forgotten.
@dataclass
class _ActorShim:
    actor: str


__all__ = [
    "ActionRequest",
    "ActionStatus",
    "AgentGateway",
    "CommittedAction",
    "ExecutionResult",
    "GatewayPolicy",
    "StagedAction",
    "AuthenticationError",
    "AuthorizationError",
    "CeremonyError",
    "GatewayStateError",
    "GatewayError",
    "operator_sign",
    "OPERATOR_KEY_ENV",
    "LIVE_AUTH_ENV",
    "LIVE_CEREMONY_PHASE",
]
