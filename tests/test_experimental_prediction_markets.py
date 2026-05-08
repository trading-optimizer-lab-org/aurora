"""Tests for PolymarketAdapter."""
from __future__ import annotations

import pytest

from quantforge.experimental.prediction_markets import PolymarketAdapter, _mock_fetch


def test_default_uses_mock_fetcher():
    adapter = PolymarketAdapter()
    res = adapter.odds("market-A")
    assert 0.0 < res["yes"] < 1.0
    assert res["no"] == pytest.approx(1.0 - res["yes"])
    assert -1.0 <= res["signal"] <= 1.0


def test_custom_fetcher_overrides_mock():
    adapter = PolymarketAdapter(fetcher=lambda mid: {"yes": 0.8})
    res = adapter.odds("anything")
    assert res["yes"] == 0.8
    assert res["no"] == pytest.approx(0.2)
    assert res["signal"] == pytest.approx(0.6)


def test_signal_at_boundaries():
    adapter = PolymarketAdapter(fetcher=lambda mid: {"yes": 1.0})
    assert adapter.odds("m")["signal"] == pytest.approx(1.0)
    adapter2 = PolymarketAdapter(fetcher=lambda mid: {"yes": 0.0})
    assert adapter2.odds("m")["signal"] == pytest.approx(-1.0)


def test_empty_market_id_raises():
    adapter = PolymarketAdapter()
    with pytest.raises(ValueError):
        adapter.odds("")


def test_mock_fetcher_is_deterministic():
    a = _mock_fetch("xyz")
    b = _mock_fetch("xyz")
    assert a == b
