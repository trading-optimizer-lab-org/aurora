"""Phase 3 (Candidate A) tests: event replay, reconciliation, fill models, TCA."""
from __future__ import annotations

import math

import pytest

from aurora.analytics.tca import TCAResult, compute_tca
from aurora.execution.events import (
    BrokerEvent,
    CancelRequested,
    CommissionReported,
    OrderAcknowledged,
    OrderCancelled,
    OrderCreated,
    OrderFilled,
    OrderPartiallyFilled,
    OrderSubmitted,
)
from aurora.execution.fill_models import (
    FillResult,
    LimitOrderFillModel,
    MarketOrderFillModel,
    StaleQuoteFillModel,
)
from aurora.execution.order_state import OrderLifecycleState, transition
from aurora.execution.reconciliation import reconcile
from aurora.execution.replay import replay_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create(oid: str, symbol: str, side: str, qty: float, ts: str) -> OrderCreated:
    return OrderCreated(
        order_id=oid,
        timestamp_iso=ts,
        symbol=symbol,
        side=side,
        qty=qty,
        order_type="market",
    )


def _submit(oid: str, ts: str) -> OrderSubmitted:
    return OrderSubmitted(order_id=oid, timestamp_iso=ts)


def _ack(oid: str, ts: str) -> OrderAcknowledged:
    return OrderAcknowledged(order_id=oid, timestamp_iso=ts)


def _partial(
    oid: str, qty: float, price: float, side: str, seq: int, ts: str
) -> OrderPartiallyFilled:
    return OrderPartiallyFilled(
        order_id=oid,
        timestamp_iso=ts,
        fill_qty=qty,
        fill_price=price,
        side=side,
        fill_seq=seq,
    )


def _fill(
    oid: str, qty: float, price: float, side: str, seq: int, ts: str
) -> OrderFilled:
    return OrderFilled(
        order_id=oid,
        timestamp_iso=ts,
        fill_qty=qty,
        fill_price=price,
        side=side,
        fill_seq=seq,
        avg_fill_price=price,
    )


# ---------------------------------------------------------------------------
# Replay correctness
# ---------------------------------------------------------------------------

def test_full_fill_rebuilds_position_and_cash() -> None:
    events: list[BrokerEvent] = [
        _create("o1", "AAPL", "buy", 100.0, "2026-05-09T10:00:00"),
        _submit("o1", "2026-05-09T10:00:01"),
        _ack("o1", "2026-05-09T10:00:02"),
        _fill("o1", 100.0, 150.0, "buy", 1, "2026-05-09T10:00:03"),
    ]
    res = replay_events(events)
    assert res.positions["AAPL"] == 100.0
    # Bought 100 @ 150 -> cash drops by 15000.
    assert res.cash == pytest.approx(-15000.0)
    assert res.open_orders == []
    assert res.orphan_events == []
    assert res.duplicate_events == []


def test_partial_fill_then_cancel_leaves_residual() -> None:
    events: list[BrokerEvent] = [
        _create("o2", "MSFT", "buy", 100.0, "2026-05-09T10:00:00"),
        _submit("o2", "2026-05-09T10:00:01"),
        _ack("o2", "2026-05-09T10:00:02"),
        _partial("o2", 40.0, 200.0, "buy", 1, "2026-05-09T10:00:03"),
        CancelRequested(order_id="o2", timestamp_iso="2026-05-09T10:00:04"),
        OrderCancelled(
            order_id="o2",
            timestamp_iso="2026-05-09T10:00:05",
            cancelled_qty=60.0,
        ),
    ]
    res = replay_events(events)
    assert res.positions["MSFT"] == 40.0
    assert res.cash == pytest.approx(-8000.0)
    assert res.open_orders == []  # CANCELLED is terminal


def test_duplicate_fill_detected() -> None:
    dup = _fill("o3", 50.0, 100.0, "buy", 1, "2026-05-09T10:00:03")
    events: list[BrokerEvent] = [
        _create("o3", "GOOG", "buy", 50.0, "2026-05-09T10:00:00"),
        _submit("o3", "2026-05-09T10:00:01"),
        _ack("o3", "2026-05-09T10:00:02"),
        dup,
        dup,  # exact duplicate (same fill_seq)
    ]
    res = replay_events(events)
    # First copy applied; second flagged.
    assert res.positions["GOOG"] == 50.0
    assert res.cash == pytest.approx(-5000.0)
    assert len(res.duplicate_events) == 1


def test_out_of_order_event_detected() -> None:
    events: list[BrokerEvent] = [
        _create("o4", "TSLA", "buy", 10.0, "2026-05-09T10:00:00"),
        _submit("o4", "2026-05-09T10:00:01"),
        _ack("o4", "2026-05-09T10:00:02"),
        # This fill timestamp goes backwards -> flagged.
        _fill("o4", 10.0, 250.0, "buy", 1, "2026-05-09T09:59:00"),
    ]
    res = replay_events(events)
    assert len(res.out_of_order_events) == 1


def test_restart_between_ack_and_fill_replays_correctly() -> None:
    # The replay receives only the tail (post-restart) events.
    events: list[BrokerEvent] = [
        _fill("o5", 25.0, 50.0, "buy", 1, "2026-05-09T10:05:00"),
    ]
    res = replay_events(events)
    # Fill without OrderCreated -> orphan, not applied.
    assert res.positions == {}
    assert res.cash == 0.0
    assert len(res.orphan_events) == 1
    assert res.orphan_events[0].order_id == "o5"


def test_fill_without_local_order_creates_orphan_diff() -> None:
    events: list[BrokerEvent] = [
        _fill("ghost", 5.0, 10.0, "buy", 1, "2026-05-09T10:00:00"),
    ]
    replay = replay_events(events)
    report = reconcile(replay, engine_state={}, broker_state=None)
    orphan_diffs = [d for d in report.diffs if "orphan_event" in d.field_name]
    assert len(orphan_diffs) == 1
    assert orphan_diffs[0].severity == "high"


def test_missing_commission_creates_reconciliation_diff() -> None:
    events: list[BrokerEvent] = [
        _create("o6", "NVDA", "buy", 10.0, "2026-05-09T10:00:00"),
        _submit("o6", "2026-05-09T10:00:01"),
        _ack("o6", "2026-05-09T10:00:02"),
        _fill("o6", 10.0, 100.0, "buy", 1, "2026-05-09T10:00:03"),
        # No CommissionReported event -- replay sees 0 commissions.
    ]
    replay = replay_events(events)
    engine_state = {
        "positions": {"NVDA": 10.0},
        "cash": -1005.0,  # engine recorded 5.0 commissions
        "commissions": 5.0,
    }
    report = reconcile(replay, engine_state, broker_state=None)
    field_names = {d.field_name for d in report.diffs}
    assert "commissions" in field_names
    assert "cash" in field_names


# ---------------------------------------------------------------------------
# Fill models
# ---------------------------------------------------------------------------

def test_limit_order_unfilled_at_unrealistic_price() -> None:
    model = LimitOrderFillModel(fill_threshold=0.5)
    order = {"side": "buy", "qty": 100.0, "limit_price": 50.0}
    market = {"bid": 99.5, "ask": 100.5, "depth": 1000.0, "queue_pos": 50.0}
    result = model.simulate_fill(order, market)
    assert isinstance(result, FillResult)
    assert result.accepted is False
    assert result.qty == 0.0


def test_stale_quote_refuses_fill() -> None:
    inner = MarketOrderFillModel()
    model = StaleQuoteFillModel(inner=inner, max_quote_age_seconds=1.0)
    order = {"side": "buy", "qty": 10.0}
    market = {
        "bid": 99.5,
        "ask": 100.5,
        "depth": 1000.0,
        "quote_age_seconds": 5.0,
    }
    result = model.simulate_fill(order, market)
    assert result.accepted is False
    assert "stale" in result.reason


# ---------------------------------------------------------------------------
# TCA
# ---------------------------------------------------------------------------

def test_tca_finite_and_sign_consistent_buy_above_arrival() -> None:
    arrival = 100.0
    decision_mid = 100.0
    events: list[BrokerEvent] = [
        _create("oT1", "AAPL", "buy", 100.0, "2026-05-09T10:00:00"),
        _fill("oT1", 100.0, 101.0, "buy", 1, "2026-05-09T10:00:03"),
    ]
    res = compute_tca(events, arrival, decision_mid)
    assert isinstance(res, TCAResult)
    assert math.isfinite(res.slippage_bps)
    assert res.slippage_bps > 0  # buy filled above arrival -> cost
    assert math.isfinite(res.total_cost_bps)


def test_tca_buy_below_arrival_negative_slippage() -> None:
    arrival = 100.0
    decision_mid = 100.0
    events: list[BrokerEvent] = [
        _create("oT2", "AAPL", "buy", 100.0, "2026-05-09T10:00:00"),
        _fill("oT2", 100.0, 99.0, "buy", 1, "2026-05-09T10:00:03"),
    ]
    res = compute_tca(events, arrival, decision_mid)
    assert math.isfinite(res.slippage_bps)
    assert res.slippage_bps < 0  # buy filled below arrival -> credit


# ---------------------------------------------------------------------------
# Order lifecycle state machine
# ---------------------------------------------------------------------------

def test_lifecycle_submitted_to_acknowledged_legal() -> None:
    ack = _ack("x", "2026-05-09T10:00:00")
    nxt = transition(OrderLifecycleState.SUBMITTED, ack)
    assert nxt == OrderLifecycleState.ACKNOWLEDGED


def test_lifecycle_submitted_to_filled_illegal() -> None:
    fill = _fill("x", 1.0, 1.0, "buy", 1, "2026-05-09T10:00:00")
    nxt = transition(OrderLifecycleState.SUBMITTED, fill)
    assert nxt is None


def test_commission_event_reduces_cash_and_accumulates() -> None:
    events: list[BrokerEvent] = [
        _create("oC", "IBM", "buy", 10.0, "2026-05-09T10:00:00"),
        _submit("oC", "2026-05-09T10:00:01"),
        _ack("oC", "2026-05-09T10:00:02"),
        _fill("oC", 10.0, 100.0, "buy", 1, "2026-05-09T10:00:03"),
        CommissionReported(
            order_id="oC",
            timestamp_iso="2026-05-09T10:00:04",
            commission=1.0,
            fees=0.5,
        ),
    ]
    res = replay_events(events)
    assert res.commissions == pytest.approx(1.5)
    assert res.cash == pytest.approx(-1001.5)
