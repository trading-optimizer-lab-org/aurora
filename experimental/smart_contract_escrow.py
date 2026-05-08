"""Performance-fee escrow — Solidity contract template + mock chain.

Provides a Solidity stub exposed as a string for off-chain inspection and
an in-memory simulator that mirrors the contract's accounting behavior.
No real chain interaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


SOLIDITY_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract PerformanceFeeEscrow {
    address public manager;
    address public investor;
    uint256 public principal;
    uint256 public highWaterMark;
    uint16 public feeBps;

    constructor(address _manager, uint16 _feeBps) {
        manager = _manager;
        investor = msg.sender;
        feeBps = _feeBps;
    }

    function deposit() external payable {
        principal += msg.value;
        if (msg.value > highWaterMark) highWaterMark = msg.value;
    }

    function settle(uint256 navAfter) external returns (uint256 fee) {
        require(msg.sender == manager, "manager only");
        if (navAfter > highWaterMark) {
            uint256 profit = navAfter - highWaterMark;
            fee = (profit * feeBps) / 10000;
            highWaterMark = navAfter;
        }
        return fee;
    }
}
"""


@dataclass
class PerformanceFeeEscrow:
    """Off-chain mock of the performance-fee escrow contract.

    Parameters
    ----------
    manager : str
        Manager address.
    investor : str
        Investor address.
    fee_bps : int
        Performance fee in basis points (100 bps = 1%).
    """

    manager: str
    investor: str
    fee_bps: int = 2000  # 20%
    principal: float = 0.0
    high_water_mark: float = 0.0
    fees_paid: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if not self.manager or not self.investor:
            raise ValueError("manager and investor are required")
        if not (0 <= self.fee_bps <= 10_000):
            raise ValueError("fee_bps must be in [0, 10000]")

    def deposit(self, amount: float) -> dict:
        if amount <= 0:
            raise ValueError("amount must be positive")
        self.principal += amount
        if self.principal > self.high_water_mark:
            self.high_water_mark = self.principal
        return {"principal": self.principal, "hwm": self.high_water_mark}

    def settle(self, nav_after: float) -> dict:
        """Settle a period; pay performance fee on profit above HWM."""
        if nav_after < 0:
            raise ValueError("nav_after must be non-negative")
        fee = 0.0
        if nav_after > self.high_water_mark:
            profit = nav_after - self.high_water_mark
            fee = profit * self.fee_bps / 10_000.0
            self.high_water_mark = nav_after
        self.fees_paid += fee
        return {
            "fee": fee,
            "fees_paid_total": self.fees_paid,
            "hwm": self.high_water_mark,
        }

    def solidity_source(self) -> str:
        """Return the Solidity contract template."""
        return SOLIDITY_TEMPLATE
