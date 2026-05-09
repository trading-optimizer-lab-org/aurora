"""Shared broker infrastructure.

Hosts the abstract :class:`Broker`, the data classes (:class:`Order`,
:class:`Position`, :class:`BrokerConfig`), the risk/audit primitives
(:class:`KillSwitch`, :class:`AuditLog`, :class:`_RateLimiter`),
helpers used by every concrete adapter (:func:`_validate_order`,
:func:`_read_env`, :func:`_import_or_raise`, :func:`_diff_positions`),
and the :class:`ReconciliationError` exception.

Concrete adapters live in their own sibling modules (``paper``,
``alpaca``, ``ib``, ``coinbase``, ``kraken``) and import everything they
need from this base module.
"""
from __future__ import annotations

import copy
import os
import sqlite3
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime as _dt
from datetime import timezone
from typing import Any, Optional

from aurora.core.logging import get_logger, log_event
from aurora.core.sqlite_utils import _setup_sqlite

# Logger keeps the original "deployment.brokers" channel so structured
# events do not change name when the file split landed.
_log = get_logger("deployment.brokers")


# ---------------------------------------------------------------------------
# Hardening exceptions
# ---------------------------------------------------------------------------

class ReconciliationError(Exception):
    """Raised when local and broker state diverge beyond tolerance."""


# ---------------------------------------------------------------------------
# Test-friendly clock lookup
# ---------------------------------------------------------------------------

def _now_utc():
    """Return ``datetime.now(UTC)`` while honouring monkeypatched ``_dt``.

    Tests patch ``aurora.deployment.brokers._dt`` to control the clock used
    by :class:`KillSwitch` and :class:`AuditLog`. After the broker code was
    split into a package, the monkeypatched attribute lives on the package
    module rather than on ``base``. This helper resolves ``_dt`` through
    ``sys.modules`` so the patch keeps applying without forcing every call
    site to import the package eagerly (which would create a circular
    import at module load time).
    """
    pkg = sys.modules.get("aurora.deployment.brokers")
    dt_cls = getattr(pkg, "_dt", _dt) if pkg is not None else _dt
    return dt_cls.now(timezone.utc)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

_VALID_SIDES = ("buy", "sell")
_VALID_ORDER_TYPES = ("market", "limit")
_VALID_TIF = ("day", "gtc", "ioc")


@dataclass
class Order:
    """Standard order across all broker adapters.

    Attributes:
        symbol: ticker, e.g. 'SPY' or 'BTC/USD'.
        qty: positive quantity. Direction encoded in `side`.
        side: 'buy' or 'sell'.
        order_type: 'market' or 'limit'.
        limit_price: required when order_type == 'limit', else ignored.
        time_in_force: 'day', 'gtc', or 'ioc'.
        client_order_id: optional client-supplied id; auto-filled with
            uuid4 hex when None.
    """
    symbol: str
    qty: float
    side: str
    order_type: str
    limit_price: Optional[float] = None
    time_in_force: str = "day"
    client_order_id: Optional[str] = None


@dataclass
class Position:
    """Snapshot of a single position."""
    symbol: str
    qty: float
    avg_price: float
    market_value: float
    unrealized_pnl: float


@dataclass
class BrokerConfig:
    """Static config for a broker adapter.

    Attributes:
        name: one of 'ib', 'alpaca', 'coinbase', 'kraken', 'paper'.
        api_key_env: env var that holds the API key. Never the key itself.
        api_secret_env: env var that holds the API secret.
        base_url: optional broker endpoint override (e.g. paper-api.alpaca.markets).
        paper: True for paper / sandbox endpoints.
        rate_limit_per_minute: max submit_order/cancel_order calls per 60s
            sliding window. Excess calls block (sleep) until the window clears.
    """
    name: str
    api_key_env: Optional[str] = None
    api_secret_env: Optional[str] = None
    base_url: Optional[str] = None
    paper: bool = True
    rate_limit_per_minute: int = 60


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------

class KillSwitch:
    """Risk circuit breaker for live trading.

    When `triggered=True`, all order submissions are rejected at the broker
    layer with a structured error.

    Thread safety: every state read/write of ``triggered``, ``day_start_equity``
    and ``day_start_date`` is serialized through an internal ``threading.Lock``
    so concurrent ``check()``/``arm()``/``disarm()`` callers cannot interleave
    a daily-reset and a trigger evaluation. ``check()`` also exposes a
    ``locked()`` helper that callers (e.g. broker submit paths) can use to
    read the trigger snapshot atomically with the same lock.

    Attributes:
        max_daily_loss_pct: trigger when (equity - day_start_equity) / day_start_equity
            drops below -max_daily_loss_pct (e.g. 0.05 = 5%).
        max_position_qty: trigger if any single position |qty| exceeds this value.
        triggered: armed state. True means orders are blocked.
        day_start_equity: reference equity for daily loss check; set on first
            check() call (or via arm()) and reset by disarm().
        day_start_date: UTC date the day_start_equity was captured. When the
            current UTC date no longer matches, ``check()`` rolls the daily
            reference to the current equity (and clears any prior trigger
            attributable to a previous session) before evaluating the loss.
    """

    def __init__(self,
                 max_daily_loss_pct: float = 0.05,
                 max_position_qty: float = 1_000_000.0,
                 triggered: bool = False,
                 day_start_equity: Optional[float] = None,
                 day_start_date: Optional[_date] = None):
        self.max_daily_loss_pct = float(max_daily_loss_pct)
        self.max_position_qty = float(max_position_qty)
        self.triggered = bool(triggered)
        self.day_start_equity = day_start_equity
        self.day_start_date = day_start_date
        self._lock = threading.RLock()

    def locked(self) -> threading.RLock:
        """Return the internal lock so callers can snapshot state atomically."""
        return self._lock

    def check(self, account: dict, positions: list[Position]) -> bool:
        """Evaluate kill switch conditions. Returns True if triggered.

        Updates self.triggered as side effect. Once True, stays True until
        disarm() OR until the UTC date rolls (auto daily reset). The whole
        operation (date roll + reset + reference-equity update + trigger
        evaluation) runs inside a single critical section so no concurrent
        caller can observe a partially updated state.
        """
        equity = float(account.get("equity", 0.0))
        today = _now_utc().date()
        with self._lock:
            # Daily reset: if the date rolled, reset reference equity and clear
            # any sticky daily-loss trigger so a new session starts clean.
            if self.day_start_date is not None and self.day_start_date != today:
                log_event(_log, "kill_switch_daily_reset",
                          prev_date=str(self.day_start_date),
                          today=str(today),
                          prev_day_start_equity=self.day_start_equity,
                          new_day_start_equity=equity)
                self.day_start_equity = equity
                self.day_start_date = today
                self.triggered = False
            if self.triggered:
                return True
            if self.day_start_equity is None:
                self.day_start_equity = equity
            if self.day_start_date is None:
                self.day_start_date = today
            # Daily loss check
            if self.day_start_equity > 0:
                loss_pct = (self.day_start_equity - equity) / self.day_start_equity
                if loss_pct >= self.max_daily_loss_pct:
                    self.triggered = True
                    log_event(_log, "kill_switch_triggered", level="ERROR",
                              reason="max_daily_loss",
                              loss_pct=loss_pct,
                              threshold=self.max_daily_loss_pct)
                    return True
            # Per-position size check
            for p in positions:
                if abs(p.qty) > self.max_position_qty:
                    self.triggered = True
                    log_event(_log, "kill_switch_triggered", level="ERROR",
                              reason="max_position_qty",
                              symbol=p.symbol, qty=p.qty,
                              threshold=self.max_position_qty)
                    return True
            return False

    def arm(self) -> None:
        """Force-trigger the kill switch (atomic).

        Captures today's UTC date so the daily reset in ``check()`` re-anchors
        the reference equity on the next session boundary. ``day_start_equity``
        is left as None so the next ``check()`` snapshots the live equity at
        that moment.
        """
        with self._lock:
            self.triggered = True
            self.day_start_date = _now_utc().date()
            self.day_start_equity = None
        log_event(_log, "kill_switch_armed", level="WARNING")

    def disarm(self) -> None:
        """Release kill switch and reset daily reference equity (atomic)."""
        with self._lock:
            self.triggered = False
            self.day_start_equity = None
            self.day_start_date = None
        log_event(_log, "kill_switch_disarmed")


# ---------------------------------------------------------------------------
# AuditLog (SQLite)
# ---------------------------------------------------------------------------

class AuditLog:
    """SQLite-backed audit log of broker-level events.

    Schema:
        id INTEGER PRIMARY KEY
        ts TEXT (ISO-8601, UTC, tz-aware)
        event TEXT (submit/cancel/fill/reject/partial_fill)
        order_id TEXT
        symbol TEXT
        side TEXT
        qty REAL
        price REAL
        status TEXT
        reason TEXT
        payload TEXT (raw JSON-ish repr for debug)

    Default db path: audit_<YYYY-MM-DD>.db in current working directory.
    Override via `db_path`. When `db_path` is left at the default and the UTC
    date rolls past midnight, ``record()`` automatically closes the current
    DB and reopens with a fresh dated path so each calendar day lands in its
    own audit file.

    Durability: opens the DB with WAL journaling, ``synchronous=FULL``, and a
    5-second busy timeout so concurrent readers / writers do not corrupt the
    journal.
    """

    def __init__(self, db_path: Optional[str] = None):
        explicit_path = db_path is not None
        if db_path is None:
            db_path = f"audit_{_now_utc().date().isoformat()}.db"
        self.db_path = str(db_path)
        self._explicit_path = bool(explicit_path)
        self._open_date: _date = _now_utc().date()
        self._lock = threading.Lock()
        # Allow cross-thread access; serialize via self._lock.
        self._conn = self._open_connection(self.db_path)

    @staticmethod
    def _open_connection(db_path: str) -> sqlite3.Connection:
        """Open a SQLite connection with durability pragmas and the schema."""
        conn = sqlite3.connect(db_path, check_same_thread=False)
        # Centralized PRAGMA setup: WAL journaling for concurrency,
        # synchronous=FULL for crash safety on the audit log, 5 s busy
        # timeout to absorb writer contention without raising.
        try:
            _setup_sqlite(conn, mode="full")
        except Exception:
            # Pragma failures must not break audit init; fall back silently.
            pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audit ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "ts TEXT NOT NULL,"
            "event TEXT NOT NULL,"
            "order_id TEXT,"
            "symbol TEXT,"
            "side TEXT,"
            "qty REAL,"
            "price REAL,"
            "status TEXT,"
            "reason TEXT,"
            "payload TEXT"
            ")"
        )
        conn.commit()
        return conn

    def _maybe_rotate_locked(self) -> None:
        """Rotate to a new dated DB if the UTC date has rolled.

        Caller must hold self._lock. Skips rotation when the user supplied an
        explicit ``db_path`` since rotating would silently relocate writes.

        Atomicity: a brand-new connection to the rotated path is opened FIRST.
        Only when that succeeds is the old connection swapped out and closed,
        so a failure to open the new file leaves the audit log writing to the
        old (still-open) connection — we never silently lose audit rows.
        """
        if self._explicit_path:
            return
        today = _now_utc().date()
        if today == self._open_date:
            return
        new_path = f"audit_{today.isoformat()}.db"
        try:
            new_conn = self._open_connection(new_path)
        except Exception as exc:
            log_event(_log, "audit_log_rotate_failed", level="ERROR",
                      new_path=new_path, err=str(exc))
            return
        old_conn = self._conn
        self._conn = new_conn
        self.db_path = new_path
        self._open_date = today
        try:
            old_conn.close()
        except Exception:
            pass
        log_event(_log, "audit_log_rotated",
                  new_path=new_path, date=str(today))

    def record(self, event: str, *, order_id: Optional[str] = None,
               symbol: Optional[str] = None, side: Optional[str] = None,
               qty: Optional[float] = None, price: Optional[float] = None,
               status: Optional[str] = None, reason: Optional[str] = None,
               payload: Optional[str] = None) -> None:
        """Insert a single audit row. Thread-safe.

        Uses tz-aware UTC ISO-8601 timestamps. When the calendar day rolls
        past UTC midnight and the audit log was created with a default path,
        the underlying DB file rotates automatically to ``audit_<YYYY-MM-DD>.db``.
        """
        with self._lock:
            self._maybe_rotate_locked()
            # Stamp AFTER rotation so the row's ts always belongs to the day
            # of the file we're writing into (no cross-day leak when a
            # caller stamps just before midnight and rotation crosses).
            ts = _now_utc().isoformat()
            self._conn.execute(
                "INSERT INTO audit (ts, event, order_id, symbol, side, qty, "
                "price, status, reason, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts, event, order_id, symbol, side,
                 float(qty) if qty is not None else None,
                 float(price) if price is not None else None,
                 status, reason, payload),
            )
            self._conn.commit()

    def fetch_all(self) -> list[dict]:
        """Return every audit row as list of dicts (for inspection / tests)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, ts, event, order_id, symbol, side, qty, price, "
                "status, reason, payload FROM audit ORDER BY id"
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Sliding-window per-minute rate limiter.

    Tracks call timestamps. When ``acquire()`` is called and the window
    already holds ``max_per_minute`` entries, the caller is queued in
    arrival order and woken when the oldest entry has expired. Threads are
    served strictly FIFO via a ``threading.Condition`` so the limiter is
    fair under contention (no starvation).

    Waiting uses ``Condition.wait(timeout=...)`` (NOT a busy ``time.sleep``)
    so a freed slot wakes pending threads immediately. Tests that need
    deterministic fake-clock behavior can override the wait via ``wait_fn``;
    ``sleep_fn`` remains a back-compat shim that defaults the wait to a
    plain sleep when ``wait_fn`` is not supplied.
    """

    def __init__(self, max_per_minute: int, window_seconds: float = 60.0,
                 sleep_fn=time.sleep, time_fn=time.monotonic,
                 wait_fn=None):
        self.max_per_minute = max(0, int(max_per_minute))
        self.window = float(window_seconds)
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._waiters: deque[int] = deque()
        self._next_ticket = 0
        self._sleep = sleep_fn
        self._now = time_fn
        self._wait_fn = wait_fn

    def _has_slot_locked(self, now: float, ticket: int) -> bool:
        # Drop expired timestamps and report whether a slot is open for the
        # given waiter. Caller must hold self._lock.
        while self._timestamps and (now - self._timestamps[0]) >= self.window:
            self._timestamps.popleft()
        head_ticket = self._waiters[0] if self._waiters else None
        if head_ticket is not None and head_ticket != ticket:
            return False
        return len(self._timestamps) < self.max_per_minute

    def _wait_locked(self, timeout: float) -> float:
        """Wait up to ``timeout`` seconds while holding the condition.

        Default: ``self._cond.wait(timeout=...)`` — a notify from a peer
        wakes us immediately so freed slots aren't held idle for the full
        timeout. When ``wait_fn`` was supplied at construction, it is used
        instead (caller owns lock release/reacquire). When the user
        overrode ``sleep_fn`` away from the default ``time.sleep`` we
        treat it as a wait hook too, so deterministic tests with fake
        clocks see their sleep_fn called instead of blocking on a real
        condition variable. Returns the actual seconds slept.
        """
        if timeout <= 0:
            return 0.0
        custom_wait = self._wait_fn
        if custom_wait is None and self._sleep is not time.sleep:
            custom_wait = self._sleep
        if custom_wait is not None:
            # Custom wait hook owns lock release/reacquire semantics.
            self._cond.release()
            try:
                custom_wait(timeout)
            finally:
                self._cond.acquire()
            return float(timeout)
        self._cond.wait(timeout=timeout)
        return float(timeout)

    def acquire(self) -> float:
        """Block until a call slot is available. Returns slept seconds.

        FIFO fairness is enforced by a ticket queue: each caller takes a
        ticket on entry and only the head-of-line ticket is allowed to
        consume the next free slot. The wait happens under the condition
        lock via ``Condition.wait`` so a slot freed by another thread
        immediately notifies and wakes us — no busy spinning.
        """
        if self.max_per_minute <= 0:
            return 0.0
        slept_total = 0.0

        # Reserve a FIFO ticket so concurrent waiters cannot reorder.
        with self._lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiters.append(ticket)

        try:
            with self._cond:
                while True:
                    now = self._now()
                    if self._has_slot_locked(now, ticket):
                        # Slot is open and we are head-of-line: take it.
                        self._timestamps.append(now)
                        try:
                            self._waiters.popleft()
                        except IndexError:
                            pass
                        # Wake the next waiter so it can re-evaluate.
                        self._cond.notify_all()
                        return slept_total
                    # Compute wait deadline. If we are not head-of-line we
                    # only need to wait until the head-of-line wakes us; the
                    # head-of-line ticket waits for the oldest timestamp to
                    # expire.
                    if self._waiters and self._waiters[0] == ticket:
                        wait = self.window - (now - self._timestamps[0])
                    else:
                        # Not head-of-line: wait for a notification or the
                        # full window as an upper bound.
                        wait = self.window
                    if wait <= 0:
                        # Spurious case: re-check loop without waiting.
                        continue
                    slept = self._wait_locked(wait)
                    slept_total += slept
        except BaseException:
            # On any abnormal exit, drop our ticket so we don't block peers.
            with self._lock:
                try:
                    self._waiters.remove(ticket)
                except ValueError:
                    pass
                self._cond.notify_all()
            raise


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_order(order: Order) -> Order:
    """Validate Order fields and fill client_order_id if missing.

    Returns the (same) order with a guaranteed client_order_id. Raises
    ValueError on bad input. The order is mutated in place for ergonomics
    but a fresh Order dataclass instance also works.
    """
    if not isinstance(order, Order):
        raise ValueError(f"order must be an Order, got {type(order).__name__}")
    if not order.symbol or not isinstance(order.symbol, str):
        raise ValueError(f"order.symbol must be non-empty str, got {order.symbol!r}")
    if order.qty is None or order.qty <= 0:
        raise ValueError(f"order.qty must be > 0, got {order.qty}")
    if order.side not in _VALID_SIDES:
        raise ValueError(
            f"order.side must be one of {_VALID_SIDES}, got {order.side!r}"
        )
    if order.order_type not in _VALID_ORDER_TYPES:
        raise ValueError(
            f"order.order_type must be one of {_VALID_ORDER_TYPES}, "
            f"got {order.order_type!r}"
        )
    if order.time_in_force not in _VALID_TIF:
        raise ValueError(
            f"order.time_in_force must be one of {_VALID_TIF}, "
            f"got {order.time_in_force!r}"
        )
    if order.order_type == "limit":
        if order.limit_price is None or order.limit_price <= 0:
            raise ValueError(
                f"limit order requires limit_price > 0, got {order.limit_price}"
            )
    if order.client_order_id is None:
        order.client_order_id = uuid.uuid4().hex
    return order


def _read_env(var_name: Optional[str]) -> Optional[str]:
    """Resolve env var name to its value. Returns None if name is None."""
    if var_name is None:
        return None
    return os.getenv(var_name)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Broker(ABC):
    """Abstract broker interface. All adapters share this surface.

    Concrete adapters should set ``self.kill_switch``, ``self.audit_log``,
    and ``self._rate_limiter`` in their ``__init__``. The base class helper
    ``_audit`` plus the per-adapter gate block (kill switch, freeze, idempotency,
    rate limiter) rely on them.

    Idempotency: ``_seen_client_order_ids`` tracks responses keyed by
    ``client_order_id``. Concrete ``submit_order`` implementations MUST
    consult this dict before forwarding to the broker so retried submissions
    sharing the same client_order_id return the prior response instead of
    placing a duplicate order.

    Local position tracking: ``_local_positions`` maps symbol -> float qty
    that the local process believes is held. Concrete adapters update it on
    successful ``submit_order`` calls and consult it inside ``sync()`` to
    compute real diffs against the broker view.
    """

    # Default attributes; set by subclasses.
    kill_switch: Optional[KillSwitch] = None
    audit_log: Optional["AuditLog"] = None
    _rate_limiter: Optional[_RateLimiter] = None

    @abstractmethod
    def submit_order(self, order: Order) -> dict:
        """Submit an order. Returns broker response (id, status, ...)."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order_id. Returns True on success."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return current open positions."""

    @abstractmethod
    def get_account(self) -> dict:
        """Return account snapshot (cash, equity, ...)."""

    @abstractmethod
    def sync(self, tolerance: float = 1e-6) -> dict:
        """Reconcile local state with broker. Returns diffs.

        Args:
            tolerance: minimum absolute quantity (broker-side) below which
                a position is considered noise rather than a real divergence.

        Result shape:
            {
                'missing_local': [Position, ...],   # broker has, local lacks
                'missing_broker': [str, ...],       # local has, broker lacks
                'qty_mismatch': [{symbol, local, broker}, ...],
            }
        Empty lists mean fully consistent.
        """

    # ------------------------------------------------------------------
    # Default hardening hooks (subclasses can override)
    # ------------------------------------------------------------------

    def partial_fill_event(self, order_id: str, filled_qty: float,
                           remaining_qty: float, price: float) -> None:
        """Record a partial fill from an external broker callback.

        Default implementation logs and audits the event. Subclasses that
        track open orders may override to update local state.
        """
        log_event(_log, "partial_fill", order_id=order_id,
                  filled_qty=filled_qty, remaining_qty=remaining_qty,
                  price=price)
        if self.audit_log is not None:
            self.audit_log.record(
                "partial_fill", order_id=order_id, qty=float(filled_qty),
                price=float(price), status="partially_filled",
                payload=f"remaining={remaining_qty}",
            )

    def reconcile(self, tolerance: float = 1e-6) -> dict:
        """Verify local state matches broker. Auto-correct or raise.

        Default behavior: if `sync()` reports any non-empty diff list,
        raise ReconciliationError. Subclasses (e.g. PaperBroker) override.
        ``tolerance`` is forwarded to ``sync()`` so dust-sized broker
        positions never trigger spurious reconciliation errors.
        Falls back to a no-arg ``sync()`` when the override does not
        accept a tolerance kwarg (legacy / monkeypatched implementations).
        """
        try:
            diff = self.sync(tolerance=tolerance)
        except TypeError:
            diff = self.sync()
        if (diff.get("missing_local") or diff.get("missing_broker")
                or diff.get("qty_mismatch")):
            raise ReconciliationError(
                f"Broker/local state diverge: {diff}"
            )
        return diff

    # ------------------------------------------------------------------
    # Internal helpers used by concrete adapters
    # ------------------------------------------------------------------

    def _kill_switch_blocked(self) -> Optional[dict]:
        """If the kill switch is triggered, return the rejection dict."""
        ks = self.kill_switch
        if ks is None or not ks.triggered:
            return None
        return {
            "id": None,
            "status": "rejected",
            "reason": "kill_switch_triggered",
            "filled_qty": 0.0,
            "filled_avg_price": 0.0,
        }

    def _rate_limit_acquire(self) -> None:
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()

    def _audit(self, event: str, **kw) -> None:
        """Best-effort audit hook. Never propagates exceptions.

        Audit failures are logged at ERROR level; the broker continues so
        an audit-store outage cannot wedge live trading.
        """
        if self.audit_log is None:
            return
        try:
            self.audit_log.record(event, **kw)
        except Exception as exc:
            log_event(_log, "audit_record_failed", level="ERROR",
                      audit_event=event, err=str(exc))

    # ------------------------------------------------------------------
    # Idempotency / local-state helpers (used by concrete adapters)
    # ------------------------------------------------------------------

    # Cap on the number of cached client_order_id -> response entries. Old
    # entries are evicted in FIFO order with an emitted log so memory use
    # stays bounded even when the process runs for months at >50k orders.
    IDEMPOTENT_CACHE_MAX = 50_000

    def _idempotent_response(self, client_order_id: Optional[str]) -> Optional[dict]:
        """Return the prior response for ``client_order_id`` if seen, else None.

        Concrete ``submit_order`` should call this BEFORE forwarding to the
        broker. Returning a cached response avoids duplicate live orders on
        retry. Returns a deep copy so callers cannot mutate the cached
        response and corrupt the next idempotency hit.
        """
        if client_order_id is None:
            return None
        seen = getattr(self, "_seen_client_order_ids", None)
        if not seen:
            return None
        cached = seen.get(client_order_id)
        if cached is None:
            return None
        log_event(_log, "submit_order_idempotent_hit",
                  client_order_id=client_order_id)
        return copy.deepcopy(cached)

    def _record_idempotent(self, client_order_id: Optional[str],
                           response: dict) -> None:
        """Cache ``response`` so a future retry with the same id is a no-op.

        Stored as a deep copy to defend against caller-side mutation. Uses an
        ``OrderedDict`` capped at ``IDEMPOTENT_CACHE_MAX``; oldest entries
        are evicted FIFO with an emitted log so the operator notices when
        the cache pressure is real (signal the broker is being hammered).
        """
        if client_order_id is None:
            return
        seen = getattr(self, "_seen_client_order_ids", None)
        if not isinstance(seen, OrderedDict):
            # Migrate from any prior dict instance lazily so subclasses /
            # callers that monkeypatched the field get a bounded cache too.
            new_cache: OrderedDict[str, dict] = OrderedDict()
            if isinstance(seen, dict):
                for k, v in seen.items():
                    new_cache[k] = v
            seen = new_cache
            self._seen_client_order_ids = seen
        # Re-insert keeps insertion-order LRU semantics on overwrite.
        if client_order_id in seen:
            seen.pop(client_order_id, None)
        seen[client_order_id] = copy.deepcopy(response)
        max_entries = int(getattr(self, "IDEMPOTENT_CACHE_MAX", 50_000))
        while len(seen) > max_entries:
            evicted_key, _ = seen.popitem(last=False)
            log_event(_log, "idempotent_cache_evicted", level="WARNING",
                      client_order_id=evicted_key,
                      cache_size=len(seen),
                      max_entries=max_entries)

    def _update_local_position(self, symbol: str, signed_qty: float) -> None:
        """Apply a signed delta to local position tracking."""
        if symbol is None:
            return
        loc = getattr(self, "_local_positions", None)
        if loc is None:
            loc = {}
            self._local_positions = loc
        loc[symbol] = float(loc.get(symbol, 0.0)) + float(signed_qty)
        if abs(loc[symbol]) < 1e-12:
            loc.pop(symbol, None)


# ---------------------------------------------------------------------------
# Helper for adapters that need lazy SDK loading
# ---------------------------------------------------------------------------

def _import_or_raise(module_name: str, install_hint: str):
    """Import `module_name`. Raise ImportError with install hint if missing."""
    try:
        return __import__(module_name)
    except ImportError as e:
        raise ImportError(
            f"Optional broker SDK '{module_name}' is not installed. "
            f"Install with: {install_hint}"
        ) from e


# ---------------------------------------------------------------------------
# Position-diff helper used by all live adapters
# ---------------------------------------------------------------------------

def _diff_positions(local: dict[str, float],
                    broker_positions: list[Position],
                    tolerance: float = 1e-6) -> dict:
    """Return diff between locally-tracked positions and broker snapshot.

    - missing_local : symbol+qty broker has but local lacks (or zero locally).
    - missing_broker: symbols local thinks it holds but broker reports none.
    - qty_mismatch  : both sides hold the symbol but qty differs > tolerance.
    """
    broker_by_sym: dict[str, Position] = {p.symbol: p for p in broker_positions}
    missing_local: list[Position] = []
    missing_broker: list[str] = []
    qty_mismatch: list[dict] = []

    for sym, bp in broker_by_sym.items():
        local_qty = float(local.get(sym, 0.0))
        broker_qty = float(bp.qty)
        # Skip dust on both sides — broker positions below tolerance are
        # noise (residual fractional fills, rounding) not real divergence.
        if abs(local_qty) <= tolerance and abs(broker_qty) <= tolerance:
            continue
        if abs(local_qty) <= tolerance and abs(broker_qty) > tolerance:
            missing_local.append(bp)
        elif abs(local_qty - broker_qty) > tolerance:
            qty_mismatch.append({
                "symbol": sym,
                "local": local_qty,
                "broker": broker_qty,
            })

    for sym, qty in local.items():
        if abs(float(qty)) <= tolerance:
            continue
        if sym not in broker_by_sym:
            missing_broker.append(sym)

    return {
        "missing_local": missing_local,
        "missing_broker": missing_broker,
        "qty_mismatch": qty_mismatch,
    }


# Re-export typing helpers commonly used by adapter modules so they can
# ``from .base import Any, Optional, ...`` instead of duplicating imports.
__all__ = [
    "ABC",
    "Any",
    "AuditLog",
    "Broker",
    "BrokerConfig",
    "KillSwitch",
    "OrderedDict",
    "Optional",
    "Order",
    "Position",
    "ReconciliationError",
    "_RateLimiter",
    "_diff_positions",
    "_import_or_raise",
    "_log",
    "_now_utc",
    "_read_env",
    "_validate_order",
    "abstractmethod",
    "copy",
    "dataclass",
    "deque",
    "log_event",
    "_dt",
    "_date",
    "timezone",
]
