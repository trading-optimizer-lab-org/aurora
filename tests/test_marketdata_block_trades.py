"""Tests for quantforge.marketdata.block_trades."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.marketdata.block_trades import (
    BlockTradeDetector,
    BlockTradeConfig,
)


@pytest.fixture
def detector() -> BlockTradeDetector:
    return BlockTradeDetector()


def test_detect_flags_size_block(detector: BlockTradeDetector):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01"] * 2, utc=True),
        "price": [10.0, 50.0],
        "size": [12_000, 100],  # First exceeds size; second doesn't
    })
    out = detector.detect(trades)
    assert out.iloc[0]["is_block"]
    assert out.iloc[0]["block_reason"] in ("size", "size+notional")
    assert not out.iloc[1]["is_block"]


def test_detect_flags_notional_block(detector: BlockTradeDetector):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01"] * 1, utc=True),
        "price": [500.0],
        "size": [500],  # 500 * 500 = 250k > 200k notional
    })
    out = detector.detect(trades)
    assert out.iloc[0]["is_block"]
    assert "notional" in out.iloc[0]["block_reason"]


def test_require_both_uses_AND():
    detector = BlockTradeDetector(BlockTradeConfig(require_both=True))
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01"], utc=True),
        "price": [10.0],
        "size": [12_000],  # Size hit, but notional 120k < 200k.
    })
    out = detector.detect(trades)
    assert not out.iloc[0]["is_block"]


def test_get_blocks_sorted_by_notional(detector: BlockTradeDetector):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01"] * 3, utc=True),
        "price": [100.0, 200.0, 50.0],
        "size": [12_000, 11_000, 15_000],
    })
    blocks = detector.get_blocks(trades)
    assert len(blocks) == 3
    assert blocks["notional"].is_monotonic_decreasing


def test_block_stats_aggregate(detector: BlockTradeDetector):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01"] * 3, utc=True),
        "price": [100.0, 100.0, 50.0],
        "size": [12_000, 100, 100],
    })
    stats = detector.block_stats(trades)
    assert stats["n_blocks"] == 1
    assert stats["block_volume"] == 12_000
    assert stats["block_share_volume"] > 0.95
