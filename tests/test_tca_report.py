"""Tests for R170 -- TCA report."""
from __future__ import annotations

import pytest

from aurora.analytics.tca import TCAReport, compute_tca
from aurora.execution.events import EventType, ExecutionEvent


def _ev(
    event_id: str,
    event_type: EventType,
    payload: dict,
    *,
    order_id: str = "o1",
    symbol: str = "SPY",
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        event_type=event_type,
        order_id=order_id,
        timestamp="2026-05-10T00:00:00+00:00",
        payload=payload,
        broker="paper",
        symbol=symbol,
    )


def test_zero_cost_when_execution_matches_arrival_and_benchmark():
    events = [
        _ev("e1", EventType.FILL,
            {"qty": 100, "price": 100.0, "side": "buy"}),
    ]
    report = compute_tca(
        events,
        arrival_price=100.0,
        benchmark_price=100.0,
        requested_qty=100,
    )
    assert report.execution_price == pytest.approx(100.0)
    assert report.slippage == pytest.approx(0.0)
    assert report.realised_spread == pytest.approx(0.0)
    assert report.effective_spread == pytest.approx(0.0)
    assert report.unfilled_qty == pytest.approx(0.0)


def test_positive_slippage_detected_for_buy_above_arrival():
    events = [
        _ev("e1", EventType.FILL,
            {"qty": 100, "price": 100.10, "side": "buy"}),
    ]
    report = compute_tca(
        events,
        arrival_price=100.00,
        benchmark_price=100.05,
        requested_qty=100,
    )
    # Buy filled 10 cents over arrival -> slippage = +0.10 * 100 = 10.
    assert report.slippage == pytest.approx(10.0)
    # Realised spread vs benchmark = 2 * (100.10 - 100.05) * +1 = 0.10.
    assert report.realised_spread == pytest.approx(0.10)
    assert report.effective_spread == pytest.approx(0.20)
    assert report.unfilled_qty == 0


def test_unfilled_qty_surfaces_when_partials_dont_complete():
    events = [
        _ev("e1", EventType.PARTIAL_FILL,
            {"qty": 30, "price": 100.0, "side": "buy"}),
    ]
    report = compute_tca(
        events,
        arrival_price=100.0,
        benchmark_price=100.0,
        requested_qty=100,
    )
    assert report.filled_qty == pytest.approx(30.0)
    assert report.unfilled_qty == pytest.approx(70.0)


def test_opportunity_cost_when_market_runs_away():
    events = [
        _ev("e1", EventType.PARTIAL_FILL,
            {"qty": 30, "price": 100.0, "side": "buy"}),
    ]
    # Benchmark drifted up to 100.5 -> we missed gains on the unfilled 70 shares.
    report = compute_tca(
        events,
        arrival_price=100.0,
        benchmark_price=100.5,
        requested_qty=100,
    )
    # opportunity_cost = (100.5 - 100) * +1 * 70 = 35.
    assert report.opportunity_cost == pytest.approx(35.0)


def test_commissions_accumulate_from_events():
    events = [
        _ev("e1", EventType.FILL, {"qty": 10, "price": 100, "side": "buy"}),
        _ev("e2", EventType.COMMISSION, {"amount": 1.5}),
        _ev("e3", EventType.COMMISSION, {"amount": 0.5}),
    ]
    report = compute_tca(events, arrival_price=100, benchmark_price=100,
                        requested_qty=10)
    assert report.commissions == pytest.approx(2.0)


def test_report_markdown_is_deterministic():
    events = [
        _ev("e1", EventType.FILL, {"qty": 10, "price": 100, "side": "buy"}),
    ]
    a = compute_tca(events, arrival_price=100, benchmark_price=100,
                   requested_qty=10).to_markdown()
    b = compute_tca(events, arrival_price=100, benchmark_price=100,
                   requested_qty=10).to_markdown()
    assert a == b
    # Markdown contains the canonical headers we report.
    for label in (
        "side", "filled_qty", "arrival_price", "execution_price",
        "slippage", "commissions",
    ):
        assert label in a


def test_compute_tca_rejects_bad_inputs():
    with pytest.raises(ValueError):
        compute_tca([], arrival_price=100, benchmark_price=100, requested_qty=0)
    with pytest.raises(ValueError):
        compute_tca([], arrival_price=0, benchmark_price=100, requested_qty=10)
    with pytest.raises(ValueError):
        compute_tca([], arrival_price=100, benchmark_price=0, requested_qty=10)


def test_to_dict_round_trip():
    events = [
        _ev("e1", EventType.FILL, {"qty": 10, "price": 100, "side": "buy"}),
    ]
    report = compute_tca(events, arrival_price=100, benchmark_price=100,
                        requested_qty=10)
    d = report.to_dict()
    assert d["filled_qty"] == 10
    assert d["side"] == "buy"
    assert isinstance(report, TCAReport)
