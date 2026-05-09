"""Tests for quantforge.compliance.best_execution."""
from __future__ import annotations

import pytest

from aurora.compliance.best_execution import (
    BestExecutionConfig,
    BestExecutionReporter,
)


@pytest.fixture
def reporter() -> BestExecutionReporter:
    return BestExecutionReporter(BestExecutionConfig(report_period="2025-Q1"))


@pytest.fixture
def orders() -> list[dict]:
    return [
        {"symbol": "AAPL", "side": "BUY", "size": 100,
         "quoted_spread_bps": 1.5, "effective_spread_bps": 1.2,
         "price_improvement_bps": 0.3, "fill_status": "filled",
         "venue": "ARCA", "security_category": "NMS",
         "payment_for_order_flow_cents": 0.0},
        {"symbol": "MSFT", "side": "SELL", "size": 1500,
         "quoted_spread_bps": 2.0, "effective_spread_bps": 1.8,
         "price_improvement_bps": 0.2, "fill_status": "filled",
         "venue": "NSDQ", "security_category": "NMS",
         "payment_for_order_flow_cents": 12.5},
        {"symbol": "TSLA", "side": "BUY", "size": 250,
         "quoted_spread_bps": 3.0, "effective_spread_bps": 3.0,
         "price_improvement_bps": 0.0, "fill_status": "unfilled",
         "venue": "ARCA", "security_category": "NMS",
         "payment_for_order_flow_cents": 0.0},
    ]


def test_605_report_basic_shape(reporter, orders):
    rep = reporter.build_605_report(orders)
    assert rep["n_orders"] == 3
    assert "buckets" in rep
    assert len(rep["buckets"]) == 4


def test_605_fill_rate(reporter, orders):
    rep = reporter.build_605_report(orders)
    # 2 filled / 3 = 66.66%
    assert 66.0 < rep["fill_rate_pct"] < 67.0


def test_605_avg_effective_spread(reporter, orders):
    rep = reporter.build_605_report(orders)
    # mean of 1.2, 1.8, 3.0 = 2.0
    assert abs(rep["avg_effective_spread_bps"] - 2.0) < 1e-9


def test_605_buckets_disaggregate_by_size(reporter, orders):
    rep = reporter.build_605_report(orders)
    bucket_100_499 = next(b for b in rep["buckets"] if b["size_low"] == 100)
    bucket_500_1999 = next(b for b in rep["buckets"] if b["size_low"] == 500)
    assert bucket_100_499["n_orders"] == 2  # AAPL=100 and TSLA=250
    assert bucket_500_1999["n_orders"] == 1  # MSFT=1500


def test_606_groups_by_venue(reporter, orders):
    rep = reporter.build_606_report(orders)
    venues = {v["venue"]: v for v in rep["venues"]}
    assert "ARCA" in venues
    assert "NSDQ" in venues
    assert venues["ARCA"]["n_orders"] == 2
    assert venues["NSDQ"]["n_orders"] == 1


def test_606_aggregates_pfof(reporter, orders):
    rep = reporter.build_606_report(orders)
    venues = {v["venue"]: v for v in rep["venues"]}
    assert venues["NSDQ"]["pfof_cents"] == 12.5
    assert venues["ARCA"]["pfof_cents"] == 0.0


def test_606_category_totals(reporter, orders):
    rep = reporter.build_606_report(orders)
    assert rep["category_totals"]["NMS"] == 100 + 1500 + 250


def test_empty_orders_returns_empty_605(reporter):
    rep = reporter.build_605_report([])
    assert rep["n_orders"] == 0
    assert rep["buckets"] == []
