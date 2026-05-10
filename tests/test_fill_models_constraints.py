"""Tests for R170 -- realistic fill models."""
from __future__ import annotations

import pytest

from aurora.execution.events import EventType
from aurora.execution.fill_models import (
    FillModelInput,
    OrderType,
    SpreadAwareFillModel,
    apply_fill_model,
)


def _input(
    *,
    order_id: str = "o1",
    qty: float = 100.0,
    order_type: OrderType = OrderType.MARKET,
    side: str = "buy",
    bid: float = 99.99,
    ask: float = 100.01,
    last_price: float | None = None,
    bar_volume: float = 1_000_000.0,
    limit_price: float | None = None,
    stop_price: float | None = None,
    timestamp: str = "2026-05-10T00:00:00+00:00",
    symbol: str = "SPY",
) -> FillModelInput:
    return FillModelInput(
        order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        order_type=order_type,
        timestamp=timestamp,
        bid=bid,
        ask=ask,
        last_price=last_price,
        bar_volume=bar_volume,
        limit_price=limit_price,
        stop_price=stop_price,
    )


def test_market_buy_crosses_ask():
    model = SpreadAwareFillModel(seed=1)
    out = model.simulate(_input())
    assert not out.rejected
    assert out.filled_qty == 100
    assert out.avg_fill_price == pytest.approx(100.01)
    types = [ev.event_type for ev in out.events]
    assert EventType.BROKER_ACK in types
    assert EventType.FILL in types


def test_market_sell_hits_bid():
    model = SpreadAwareFillModel(seed=1)
    out = model.simulate(_input(side="sell"))
    assert out.avg_fill_price == pytest.approx(99.99)


def test_deterministic_with_seed():
    model = SpreadAwareFillModel(
        seed=42, partial_fill_prob=0.5, reject_prob=0.1,
    )
    a = model.simulate(_input(order_id="o1"))
    b = model.simulate(_input(order_id="o1"))
    assert a.events == b.events
    assert a.filled_qty == b.filled_qty
    assert a.rejected == b.rejected


def test_different_seeds_produce_different_streams():
    m1 = SpreadAwareFillModel(seed=1, partial_fill_prob=0.9)
    m2 = SpreadAwareFillModel(seed=999, partial_fill_prob=0.9)
    a = m1.simulate(_input(order_id="o1"))
    b = m2.simulate(_input(order_id="o1"))
    # Same logical order; different seeds -> different filled qty most of the time.
    # We assert they produce a real stream rather than identical output.
    assert (a.filled_qty != b.filled_qty) or (a.events != b.events)


def test_partial_fill_prob_respected_over_many_trials():
    model = SpreadAwareFillModel(seed=7, partial_fill_prob=0.6)
    n = 200
    partials = 0
    for i in range(n):
        out = model.simulate(_input(order_id=f"order-{i}"))
        if any(ev.event_type is EventType.PARTIAL_FILL for ev in out.events):
            partials += 1
    rate = partials / n
    # Loose band -- 0.6 +/- 0.15 keeps the test stable across implementations.
    assert 0.45 <= rate <= 0.75, f"partial rate {rate} out of expected band"


def test_reject_prob_respected_over_many_trials():
    model = SpreadAwareFillModel(seed=7, reject_prob=0.4)
    n = 200
    rejects = sum(
        1 for i in range(n)
        if model.simulate(_input(order_id=f"order-{i}")).rejected
    )
    rate = rejects / n
    assert 0.25 <= rate <= 0.55, f"reject rate {rate} out of expected band"


def test_tick_size_rounds_buy_up_and_sell_down():
    model = SpreadAwareFillModel(seed=1, tick_size=0.05)
    buy = model.simulate(_input(side="buy", bid=99.99, ask=100.013))
    sell = model.simulate(_input(side="sell", bid=99.997, ask=100.01))
    # Buy crossed ask 100.013 -> rounded up to 100.05.
    assert buy.avg_fill_price == pytest.approx(100.05)
    # Sell hit bid 99.997 -> rounded down to 99.95.
    assert sell.avg_fill_price == pytest.approx(99.95)


def test_min_lot_rejects_sub_min_orders():
    model = SpreadAwareFillModel(seed=1, min_lot=10.0)
    out = model.simulate(_input(qty=5))
    assert out.rejected
    assert "min_lot" in out.rejection_reason


def test_max_volume_participation_caps_fill_qty():
    model = SpreadAwareFillModel(
        seed=1, max_volume_participation=0.05,
    )
    # Bar volume 1_000 -> cap = 50 -> requested 200 should clamp to 50.
    out = model.simulate(_input(qty=200, bar_volume=1_000.0))
    assert not out.rejected
    assert out.filled_qty == pytest.approx(50.0)


def test_limit_buy_fills_only_when_ask_below_limit():
    model = SpreadAwareFillModel(seed=1)
    inside = model.simulate(_input(
        order_type=OrderType.LIMIT, side="buy", limit_price=100.05,
        bid=99.99, ask=100.01,
    ))
    assert not inside.rejected
    outside = model.simulate(_input(
        order_id="o2",
        order_type=OrderType.LIMIT, side="buy", limit_price=99.95,
        bid=99.99, ask=100.01,
    ))
    assert outside.rejected


def test_stop_buy_triggers_only_when_last_price_above_stop():
    model = SpreadAwareFillModel(seed=1)
    triggered = model.simulate(_input(
        order_type=OrderType.STOP, side="buy", stop_price=100.0,
        last_price=101.0,
    ))
    assert not triggered.rejected
    not_yet = model.simulate(_input(
        order_id="o2",
        order_type=OrderType.STOP, side="buy", stop_price=110.0,
        last_price=101.0,
    ))
    assert not_yet.rejected


def test_apply_fill_model_concatenates_events():
    model = SpreadAwareFillModel(seed=1)
    orders = [
        _input(order_id="o1"),
        _input(order_id="o2", side="sell"),
    ]
    events = apply_fill_model(orders, model)
    order_ids = {ev.order_id for ev in events}
    assert order_ids == {"o1", "o2"}
    # At least one ACK + one FILL per order.
    assert len(events) >= 4


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        FillModelInput(
            order_id="",
            symbol="SPY",
            side="buy",
            qty=1,
            order_type=OrderType.MARKET,
            timestamp="t",
            bid=100.0,
            ask=100.1,
        )
    with pytest.raises(ValueError):
        FillModelInput(
            order_id="o1",
            symbol="SPY",
            side="hold",  # not buy/sell
            qty=1,
            order_type=OrderType.MARKET,
            timestamp="t",
            bid=100.0,
            ask=100.1,
        )


def test_invalid_model_config_raises():
    with pytest.raises(ValueError):
        SpreadAwareFillModel(partial_fill_prob=1.5)
    with pytest.raises(ValueError):
        SpreadAwareFillModel(reject_prob=-0.1)
    with pytest.raises(ValueError):
        SpreadAwareFillModel(max_volume_participation=2.0)
