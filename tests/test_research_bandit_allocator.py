"""Tests for quantforge.research.bandit_allocator."""
from __future__ import annotations
import pytest

from quantforge.research.bandit_allocator import (
    LiveBanditAllocator,
    AllocationReport,
)


def test_construction_validates():
    with pytest.raises(ValueError):
        LiveBanditAllocator(arms=[])
    with pytest.raises(ValueError):
        LiveBanditAllocator(arms=["a", "a"])
    with pytest.raises(ValueError):
        LiveBanditAllocator(arms=["a", "b"], algorithm="bogus")
    with pytest.raises(ValueError):
        LiveBanditAllocator(arms=["a", "b"], floor=0.6)
    with pytest.raises(ValueError):
        LiveBanditAllocator(arms=["a", "b"], c=0)


def test_ucb1_initial_allocation_is_uniform():
    bd = LiveBanditAllocator(arms=["a", "b", "c"], algorithm="ucb1", floor=0.05)
    rep = bd.allocate()
    assert isinstance(rep, AllocationReport)
    assert rep.algorithm == "ucb1"
    assert pytest.approx(sum(rep.weights.values()), rel=1e-6) == 1.0
    # all infinite scores -> equal share
    for w in rep.weights.values():
        assert abs(w - 1.0 / 3) < 1e-6


def test_ucb1_concentrates_on_winner():
    bd = LiveBanditAllocator(arms=["a", "b"], algorithm="ucb1",
                             floor=0.05, c=0.5)
    for _ in range(200):
        bd.update("a", 0.01)
        bd.update("b", -0.01)
    rep = bd.allocate()
    assert rep.weights["a"] > rep.weights["b"]
    assert rep.arm_means["a"] > rep.arm_means["b"]


def test_thompson_select_returns_known_arm():
    bd = LiveBanditAllocator(arms=["x", "y"], algorithm="thompson", seed=1)
    arm = bd.select()
    assert arm in ("x", "y")


def test_floor_enforced():
    bd = LiveBanditAllocator(arms=["a", "b", "c"], algorithm="ucb1",
                             floor=0.10, c=0.5)
    for _ in range(300):
        bd.update("a", 1.0)
        bd.update("b", 0.0)
        bd.update("c", 0.0)
    rep = bd.allocate()
    for w in rep.weights.values():
        assert w >= 0.10 - 1e-9


def test_unknown_arm_update_raises():
    bd = LiveBanditAllocator(arms=["a", "b"])
    with pytest.raises(KeyError):
        bd.update("c", 0.1)


def test_total_pulls_tracked():
    bd = LiveBanditAllocator(arms=["a", "b"])
    bd.update("a", 0.1); bd.update("b", 0.0); bd.update("a", 0.2)
    rep = bd.allocate()
    assert rep.total_pulls == 3
