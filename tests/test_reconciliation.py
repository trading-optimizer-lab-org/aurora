"""Tests for R169 -- reconciliation engine."""
from __future__ import annotations

import pytest

from aurora.execution.events import (
    EventType,
    ExecutionEvent,
    OrderState,
    OrderStateRecord,
)
from aurora.execution.reconciliation import (
    Mismatch,
    MismatchKind,
    reconcile_broker_vs_engine,
    reconcile_engine_vs_replay,
)
from aurora.execution.replay import replay_execution_events


def _ev(
    event_id: str,
    order_id: str,
    event_type: EventType,
    *,
    payload: dict | None = None,
    timestamp: str = "2026-05-10T00:00:00+00:00",
    symbol: str = "SPY",
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        event_type=event_type,
        order_id=order_id,
        timestamp=timestamp,
        payload=payload or {},
        broker="paper",
        symbol=symbol,
    )


def _replay_with_one_buy() -> tuple[dict, "object"]:
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED,
            payload={"requested_qty": 10, "side": "buy"}),
        _ev("e2", "o1", EventType.FILL,
            payload={"qty": 10, "price": 100, "side": "buy"}),
        _ev("e3", "o1", EventType.COMMISSION, payload={"amount": 1.0}),
    ]
    replay = replay_execution_events(events, starting_cash=10_000.0)
    engine = {
        "orders": dict(replay.orders),
        "positions": dict(replay.positions),
        "cash": replay.cash,
        "commissions": replay.commissions,
    }
    return engine, replay


# ---------------------------------------------------------------------------
# reconcile_engine_vs_replay
# ---------------------------------------------------------------------------


def test_clean_state_yields_no_mismatches():
    engine, replay = _replay_with_one_buy()
    out = reconcile_engine_vs_replay(engine, replay)
    assert out == []


def test_engine_cash_off_emits_cash_mismatch():
    engine, replay = _replay_with_one_buy()
    engine["cash"] = engine["cash"] - 5.0  # engine missing $5
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.CASH_MISMATCH in kinds
    [cash] = [m for m in out if m.kind is MismatchKind.CASH_MISMATCH]
    assert cash.details["delta"] == pytest.approx(-5.0)


def test_engine_position_off_emits_position_mismatch():
    engine, replay = _replay_with_one_buy()
    engine["positions"] = {"SPY": 9.0}  # off by one
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.POSITION_MISMATCH in kinds


def test_engine_commission_off_emits_commission_mismatch():
    engine, replay = _replay_with_one_buy()
    engine["commissions"] = engine["commissions"] + 0.25
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.COMMISSION_MISMATCH in kinds


def test_orphan_order_in_engine_is_flagged():
    engine, replay = _replay_with_one_buy()
    fake = OrderStateRecord(
        order_id="ghost",
        state=OrderState.SUBMITTED,
        symbol="ZZZ",
        side="buy",
        requested_qty=1.0,
        filled_qty=0.0,
        avg_fill_price=0.0,
        last_event_id="g1",
        last_timestamp="2026-05-10T00:00:00+00:00",
    )
    engine["orders"]["ghost"] = fake
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.ORPHAN_ORDER in kinds


def test_replay_gap_when_engine_missing_known_order():
    engine, replay = _replay_with_one_buy()
    engine["orders"] = {}  # engine forgot all orders
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.REPLAY_GAP in kinds


def test_engine_filled_qty_below_replay_signals_missing_fill():
    engine, replay = _replay_with_one_buy()
    rep_rec = replay.orders["o1"]
    # Force engine to record only 5 of 10 filled.
    engine["orders"]["o1"] = OrderStateRecord(
        order_id="o1",
        state=OrderState.PARTIALLY_FILLED,
        symbol=rep_rec.symbol,
        side=rep_rec.side,
        requested_qty=rep_rec.requested_qty,
        filled_qty=5.0,
        avg_fill_price=100.0,
        last_event_id=rep_rec.last_event_id,
        last_timestamp=rep_rec.last_timestamp,
    )
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.MISSING_FILL in kinds


def test_stale_order_flagged_when_engine_not_terminal():
    engine, replay = _replay_with_one_buy()
    rep_rec = replay.orders["o1"]
    engine["orders"]["o1"] = OrderStateRecord(
        order_id="o1",
        state=OrderState.SUBMITTED,  # stale -- replay says FILLED.
        symbol=rep_rec.symbol,
        side=rep_rec.side,
        requested_qty=rep_rec.requested_qty,
        filled_qty=rep_rec.filled_qty,
        avg_fill_price=rep_rec.avg_fill_price,
        last_event_id=rep_rec.last_event_id,
        last_timestamp=rep_rec.last_timestamp,
    )
    out = reconcile_engine_vs_replay(engine, replay)
    kinds = {m.kind for m in out}
    assert MismatchKind.STALE_ORDER in kinds


# ---------------------------------------------------------------------------
# reconcile_broker_vs_engine
# ---------------------------------------------------------------------------


def test_broker_missing_fill_for_known_order():
    engine, _replay = _replay_with_one_buy()
    broker = {
        "fills": [],  # broker reports no fill for o1 even though engine has 10.
    }
    out = reconcile_broker_vs_engine(broker, engine)
    kinds = {m.kind for m in out}
    assert MismatchKind.DUPLICATE_FILL in kinds


def test_broker_orphan_fill_for_unknown_order():
    engine, _replay = _replay_with_one_buy()
    broker = {
        "fills": [
            {"order_id": "ghost", "qty": 5, "price": 100, "fill_id": "f-x",
             "side": "buy"},
        ],
    }
    out = reconcile_broker_vs_engine(broker, engine)
    kinds = {m.kind for m in out}
    assert MismatchKind.MISSING_FILL in kinds


def test_broker_duplicate_fill_excess_over_engine():
    engine, _replay = _replay_with_one_buy()
    broker = {
        "fills": [
            {"order_id": "o1", "qty": 12, "price": 100, "fill_id": "f1",
             "side": "buy"},
        ],
    }
    out = reconcile_broker_vs_engine(broker, engine)
    [m] = [x for x in out if x.kind is MismatchKind.MISSING_FILL]
    assert m.details["broker_filled"] == pytest.approx(12.0)
    assert m.details["engine_filled"] == pytest.approx(10.0)


def test_broker_cash_mismatch_when_broker_disagrees():
    engine, _replay = _replay_with_one_buy()
    broker = {
        "fills": [
            {"order_id": "o1", "qty": 10, "price": 100, "fill_id": "f1",
             "side": "buy"},
        ],
        "cash": engine["cash"] + 100.0,
        "commissions": engine["commissions"],
        "positions": dict(engine["positions"]),
    }
    out = reconcile_broker_vs_engine(broker, engine)
    kinds = {m.kind for m in out}
    assert MismatchKind.CASH_MISMATCH in kinds


def test_broker_unknown_event_surfaced():
    engine, _replay = _replay_with_one_buy()
    broker = {
        "fills": [
            {"order_id": "o1", "qty": 10, "price": 100, "fill_id": "f1",
             "side": "buy"},
        ],
        "unknown_events": [
            {"event_id": "ub-1", "kind": "rebate_credit",
             "details": "venue-side rebate"},
        ],
    }
    out = reconcile_broker_vs_engine(broker, engine)
    kinds = {m.kind for m in out}
    assert MismatchKind.UNKNOWN_BROKER_EVENT in kinds


def test_clean_broker_engine_state_yields_no_mismatches():
    engine, _replay = _replay_with_one_buy()
    broker = {
        "fills": [
            {"order_id": "o1", "qty": 10, "price": 100, "fill_id": "f1",
             "side": "buy"},
        ],
        "cash": engine["cash"],
        "commissions": engine["commissions"],
        "positions": dict(engine["positions"]),
    }
    out = reconcile_broker_vs_engine(broker, engine)
    assert out == []


def test_reconcile_engine_vs_replay_rejects_none_replay():
    with pytest.raises(ValueError):
        reconcile_engine_vs_replay({"cash": 0.0}, None)  # type: ignore[arg-type]


def test_reconcile_broker_vs_engine_rejects_none_snapshot():
    engine, _replay = _replay_with_one_buy()
    with pytest.raises(ValueError):
        reconcile_broker_vs_engine(None, engine)  # type: ignore[arg-type]


def test_mismatch_to_dict_round_trip():
    m = Mismatch(
        kind=MismatchKind.CASH_MISMATCH,
        reason="off",
        details={"delta": 1.0},
        evidence_ids=("e1",),
    )
    d = m.to_dict()
    assert d["kind"] == "cash_mismatch"
    assert d["details"] == {"delta": 1.0}
    assert d["evidence_ids"] == ["e1"]
