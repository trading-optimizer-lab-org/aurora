"""Tests for PerformanceFeeEscrow."""
from __future__ import annotations

import pytest

from aurora.experimental.smart_contract_escrow import (
    PerformanceFeeEscrow,
    SOLIDITY_TEMPLATE,
)


def test_deposit_and_hwm():
    e = PerformanceFeeEscrow(manager="0xMgr", investor="0xInv")
    e.deposit(100.0)
    assert e.principal == pytest.approx(100.0)
    assert e.high_water_mark == pytest.approx(100.0)


def test_settle_pays_fee_on_profit():
    e = PerformanceFeeEscrow(manager="0xMgr", investor="0xInv", fee_bps=2000)
    e.deposit(100.0)
    res = e.settle(150.0)
    # 20% of 50 profit = 10
    assert res["fee"] == pytest.approx(10.0)
    assert e.high_water_mark == pytest.approx(150.0)


def test_no_fee_when_below_hwm():
    e = PerformanceFeeEscrow(manager="0xMgr", investor="0xInv", fee_bps=2000)
    e.deposit(100.0)
    e.settle(150.0)
    res = e.settle(120.0)
    assert res["fee"] == 0.0
    assert e.high_water_mark == pytest.approx(150.0)


def test_validation_constructor():
    with pytest.raises(ValueError):
        PerformanceFeeEscrow(manager="", investor="x")
    with pytest.raises(ValueError):
        PerformanceFeeEscrow(manager="m", investor="i", fee_bps=-1)
    with pytest.raises(ValueError):
        PerformanceFeeEscrow(manager="m", investor="i", fee_bps=20_000)


def test_negative_deposit_raises():
    e = PerformanceFeeEscrow(manager="0xMgr", investor="0xInv")
    with pytest.raises(ValueError):
        e.deposit(-1.0)


def test_solidity_source_returned():
    e = PerformanceFeeEscrow(manager="0xMgr", investor="0xInv")
    src = e.solidity_source()
    assert "PerformanceFeeEscrow" in src
    assert src == SOLIDITY_TEMPLATE
