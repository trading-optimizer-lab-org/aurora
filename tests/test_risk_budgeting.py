"""Tests for RiskBudgetingAllocator."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.risk.risk_budgeting import RiskBudgetingAllocator


def test_rb_simplex():
    rng = np.random.default_rng(7)
    R = rng.normal(0.0, 0.01, (800, 6))
    buckets = ["tech", "tech", "fin", "fin", "energy", "energy"]
    rb = RiskBudgetingAllocator(targets={"tech": 0.5, "fin": 0.3, "energy": 0.2})
    w = rb.allocate(R, buckets)
    assert np.isclose(w.sum(), 1.0, atol=1e-6)
    assert np.all(w >= 0)


def test_rb_targets_sum_renormalised():
    # User passes percentages, allocator should renormalise to sum to 1
    rb = RiskBudgetingAllocator(targets={"a": 50, "b": 30, "c": 20})
    s = sum(rb.targets.values())
    assert np.isclose(s, 1.0)


def test_rb_validates_empty_targets():
    with pytest.raises(ValueError):
        RiskBudgetingAllocator(targets={})


def test_rb_validates_negative_targets():
    with pytest.raises(ValueError):
        RiskBudgetingAllocator(targets={"a": -0.5, "b": 1.5})


def test_rb_validates_zero_sum_targets():
    with pytest.raises(ValueError):
        RiskBudgetingAllocator(targets={"a": 0, "b": 0})


def test_rb_buckets_length_mismatch():
    rng = np.random.default_rng(7)
    R = rng.normal(0.0, 0.01, (200, 3))
    rb = RiskBudgetingAllocator(targets={"x": 0.5, "y": 0.5})
    with pytest.raises(ValueError):
        rb.allocate(R, buckets=["x", "y"])


def test_rb_2d_required():
    rb = RiskBudgetingAllocator(targets={"x": 1.0})
    with pytest.raises(ValueError):
        rb.allocate(np.array([1.0, 2.0]), ["x"])


def test_rb_bucket_contributions_sum_to_one():
    rng = np.random.default_rng(11)
    R = rng.normal(0.0, 0.01, (500, 4))
    buckets = ["a", "a", "b", "b"]
    rb = RiskBudgetingAllocator(targets={"a": 0.6, "b": 0.4})
    w = rb.allocate(R, buckets)
    contribs = rb.bucket_contributions(w, R, buckets)
    assert "a" in contribs and "b" in contribs
    assert np.isclose(sum(contribs.values()), 1.0, atol=1e-6)
