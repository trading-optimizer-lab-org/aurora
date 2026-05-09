"""Tests for deployment.strategy_isolation (R71)."""
from __future__ import annotations

import pytest

from aurora.deployment.strategy_isolation import (
    IsolationConflict,
    Lease,
    StrategyIsolation,
)


def test_acquire_grants_exclusive_lease():
    iso = StrategyIsolation()
    lease = iso.acquire("alpha", "SPY")
    assert isinstance(lease, Lease)
    assert lease.strategy_id == "alpha"
    assert lease.symbol == "SPY"


def test_second_strategy_refused():
    iso = StrategyIsolation()
    iso.acquire("alpha", "SPY")
    with pytest.raises(IsolationConflict):
        iso.acquire("beta", "SPY")


def test_same_strategy_reacquire_is_idempotent():
    iso = StrategyIsolation()
    a = iso.acquire("alpha", "SPY")
    b = iso.acquire("alpha", "SPY")
    assert a == b


def test_release_frees_the_symbol():
    iso = StrategyIsolation()
    lease = iso.acquire("alpha", "SPY")
    iso.release(lease)
    assert iso.is_free("SPY") is True
    iso.acquire("beta", "SPY")  # no longer raises


def test_release_with_wrong_strategy_refuses():
    iso = StrategyIsolation()
    iso.acquire("alpha", "SPY")
    spoofed = Lease(
        strategy_id="beta",
        symbol="SPY",
        acquired_at=__import__("datetime").datetime.utcnow(),
    )
    with pytest.raises(IsolationConflict):
        iso.release(spoofed)


def test_release_all_for_drops_every_lease_of_strategy():
    iso = StrategyIsolation()
    iso.acquire("alpha", "SPY")
    iso.acquire("alpha", "QQQ")
    iso.acquire("beta", "TLT")
    n = iso.release_all_for("alpha")
    assert n == 2
    assert iso.is_free("SPY")
    assert iso.is_free("QQQ")
    assert iso.is_free("TLT") is False


def test_current_leases_snapshot_is_immutable_view():
    iso = StrategyIsolation()
    iso.acquire("alpha", "SPY")
    iso.acquire("beta", "QQQ")
    leases = iso.current_leases()
    assert {l.symbol for l in leases} == {"SPY", "QQQ"}
    # Modifying the snapshot does not affect the registry.
    leases.clear()
    assert iso.acquired_by("SPY") is not None


def test_acquired_by_returns_none_when_free():
    iso = StrategyIsolation()
    assert iso.acquired_by("SPY") is None
