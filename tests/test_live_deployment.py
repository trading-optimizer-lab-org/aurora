"""Tests for aurora.deployment.live (Lumibot live trading wrapper).

All broker interactions are mocked — no real orders are submitted, lumibot is
not required.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aurora.deployment import live
from aurora.deployment.live import (
    LiveConfig,
    QFLiveStrategy,
    TransientOrderError,
    preflight_checks,
    submit_with_retry,
)


# ---------------------------------------------------------------------------
# LiveConfig
# ---------------------------------------------------------------------------

def test_config_defaults():
    """LiveConfig defaults are sensible for live trading."""
    c = LiveConfig()
    assert c.risk_per_trade == 0.01
    assert c.daily_loss_limit == 0.05
    assert c.max_notional_pct == 1.0
    assert c.stop_pct_default == 0.02
    assert c.order_retry_attempts == 3
    assert c.order_retry_delay_sec == 2.0
    # Sanity bounds.
    assert 0.0 < c.risk_per_trade < 0.1
    assert 0.0 < c.daily_loss_limit < 0.5
    assert c.order_retry_attempts >= 1


# ---------------------------------------------------------------------------
# bind()
# ---------------------------------------------------------------------------

def test_bind_returns_class():
    """QFLiveStrategy.bind() returns a fresh subclass with bound state.

    bind() now manufactures a brand-new subclass per call so two binds
    cannot share class-level config. The returned class must still be
    issubclass(..., QFLiveStrategy) and expose all bound attributes.
    """
    qf = MagicMock()
    qf.signals = MagicMock(return_value=[0.5])

    cls = QFLiveStrategy.bind(
        qf_strategy=qf,
        symbol="QQQ",
        risk_per_trade=0.02,
        daily_loss_limit=0.03,
        max_notional_pct=0.8,
    )
    assert issubclass(cls, QFLiveStrategy)
    assert cls._qf_strategy is qf
    assert cls._qf_symbol == "QQQ"
    assert isinstance(cls._qf_config, LiveConfig)
    assert cls._qf_config.risk_per_trade == 0.02
    assert cls._qf_config.daily_loss_limit == 0.03
    assert cls._qf_config.max_notional_pct == 0.8


def test_bind_isolates_per_call_config():
    """Two bind() calls produce distinct subclasses; one's config does not
    bleed into the other (issue 9)."""
    qf_a = MagicMock()
    qf_a.signals = MagicMock(return_value=[0.5])
    qf_b = MagicMock()
    qf_b.signals = MagicMock(return_value=[0.0])

    cls_a = QFLiveStrategy.bind(qf_strategy=qf_a, symbol="AAA",
                                risk_per_trade=0.01,
                                daily_loss_limit=0.02,
                                max_notional_pct=0.5)
    cls_b = QFLiveStrategy.bind(qf_strategy=qf_b, symbol="BBB",
                                risk_per_trade=0.03,
                                daily_loss_limit=0.04,
                                max_notional_pct=0.9)

    assert cls_a is not cls_b
    assert cls_a._qf_symbol == "AAA"
    assert cls_b._qf_symbol == "BBB"
    assert cls_a._qf_config.risk_per_trade == 0.01
    assert cls_b._qf_config.risk_per_trade == 0.03
    # Calling bind() on cls_b again must not mutate cls_a.
    assert cls_a._qf_strategy is qf_a
    assert cls_b._qf_strategy is qf_b


# ---------------------------------------------------------------------------
# preflight_checks
# ---------------------------------------------------------------------------

def test_preflight_no_lumibot(monkeypatch):
    """When lumibot unavailable, returns clear error."""
    monkeypatch.setattr(live, "HAS_LUMIBOT", False)
    strat = MagicMock()
    failures = preflight_checks(strat, LiveConfig())
    assert failures, "expected non-empty failure list"
    assert any("lumibot" in f.lower() for f in failures)


def test_preflight_no_qf_bound(monkeypatch):
    """No bound QF strategy raises a preflight failure."""
    monkeypatch.setattr(live, "HAS_LUMIBOT", True)
    strat = MagicMock()
    strat._qf_strategy = None
    strat._qf_session_start_nav = 100_000.0
    strat.get_portfolio_value = MagicMock(return_value=100_000.0)
    failures = preflight_checks(strat, LiveConfig())
    assert any("qf strategy" in f.lower() or "bind" in f.lower() for f in failures)


def test_preflight_daily_loss_breach(monkeypatch):
    """If NAV drew more than daily_loss_limit, preflight fails."""
    monkeypatch.setattr(live, "HAS_LUMIBOT", True)
    strat = MagicMock()
    strat._qf_strategy = MagicMock()
    strat._qf_session_start_nav = 100_000.0
    strat.get_portfolio_value = MagicMock(return_value=94_000.0)  # -6%
    failures = preflight_checks(strat, LiveConfig(daily_loss_limit=0.05))
    assert any("daily loss" in f.lower() for f in failures)


def test_preflight_ok(monkeypatch):
    """Healthy state returns empty failure list."""
    monkeypatch.setattr(live, "HAS_LUMIBOT", True)
    strat = MagicMock()
    strat._qf_strategy = MagicMock()
    strat._qf_session_start_nav = 100_000.0
    strat.get_portfolio_value = MagicMock(return_value=99_000.0)  # -1%, ok
    failures = preflight_checks(strat, LiveConfig(daily_loss_limit=0.05))
    assert failures == []


# ---------------------------------------------------------------------------
# submit_with_retry
# ---------------------------------------------------------------------------

def test_submit_with_retry_succeeds_first():
    """Mock that returns ok on first call → 1 attempt."""
    strat = MagicMock()
    strat.submit_order = MagicMock(return_value="OK")
    out = submit_with_retry(strat, order="ORDER", max_attempts=3, delay=0.0)
    assert out == "OK"
    assert strat.submit_order.call_count == 1


def test_submit_with_retry_succeeds_second():
    """Mock fails once with TransientOrderError, then ok → 2 attempts."""
    strat = MagicMock()
    strat.submit_order = MagicMock(side_effect=[
        TransientOrderError("rate limited"),
        "OK",
    ])
    out = submit_with_retry(strat, order="ORDER", max_attempts=3, delay=0.0)
    assert out == "OK"
    assert strat.submit_order.call_count == 2


def test_submit_with_retry_exhausted():
    """Always-failing mock raises TransientOrderError after max_attempts."""
    strat = MagicMock()
    strat.submit_order = MagicMock(side_effect=TransientOrderError("broker down"))
    with pytest.raises(TransientOrderError):
        submit_with_retry(strat, order="ORDER", max_attempts=3, delay=0.0)
    assert strat.submit_order.call_count == 3


def test_submit_with_retry_propagates_non_transient():
    """Non-transient exceptions are NOT retried."""
    strat = MagicMock()
    strat.submit_order = MagicMock(side_effect=ValueError("bad order"))
    with pytest.raises(ValueError):
        submit_with_retry(strat, order="ORDER", max_attempts=3, delay=0.0)
    assert strat.submit_order.call_count == 1


def test_submit_with_retry_invalid_attempts():
    strat = MagicMock()
    with pytest.raises(ValueError):
        submit_with_retry(strat, order="ORDER", max_attempts=0, delay=0.0)


# ---------------------------------------------------------------------------
# Per-instance state isolation (issue 10)
# ---------------------------------------------------------------------------

def test_two_qflive_strategies_isolated_state(monkeypatch):
    """Two QFLiveStrategy instances must NOT share halt flag or session NAV.

    The original implementation stored ``_qf_halted`` / ``_qf_session_start_nav``
    as class-level attributes, so flipping one instance's halt flag broke
    the other instance. After the fix, ``initialize()`` materializes both
    fields per-instance.
    """
    monkeypatch.setattr(live, "HAS_LUMIBOT", True)

    qf = MagicMock()
    qf.signals = MagicMock(return_value=[0.0])
    cls = QFLiveStrategy.bind(qf_strategy=qf, symbol="SPY",
                              risk_per_trade=0.01,
                              daily_loss_limit=0.05,
                              max_notional_pct=1.0,
                              # Round-4: bypass the validation-marker
                              # gate; this test is about per-instance
                              # state isolation, not validation.
                              bypass_validation_check=True)

    # Build two bare instances (skip Lumibot's __init__ entirely).
    a = object.__new__(cls)
    b = object.__new__(cls)
    # Stub lumibot helpers used inside initialize().
    for inst in (a, b):
        inst.set_market = MagicMock()
        inst.sleeptime = None
        inst.get_portfolio_value = MagicMock(return_value=100_000.0)

    a.initialize()
    b.initialize()

    a.qf_halted = True
    a.qf_session_start_nav = 50_000.0

    # Mutating ``a`` MUST NOT affect ``b``.
    assert b.qf_halted is False
    assert b.qf_session_start_nav == pytest.approx(100_000.0)


# ---------------------------------------------------------------------------
# Halt flag resets per session (issue 11)
# ---------------------------------------------------------------------------

def test_halt_flag_resets_per_session(monkeypatch):
    """When the UTC date rolls between iterations, the halted flag clears
    at the top of on_trading_iteration via _maybe_roll_session()."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timezone

    fake_today = [_date(2026, 5, 7)]

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return _dt(fake_today[0].year, fake_today[0].month,
                       fake_today[0].day, 12, 0, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(live, "_dt", _FakeDT)

    cls = QFLiveStrategy
    inst = object.__new__(cls)
    inst.qf_session_date = _date(2026, 5, 7)
    inst.qf_halted = True
    inst.qf_session_start_nav = 100_000.0
    inst._qf_halted = True
    inst._qf_session_start_nav = 100_000.0
    inst.get_portfolio_value = MagicMock(return_value=99_000.0)

    # Same day -> halt remains.
    inst._maybe_roll_session()
    assert inst.qf_halted is True

    # Roll the day -> halt clears and session NAV refreshes.
    fake_today[0] = _date(2026, 5, 8)
    inst._maybe_roll_session()
    assert inst.qf_halted is False
    assert inst._qf_halted is False
    assert inst.qf_session_start_nav == pytest.approx(99_000.0)


# ---------------------------------------------------------------------------
# Idempotent retry guard (issue 12)
# ---------------------------------------------------------------------------

def test_submit_with_retry_no_double_submit_on_partial_failure():
    """If the first attempt times out but the broker actually accepted the
    order, the second attempt MUST detect the prior submission via the
    broker's get_order_by_client_id() / get_orders() lookup and return
    instead of double-submitting."""
    cid = "qf-cid-42"

    class _Broker:
        def __init__(self):
            self.lookup_calls = 0

        def get_order_by_client_id(self, client_id):
            self.lookup_calls += 1
            if str(client_id) == cid:
                return {"client_order_id": cid, "status": "accepted"}
            return None

    class _Order:
        client_order_id = cid

    class _Strat:
        broker = _Broker()
        submit_count = 0

        def submit_order(self, order):
            type(self).submit_count += 1
            from aurora.deployment.live import TransientOrderError
            raise TransientOrderError("first submit timed out")

    strat = _Strat()
    out = submit_with_retry(strat, _Order, max_attempts=3, delay=0.0)
    # Exactly one submit_order call: the second attempt was skipped because
    # the broker already had the order.
    assert _Strat.submit_count == 1
    assert strat.broker.lookup_calls >= 1
    assert out["status"] == "already_submitted"


# ---------------------------------------------------------------------------
# bind() input validation (issue 22)
# ---------------------------------------------------------------------------

def test_bind_rejects_out_of_range_inputs():
    qf = MagicMock()
    qf.signals = MagicMock(return_value=[0.0])
    # risk_per_trade out of range
    with pytest.raises(ValueError):
        QFLiveStrategy.bind(qf_strategy=qf, risk_per_trade=0.5)
    with pytest.raises(ValueError):
        QFLiveStrategy.bind(qf_strategy=qf, risk_per_trade=-0.01)
    # daily_loss_limit out of range
    with pytest.raises(ValueError):
        QFLiveStrategy.bind(qf_strategy=qf, daily_loss_limit=0.0)
    with pytest.raises(ValueError):
        QFLiveStrategy.bind(qf_strategy=qf, daily_loss_limit=2.0)
    # max_notional_pct out of range
    with pytest.raises(ValueError):
        QFLiveStrategy.bind(qf_strategy=qf, max_notional_pct=0.0)
    with pytest.raises(ValueError):
        QFLiveStrategy.bind(qf_strategy=qf, max_notional_pct=2.0)
    # Valid bind still works after invalid attempts. bind() now returns a
    # fresh subclass per call (issue 9), so check via issubclass.
    cls = QFLiveStrategy.bind(qf_strategy=qf, risk_per_trade=0.02,
                              daily_loss_limit=0.05, max_notional_pct=0.9)
    assert issubclass(cls, QFLiveStrategy)
