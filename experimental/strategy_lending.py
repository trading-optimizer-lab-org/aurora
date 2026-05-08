"""Strategy lending marketplace.

P2P marketplace where strategy owners list strategies for rent and
charge a per-backtest royalty. Pure in-memory ledger — no chain or
network. Useful as a unit-testable stub for a future on-chain version.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _Listing:
    strategy_id: str
    owner: str
    royalty_per_run: float


@dataclass
class StrategyLendingMarketplace:
    """List strategies for rent and meter usage.

    Royalties are accrued per ``rent_run`` call. ``settle`` zeroes the
    accrued balance for an owner and returns the paid amount.
    """

    listings: dict[str, _Listing] = field(default_factory=dict)
    accrued: dict[str, float] = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)

    def list_strategy(
        self, strategy_id: str, owner: str, royalty_per_run: float
    ) -> dict:
        if not strategy_id or not owner:
            raise ValueError("strategy_id and owner are required")
        if royalty_per_run < 0:
            raise ValueError("royalty must be non-negative")
        if strategy_id in self.listings:
            raise ValueError(f"strategy_id already listed: {strategy_id}")
        self.listings[strategy_id] = _Listing(strategy_id, owner, royalty_per_run)
        return {
            "strategy_id": strategy_id,
            "owner": owner,
            "royalty_per_run": royalty_per_run,
        }

    def rent_run(self, strategy_id: str, renter: str) -> dict:
        """Charge a royalty for one backtest run."""
        if strategy_id not in self.listings:
            raise ValueError(f"unknown strategy_id: {strategy_id}")
        if not renter:
            raise ValueError("renter is required")
        listing = self.listings[strategy_id]
        self.accrued[listing.owner] = (
            self.accrued.get(listing.owner, 0.0) + listing.royalty_per_run
        )
        record = {
            "strategy_id": strategy_id,
            "renter": renter,
            "owner": listing.owner,
            "fee": listing.royalty_per_run,
            "ts": time.time(),
        }
        self.runs.append(record)
        return record

    def settle(self, owner: str) -> dict:
        """Pay out and zero the owner's accrued royalties."""
        amount = self.accrued.get(owner, 0.0)
        self.accrued[owner] = 0.0
        return {"owner": owner, "paid": amount}
