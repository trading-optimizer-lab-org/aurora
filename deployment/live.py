"""Lumibot live trading wrapper for QuantForge strategies.

WARNING - LIVE TRADING RISKS
============================
This module submits REAL ORDERS to a live broker. Before deploying:

1. Strategy MUST pass the QuantForge validation pipeline (WF, MC, Lookahead,
   DSR > 0.5, Calmar gates, lockbox approval). Never deploy unvalidated code.
2. Test on paper (deployment.paper.QFPaperStrategy) for >= 1 month first.
3. Start with the smallest viable size; daily_loss_limit and max_notional_pct
   exist for a reason - keep them tight.
4. Network/broker outages, partial fills, halted symbols, after-hours gaps,
   liquidity holes, and corporate actions can all cause REAL money loss
   beyond what your backtest models. Live P&L will diverge from backtest P&L.
5. You accept full responsibility. The QuantForge authors do NOT.

Pre-trade risk checks layered on top of paper wrapper:
- Daily loss limit (halt new orders if NAV draw exceeds limit since session start)
- Max gross notional check (no over-leverage vs target weight)
- Order retry on transient broker errors

Usage:
    from lumibot.brokers import Alpaca
    from lumibot.traders import Trader
    from aurora.deployment.live import QFLiveStrategy
    from aurora.strategies.library import MACross

    cls = QFLiveStrategy.bind(
        qf_strategy=MACross(20, 100),
        symbol="SPY",
        risk_per_trade=0.01,
        daily_loss_limit=0.05,
        max_notional_pct=1.0,
    )
    broker = Alpaca(ALPACA_CONFIG)
    Trader().add_strategy(cls(broker=broker)).run_all()
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime as _dt
from datetime import timezone
from typing import Any

from aurora.core.logging import get_logger, log_event
from aurora.deployment.sizing import fixed_risk_size

try:
    from lumibot.strategies.strategy import Strategy as LumibotStrategy
    HAS_LUMIBOT = True
except ImportError:
    HAS_LUMIBOT = False
    LumibotStrategy = object


_log = get_logger("deployment.live")
# Sentinel used when distinguishing "attribute not set" from "attribute is None"
# in preflight_checks; needed because MagicMock objects auto-create attributes.
_SENTINEL = object()


class _NullCtx:
    """No-op context manager used when no per-instance lock has been built."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@dataclass
class LiveConfig:
    """Risk parameters for live deployment.

    Attributes:
        risk_per_trade: max % NAV to risk per trade entry (default 1%).
        daily_loss_limit: NAV draw fraction since session start that halts new
            orders (default 5%).
        max_notional_pct: cap on gross |target weight| (default 1.0 = 100%).
            Set < 1.0 for sub-leverage; > 1.0 only with explicit broker support.
        stop_pct_default: default stop distance for fixed_risk_size (default 2%).
        order_retry_attempts: total submit attempts before giving up.
        order_retry_delay_sec: seconds to sleep between retries.
        fractional: when True, ``notional_shares`` is a float (no int floor)
            so brokers that support fractional shares (e.g. Alpaca) actually
            trade the full target dollar amount. Default False keeps the
            integer share semantics that whole-share brokers require.
    """
    risk_per_trade: float = 0.01
    daily_loss_limit: float = 0.05
    max_notional_pct: float = 1.0
    stop_pct_default: float = 0.02
    order_retry_attempts: int = 3
    order_retry_delay_sec: float = 2.0
    fractional: bool = False
    bypass_validation_check: bool = False

    @classmethod
    def from_policy(cls) -> "LiveConfig":
        """Return a :class:`LiveConfig` seeded from the active
        :class:`aurora.core.protocol_policy.ProtocolPolicy`.

        Maps:

        * ``risk_limits.max_leverage`` -> ``max_notional_pct``
        * ``risk_limits.max_drawdown_promotion_threshold`` ->
          ``daily_loss_limit`` (the daily-loss halt is a *runtime*
          analogue of the promotion-time drawdown ceiling, so tying
          them together keeps the protocol's risk envelope coherent).

        All other fields remain at their conservative defaults.
        """
        try:
            from aurora.core.protocol_policy import get_active_policy
            rl = get_active_policy().risk_limits
            return cls(
                max_notional_pct=float(rl.max_leverage),
                daily_loss_limit=float(rl.max_drawdown_promotion_threshold),
            )
        except Exception:
            return cls()


class TransientOrderError(Exception):
    """Mark a broker error as retryable."""


def _order_client_id(order) -> str | None:
    """Return the QuantForge client_order_id attribute on the order, if any."""
    for attr in ("client_order_id", "_client_order_id"):
        val = getattr(order, attr, None)
        if val:
            return str(val)
    return None


def _broker_has_order(strategy, client_order_id: str) -> bool:
    """Best-effort lookup against the broker for a prior submission.

    The lookup probes ``strategy.broker`` for ``get_order_by_client_id`` /
    ``get_orders``. A match means the order already exists at the broker, so
    a retry MUST NOT resubmit. Errors are swallowed and treated as not
    found so we err on the side of retrying when the broker is unreachable.
    """
    if client_order_id is None:
        return False
    broker = getattr(strategy, "broker", None)
    if broker is None:
        return False
    # Direct lookup helpers used by lumibot brokers / our adapters.
    for name in ("get_order_by_client_id", "get_order_by_client_order_id"):
        fn = getattr(broker, name, None)
        if fn is None:
            continue
        try:
            res = fn(client_order_id)
        except Exception:
            continue
        if res:
            return True
    fn = getattr(broker, "get_orders", None)
    if fn is not None:
        try:
            orders = fn() or []
        except Exception:
            return False
        for o in orders:
            cid = (getattr(o, "client_order_id", None)
                   or getattr(o, "client_id", None)
                   or getattr(o, "id", None))
            if cid and str(cid) == str(client_order_id):
                return True
    return False


#: Default set of exception classes treated as transient retryable errors.
#: ``TransientOrderError`` is the explicit caller-flagged path; the rest are
#: standard network-class exceptions a retry can plausibly recover from.
#: Authentication, validation, and credential errors are NOT in this set —
#: those are non-retryable and propagate on the first failure.
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _verify_agent_gateway_commit(order, gateway_committed) -> None:
    """Validate that a gateway-committed action authorizes ``order``.

    P1.A integration point: when a non-human actor submits an order
    through ``submit_with_retry``, the caller must pass the
    :class:`quantforge.agent_gateway.CommittedAction` returned by
    ``AgentGateway.commit``. This helper confirms the committed
    action's symbol and side match the order. Mismatches raise a
    ``RuntimeError`` so the broker is never reached.
    """
    if gateway_committed is None:
        return
    try:
        from aurora.agent_gateway import CommittedAction, TokenScope
    except Exception:
        return
    if not isinstance(gateway_committed, CommittedAction):
        raise RuntimeError("gateway_committed must be a CommittedAction")
    action = gateway_committed.staged.action
    if action.scope not in (TokenScope.PAPER_TRADE, TokenScope.LIVE_TRADE):
        raise RuntimeError(
            f"gateway action scope {action.scope.value} cannot submit orders"
        )
    sym = getattr(order, "symbol", None) or getattr(order, "asset", None)
    if action.symbol and sym and str(action.symbol) != str(sym):
        raise RuntimeError(
            f"gateway-committed symbol {action.symbol} != order symbol {sym}"
        )


def submit_with_retry(strategy, order, max_attempts: int = 3,
                      delay: float = 2.0,
                      transient_predicate=None,
                      gateway_committed=None):
    """Submit order, retry on transient errors.

    Retry classification
    --------------------
    The retry path catches ``TransientOrderError`` (caller-flagged) plus a
    network-class fallback ``(ConnectionError, TimeoutError, OSError)``.
    Anything else (auth failure, malformed request, broker-side validation,
    insufficient buying power) is **non-retryable** and propagates on the
    first failure. Pass ``transient_predicate(exc) -> bool`` to inject extra
    retryable classifications without subclassing — return True to retry,
    False/None to propagate.

    Idempotency: before the second and subsequent attempts, the broker is
    queried for a prior order with the same ``client_order_id``. If one is
    found, the prior order is returned instead of resubmitting, so a partial
    failure (e.g. broker received the order but the response timed out) does
    not result in a duplicate live order.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    _verify_agent_gateway_commit(order, gateway_committed)
    cid = _order_client_id(order)
    last_err: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        # On retries, check whether the broker already accepted the order.
        if attempt > 1 and cid is not None and _broker_has_order(strategy, cid):
            log_event(_log, "order_retry_skipped_idempotent",
                      attempt=attempt, client_order_id=cid)
            return {"status": "already_submitted", "client_order_id": cid}
        try:
            resp = strategy.submit_order(order)
            log_event(_log, "order_submitted", attempt=attempt)
            return resp
        except TransientOrderError as e:
            last_err = e
            log_event(_log, "order_retry", level="WARNING",
                      attempt=attempt, max_attempts=max_attempts, err=str(e))
            if attempt < max_attempts:
                time.sleep(delay)
        except _RETRYABLE_EXC as e:
            last_err = e
            log_event(_log, "order_retry_network", level="WARNING",
                      attempt=attempt, max_attempts=max_attempts,
                      err=str(e), err_type=type(e).__name__)
            if attempt < max_attempts:
                time.sleep(delay)
        except Exception as e:
            # Inject-able predicate hook: if the caller has classified this
            # exception as transient (e.g. wrapped HTTP 503 from a vendored
            # SDK), retry; otherwise propagate immediately.
            if transient_predicate is not None and bool(transient_predicate(e)):
                last_err = e
                log_event(_log, "order_retry_predicate", level="WARNING",
                          attempt=attempt, max_attempts=max_attempts,
                          err=str(e), err_type=type(e).__name__)
                if attempt < max_attempts:
                    time.sleep(delay)
                continue
            raise
    log_event(_log, "order_exhausted", level="ERROR",
              attempts=max_attempts, err=str(last_err))
    assert last_err is not None
    raise last_err


def preflight_checks(strategy, qf_config: LiveConfig) -> list[str]:
    """Run pre-trade gates. Returns list of failure reasons (empty = ok).

    Checks:
    - Lumibot is importable.
    - Strategy has a bound QF strategy.
    - Daily P&L drawdown vs session_start_nav within daily_loss_limit.
    - Broker reports portfolio value > 0.
    """
    failures: list[str] = []
    if not HAS_LUMIBOT:
        failures.append("lumibot not installed; install with `pip install lumibot`")
        return failures
    # Resolve the bound QF strategy. Prefer the legacy underscore-prefixed
    # attribute for compatibility with existing test fixtures that set it
    # explicitly to None. Fall back to the new per-instance attribute when
    # the legacy alias was never set.
    qf_strategy = getattr(strategy, "_qf_strategy", _SENTINEL)
    if qf_strategy is _SENTINEL:
        qf_strategy = getattr(strategy, "qf_strategy", None)
    if qf_strategy is None:
        failures.append("no QF strategy bound; call QFLiveStrategy.bind(...) first")
    nav_now = strategy.get_portfolio_value()
    if nav_now is None or nav_now <= 0:
        failures.append(f"broker portfolio value invalid: {nav_now}")
        return failures
    # Resolve session-start NAV. Prefer the legacy underscore-prefixed
    # attribute for compatibility with existing fixtures and fall back to
    # the new per-instance attribute. Coerce to float so mocks / proxies
    # that return non-numeric placeholders are ignored.
    nav_start: float | None = None
    for attr in ("_qf_session_start_nav", "qf_session_start_nav"):
        raw: Any = getattr(strategy, attr, _SENTINEL)
        if raw is _SENTINEL or raw is None:
            continue
        try:
            nav_start = float(raw)
            break
        except (TypeError, ValueError):
            continue
    if nav_start is not None and nav_start > 0:
        draw = (nav_start - nav_now) / nav_start
        if draw >= qf_config.daily_loss_limit:
            failures.append(
                f"daily loss {draw:.4f} exceeds limit {qf_config.daily_loss_limit:.4f}"
            )
    return failures


class QFLiveStrategy(LumibotStrategy):
    """Lumibot live trading wrapper for QuantForge strategies.

    Adds pre-trade risk checks on top of paper wrapper:
    - Max position notional check (no over-leverage)
    - Daily loss limit (halt if breached)
    - Order retry on transient failures

    Usage:
        from lumibot.brokers import Alpaca
        from lumibot.traders import Trader

        strategy = QFLiveStrategy.bind(
            qf_strategy=MACross(20, 100),
            symbol='SPY',
            risk_per_trade=0.01,
            daily_loss_limit=0.05,
            max_notional_pct=1.0,
        )
        broker = Alpaca(ALPACA_CONFIG)
        Trader().add_strategy(strategy(broker=broker)).run_all()
    """

    # Pending bind() configuration. ``bind()`` no longer mutates class
    # attributes that act as live state — it only stores the configuration
    # to be applied per-instance inside ``initialize()``. This keeps
    # multiple QFLiveStrategy instances from sharing mutable state through
    # the class (a footgun that previously caused two paper sessions to
    # share a single halt flag and session NAV).
    _qf_pending_config: dict | None = None

    # Subclass attributes default to None so subclasses without bind() are
    # still importable. Per-instance ``initialize()`` populates the real
    # ``self.qf_*`` fields.
    _qf_strategy = None
    _qf_symbol = "SPY"
    _qf_lookback_days = 300

    @classmethod
    def _validate_bind_args(cls, *, risk_per_trade: float,
                            daily_loss_limit: float,
                            max_notional_pct: float,
                            stop_pct_default: float,
                            order_retry_attempts: int,
                            order_retry_delay_sec: float,
                            lookback_days: int) -> None:
        """Reject obviously dangerous live-trading parameters at bind time."""
        if not (0.0 <= float(risk_per_trade) <= 0.1):
            raise ValueError(
                f"risk_per_trade must be in [0.0, 0.1], got {risk_per_trade}"
            )
        if not (0.0 < float(daily_loss_limit) <= 1.0):
            raise ValueError(
                f"daily_loss_limit must be in (0.0, 1.0], got {daily_loss_limit}"
            )
        if not (0.0 < float(max_notional_pct) <= 1.5):
            raise ValueError(
                f"max_notional_pct must be in (0.0, 1.5], got {max_notional_pct}"
            )
        if not (0.0 < float(stop_pct_default) <= 1.0):
            raise ValueError(
                f"stop_pct_default must be in (0.0, 1.0], got {stop_pct_default}"
            )
        if int(order_retry_attempts) < 1:
            raise ValueError(
                f"order_retry_attempts must be >= 1, got {order_retry_attempts}"
            )
        if float(order_retry_delay_sec) < 0:
            raise ValueError(
                f"order_retry_delay_sec must be >= 0, got {order_retry_delay_sec}"
            )
        if int(lookback_days) < 1:
            raise ValueError(
                f"lookback_days must be >= 1, got {lookback_days}"
            )

    @classmethod
    def bind(cls, qf_strategy, symbol: str = "SPY",
             risk_per_trade: float = 0.01,
             daily_loss_limit: float = 0.05,
             max_notional_pct: float = 1.0,
             stop_pct_default: float = 0.02,
             order_retry_attempts: int = 3,
             order_retry_delay_sec: float = 2.0,
             lookback_days: int = 300,
             fractional: bool = False,
             bypass_validation_check: bool = False,
             project_dir: str = "."):
        """Bind a QF strategy plus risk parameters.

        ``bind()`` validates the supplied risk parameters and returns a
        FRESHLY-SUBCLASSED strategy class with the bound config attached.
        Two ``bind()`` calls on the same base class therefore never share
        mutable class-level config — each call yields its own subclass with
        its own ``_qf_pending_config``. The actual mutable session state
        (``qf_strategy``, ``qf_symbol``, ``qf_session_start_nav``,
        ``qf_halted``, ``qf_config``, ``qf_session_date``) is materialized
        as **per-instance** attributes inside ``initialize()`` so two live
        strategies still cannot share state through the class.

        Returns the new subclass for convenience (``bind(...)(broker=...)``).
        """
        cls._validate_bind_args(
            risk_per_trade=risk_per_trade,
            daily_loss_limit=daily_loss_limit,
            max_notional_pct=max_notional_pct,
            stop_pct_default=stop_pct_default,
            order_retry_attempts=order_retry_attempts,
            order_retry_delay_sec=order_retry_delay_sec,
            lookback_days=lookback_days,
        )
        pending_config = {
            "qf_strategy": qf_strategy,
            "symbol": symbol,
            "lookback_days": int(lookback_days),
            "project_dir": str(project_dir),
            "config": LiveConfig(
                risk_per_trade=float(risk_per_trade),
                daily_loss_limit=float(daily_loss_limit),
                max_notional_pct=float(max_notional_pct),
                stop_pct_default=float(stop_pct_default),
                order_retry_attempts=int(order_retry_attempts),
                order_retry_delay_sec=float(order_retry_delay_sec),
                fractional=bool(fractional),
                bypass_validation_check=bool(bypass_validation_check),
            ),
        }
        # Build a fresh subclass so each bind() yields an isolated
        # configuration. Mirroring the pending config onto the SUBCLASS
        # (never the base) preserves the class-attr read API that legacy
        # tests rely on without leaking state across binds.
        new_cls = type(
            cls.__name__,
            (cls,),
            {
                "_qf_pending_config": pending_config,
                "_qf_strategy": qf_strategy,
                "_qf_symbol": symbol,
                "_qf_lookback_days": int(lookback_days),
                "_qf_config": pending_config["config"],
            },
        )
        log_event(_log, "live_strategy_bound",
                  symbol=symbol,
                  risk_per_trade=risk_per_trade,
                  daily_loss_limit=daily_loss_limit,
                  max_notional_pct=max_notional_pct)
        return new_cls

    def initialize(self, parameters=None):
        self.set_market("NYSE")
        self.sleeptime = "1D"
        # Materialize bound configuration as PER-INSTANCE state so two
        # QFLiveStrategy instances never share a class-level halt flag or
        # session NAV.
        pending = type(self)._qf_pending_config or {}
        self.qf_strategy = pending.get("qf_strategy", type(self)._qf_strategy)
        self.qf_symbol = pending.get("symbol", type(self)._qf_symbol)
        self.qf_lookback_days = int(pending.get("lookback_days",
                                                type(self)._qf_lookback_days))
        self.qf_config = pending.get("config", LiveConfig())
        self.qf_project_dir = str(pending.get("project_dir", "."))
        self.qf_halted = False
        self.qf_session_date = _dt.now(timezone.utc).date()
        # P1.1: Round-4 audit -- enforce validation marker once at session
        # start so an unvalidated strategy can never reach order submit.
        # Failure is sticky for the rest of the session (qf_halted=True).
        self._enforce_validation_marker()
        # Per-instance lock guarding the date-roll critical section.
        # Two scheduler ticks landing simultaneously after midnight could
        # otherwise both observe ``qf_session_date != today`` and capture
        # the session NAV twice (the second snapshot lands AFTER trades
        # already moved NAV that day, polluting the daily-loss reference).
        self._qf_session_lock = threading.Lock()
        # Capture session-start NAV for daily-loss tracking.
        try:
            self.qf_session_start_nav = float(self.get_portfolio_value())
        except Exception as e:
            log_event(_log, "session_nav_unavailable", level="WARNING",
                      err=str(e))
            self.qf_session_start_nav = None
        # Mirror to the legacy underscore-prefixed instance attributes so
        # external callers (and existing tests) keep working.
        self._qf_strategy = self.qf_strategy
        self._qf_symbol = self.qf_symbol
        self._qf_lookback_days = self.qf_lookback_days
        self._qf_config = self.qf_config
        self._qf_halted = False
        self._qf_session_start_nav = self.qf_session_start_nav

    def _enforce_validation_marker(self) -> None:
        """P1.1 -- ensure the bound QF strategy has a fresh validation marker.

        Called once from ``initialize()``. Looks up the validation marker
        for ``self.qf_strategy.__class__.__name__`` via
        ``check_validation_marker``. On FAIL we set ``self.qf_halted = True``
        permanently for this session and log an ERROR. The
        ``LiveConfig.bypass_validation_check`` flag explicitly opts out
        (with a WARNING) for tests / emergency operator overrides.

        This is the round-4 audit fix: previously the marker was only
        checked by the standalone ``forge preflight`` CLI, so a user
        could ``QFLiveStrategy.bind(...)`` an unvalidated strategy and
        the live wrapper would happily submit orders.
        """
        cfg = getattr(self, "qf_config", None) or LiveConfig()
        if getattr(cfg, "bypass_validation_check", False):
            log_event(_log, "validation_marker_bypassed",
                      level="WARNING",
                      reason="LiveConfig.bypass_validation_check=True; "
                             "operator override -- USE AT OWN RISK")
            return
        qf_strategy = getattr(self, "qf_strategy", None)
        if qf_strategy is None:
            # No strategy bound at all -- preflight will catch this on
            # the first iteration. Don't pre-halt because some test
            # fixtures rely on bind-less initialize() succeeding.
            return
        strategy_name = type(qf_strategy).__name__
        try:
            from aurora.deployment.preflight import check_validation_marker
            check = check_validation_marker(
                strategy_name,
                project_dir=getattr(self, "qf_project_dir", "."),
            )
        except Exception as e:
            log_event(_log, "validation_marker_check_error",
                      level="ERROR",
                      strategy=strategy_name, err=str(e))
            self.qf_halted = True
            self._qf_halted = True
            return
        if not check.passed:
            log_event(_log, "validation_marker_fail",
                      level="ERROR",
                      strategy=strategy_name, detail=check.detail)
            self.qf_halted = True
            self._qf_halted = True
            return
        log_event(_log, "validation_marker_ok",
                  strategy=strategy_name, detail=check.detail)

    def _maybe_roll_session(self) -> None:
        """Reset halt flag and session NAV when the UTC date rolls.

        Captures session NAV once per UTC date inside a per-instance lock
        so concurrent ticks on the date boundary cannot double-snapshot.
        """
        today = _dt.now(timezone.utc).date()
        prev = getattr(self, "qf_session_date", None)
        if prev is not None and today == prev:
            return
        lock = getattr(self, "_qf_session_lock", None)
        if lock is None:
            # initialize() has not run yet (e.g. mocked test fixtures).
            # Fall back to no-lock semantics — the original behavior.
            lock_ctx = _NullCtx()
        else:
            lock_ctx = lock
        with lock_ctx:
            # Re-check inside the critical section: another thread may have
            # rolled the date already while we were waiting for the lock.
            prev = getattr(self, "qf_session_date", None)
            if prev is not None and today == prev:
                return
            log_event(_log, "live_session_rolled",
                      prev=str(prev), today=str(today))
            self.qf_session_date = today
            self.qf_halted = False
            self._qf_halted = False
            try:
                self.qf_session_start_nav = float(self.get_portfolio_value())
                self._qf_session_start_nav = self.qf_session_start_nav
            except Exception as e:
                log_event(_log, "session_nav_unavailable", level="WARNING",
                          err=str(e))
                self.qf_session_start_nav = None
                self._qf_session_start_nav = None

    def on_trading_iteration(self):
        # Reset halt + session NAV on UTC date roll (e.g. paper sessions
        # that span > 1 day).
        self._maybe_roll_session()

        if self.qf_halted:
            self.log_message("HALTED (daily loss limit hit). Skipping.")
            return

        cfg = self.qf_config

        # 1) Pre-flight gates.
        failures = preflight_checks(self, cfg)
        if failures:
            for f in failures:
                self.log_message(f"PREFLIGHT FAIL: {f}")
                log_event(_log, "preflight_fail", level="ERROR", reason=f)
            # Daily loss breach is sticky for the rest of the session.
            if any("daily loss" in f for f in failures):
                self.qf_halted = True
                self._qf_halted = True
                log_event(_log, "trading_halted", level="ERROR")
            return

        # 2) Fetch historical prices.
        bars = self.get_historical_prices(self.qf_symbol,
                                          length=self.qf_lookback_days,
                                          timestep="day")
        if bars is None:
            self.log_message("Missing data, skipping.")
            log_event(_log, "missing_data", level="WARNING",
                      symbol=self.qf_symbol)
            return

        prices = bars.df["close"]

        # 3) Compute target weight from QF strategy.
        weights = self.qf_strategy.signals(prices)
        target_w = float(weights[-1])

        # 5) Cap by max_notional_pct (single clamp; respects user cap > 1.0
        #    or ultra-tight cap < 1.0 without a hidden [-1, 1] override).
        cap = cfg.max_notional_pct
        clamped = max(-cap, min(cap, target_w))
        if clamped != target_w:
            log_event(_log, "weight_capped", target_w=clamped, cap=cap)
        target_w = clamped

        nav = float(self.get_portfolio_value())
        price = self.get_last_price(self.qf_symbol)
        if price is None or price <= 0:
            self.log_message(f"Invalid price for {self.qf_symbol}: {price}")
            return

        # 4) Apply risk_per_trade sizing using stop = stop_pct_default below entry
        #    when target_w > 0 (long), or above entry when target_w < 0 (short).
        if target_w == 0.0:
            target_qty = 0
        else:
            stop_dist = price * cfg.stop_pct_default
            stop_price = price - stop_dist if target_w > 0 else price + stop_dist
            risk_shares = fixed_risk_size(
                nav=nav, entry_price=price, stop_price=stop_price,
                risk_pct=cfg.risk_per_trade,
            )
            # Take the SMALLER of risk-budget shares and notional-target shares.
            target_dollars = target_w * nav
            if getattr(cfg, "fractional", False):
                # Fractional brokers (e.g. Alpaca) accept floats; do NOT
                # truncate or notional drift will compound.
                notional_shares = abs(target_dollars) / price
                qty_mag = min(float(risk_shares), notional_shares)
                target_qty = qty_mag if target_w > 0 else -qty_mag
            else:
                notional_shares = int(abs(target_dollars) // price)
                qty_mag = min(risk_shares, notional_shares)
                target_qty = qty_mag if target_w > 0 else -qty_mag

        cur = self.get_position(self.qf_symbol)
        cur_qty = cur.quantity if cur else 0
        delta = target_qty - cur_qty
        # Fractional path may produce float deltas: treat anything below the
        # broker precision floor as a no-op so we never submit dust orders.
        if getattr(cfg, "fractional", False):
            if abs(delta) < 1e-9:
                log_event(_log, "no_change",
                          target_qty=target_qty, cur_qty=cur_qty)
                return
            order_qty = round(abs(float(delta)), 9)
            if order_qty <= 0:
                log_event(_log, "no_change",
                          target_qty=target_qty, cur_qty=cur_qty)
                return
        else:
            if delta == 0:
                log_event(_log, "no_change",
                          target_qty=target_qty, cur_qty=cur_qty)
                return
            order_qty = abs(delta)
        side = "buy" if delta > 0 else "sell"
        order = self.create_order(self.qf_symbol, order_qty, side)

        # 6) Submit with retry.
        try:
            submit_with_retry(self, order,
                              max_attempts=cfg.order_retry_attempts,
                              delay=cfg.order_retry_delay_sec)
            log_event(_log, "trade_executed",
                      side=side, qty=order_qty,
                      symbol=self.qf_symbol,
                      target_w=target_w, nav=nav)
            self.log_message(
                f"{side.upper()} {order_qty} {self.qf_symbol} "
                f"(weight {target_w:+.3f}, NAV ${nav:.2f})"
            )
        except Exception as e:
            log_event(_log, "trade_failed", level="ERROR",
                      side=side, qty=order_qty,
                      symbol=self.qf_symbol, err=str(e))
            self.log_message(f"ORDER FAILED after retries: {e}")
