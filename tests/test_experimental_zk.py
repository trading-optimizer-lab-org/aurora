"""Tests for ZKPerformanceProof (mock proof + verify roundtrip)."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.experimental.zk_performance_proof import ZKPerformanceProof


def test_proof_round_trip_verifies():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, 252)
    z = ZKPerformanceProof(claim_metric="sharpe_ratio")
    bundle = z.generate_proof(rets, claimed_value=1.23)
    assert z.verify(bundle) is True


def test_proof_fails_with_wrong_salt():
    rng = np.random.default_rng(1)
    rets = rng.normal(0.0005, 0.01, 100)
    z = ZKPerformanceProof()
    bundle = z.generate_proof(rets, claimed_value=0.5)
    assert z.verify(bundle, salt=b"\x00" * 16) is False


def test_proof_detects_tampered_claim():
    rng = np.random.default_rng(2)
    rets = rng.normal(0.0005, 0.01, 50)
    z = ZKPerformanceProof()
    bundle = z.generate_proof(rets, claimed_value=0.7)
    bundle["claim"]["value"] = 99.0  # tamper
    assert z.verify(bundle) is False


def test_commit_is_deterministic():
    z = ZKPerformanceProof()
    rets = np.array([0.01, -0.02, 0.005])
    a = z.commit(rets)
    b = z.commit(rets)
    assert a == b


def test_different_returns_produce_different_commitment():
    z = ZKPerformanceProof()
    a = z.commit(np.array([0.01, -0.02]))
    b = z.commit(np.array([0.01, -0.03]))
    assert a != b
