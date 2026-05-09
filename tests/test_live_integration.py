"""Live broker integration smoke tests.

These tests are skipped by default. They run only when both:
  1. pytest is invoked with ``-m integration``
  2. ALPACA_API_KEY and ALPACA_API_SECRET env vars are set

They hit the real Alpaca paper API. We submit a single far-from-market
limit order, then cancel it, then verify the resulting state. No market
fills are expected at the test prices.

To enable: see CONTRIBUTING.md section "Integration tests".
"""
from __future__ import annotations

import os
import time

import pytest

from aurora.deployment.brokers import (
    AlpacaAdapter,
    BrokerConfig,
    Order,
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def alpaca_paper():
    """Build a paper AlpacaAdapter or skip if creds / SDK missing."""
    if not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_API_SECRET"):
        pytest.skip("ALPACA_API_KEY / ALPACA_API_SECRET not set")
    try:
        import alpaca  # noqa: F401
    except ImportError:
        pytest.skip("alpaca-py SDK not installed")
    cfg = BrokerConfig(
        name="alpaca",
        api_key_env="ALPACA_API_KEY",
        api_secret_env="ALPACA_API_SECRET",
        paper=True,
    )
    return AlpacaAdapter(cfg)


def test_alpaca_paper_submit_and_cancel_far_limit(alpaca_paper):
    """Submit a limit order at $1 for SPY, confirm submitted, then cancel."""
    adapter = alpaca_paper
    # SPY at $1 should never fill. Use a fresh client_order_id each run.
    cid = f"qf-smoke-{int(time.time())}"
    order = Order(
        symbol="SPY",
        qty=1,
        side="buy",
        order_type="limit",
        limit_price=1.0,
        time_in_force="day",
        client_order_id=cid,
    )
    resp = adapter.submit_order(order)
    assert resp.get("client_order_id") == cid
    order_id = resp.get("id")
    assert order_id

    # Give Alpaca a moment to register the order.
    time.sleep(1.0)

    # Cancel the order.
    canceled = adapter.cancel_order(order_id)
    assert canceled is True


def test_alpaca_paper_account_snapshot(alpaca_paper):
    """get_account returns numeric cash/equity/buying_power."""
    acct = alpaca_paper.get_account()
    assert "cash" in acct
    assert "equity" in acct
    assert "buying_power" in acct
    assert isinstance(acct["cash"], float)
    assert isinstance(acct["equity"], float)
    assert isinstance(acct["buying_power"], float)
