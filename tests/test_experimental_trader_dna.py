"""Tests for TraderDNAProfiler."""
from __future__ import annotations

import pytest

from quantforge.experimental.trader_dna import TraderDNAProfiler


def test_empty_trades_returns_unknown():
    p = TraderDNAProfiler()
    res = p.profile([])
    assert res["n_trades"] == 0
    assert res["risk_tolerance"] == "unknown"
    assert res["fingerprint"] == "empty"


def test_conservative_bucket():
    p = TraderDNAProfiler()
    trades = [{"size": 0.01, "hold_days": 60, "sector": "Tech"} for _ in range(10)]
    res = p.profile(trades)
    assert res["risk_tolerance"] == "conservative"
    assert res["n_trades"] == 10


def test_aggressive_bucket():
    p = TraderDNAProfiler()
    trades = [{"size": 0.25, "hold_days": 1, "sector": "Energy"} for _ in range(5)]
    res = p.profile(trades)
    assert res["risk_tolerance"] == "aggressive"


def test_sector_bias_normalizes_to_one():
    p = TraderDNAProfiler()
    trades = [
        {"size": 0.05, "hold_days": 10, "sector": "Tech"},
        {"size": 0.05, "hold_days": 10, "sector": "Tech"},
        {"size": 0.05, "hold_days": 10, "sector": "Energy"},
    ]
    res = p.profile(trades)
    assert sum(res["sector_bias"].values()) == pytest.approx(1.0)
    assert res["sector_bias"]["Tech"] > res["sector_bias"]["Energy"]


def test_invalid_thresholds_raise():
    with pytest.raises(ValueError):
        TraderDNAProfiler(risk_thresholds=(0.2, 0.1))


def test_fingerprint_is_string():
    p = TraderDNAProfiler()
    res = p.profile([{"size": 0.1, "hold_days": 7, "sector": "Health"}])
    assert isinstance(res["fingerprint"], str)
    assert len(res["fingerprint"]) > 0
