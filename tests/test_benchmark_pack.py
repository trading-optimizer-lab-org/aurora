"""Tests for R164 mandatory benchmark pack."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.validation.benchmark_pack import (
    BenchmarkPack,
    assert_pack_complete,
    build_benchmark_pack,
    required_pack_keys,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _series(seed: int, n: int = 252) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n) * 0.01


# ---------------------------------------------------------------------------
# Pack-level tests
# ---------------------------------------------------------------------------


def test_pack_includes_every_required_baseline():
    s = _series(0)
    a = _series(1)
    pack = build_benchmark_pack(s, a, strategy_id="strat-1")
    have = {m.name for m in pack.metrics}
    assert have == set(required_pack_keys())


def test_assert_pack_complete_raises_when_missing():
    s = _series(0)
    a = _series(1)
    pack = build_benchmark_pack(s, a, strategy_id="strat-1")
    truncated = BenchmarkPack(
        strategy_id=pack.strategy_id,
        primary_baseline=pack.primary_baseline,
        periods_per_year=pack.periods_per_year,
        random_seed=pack.random_seed,
        metrics=pack.metrics[:-1],
        overall_verdict=pack.overall_verdict,
        pack_hash=pack.pack_hash,
        n_periods=pack.n_periods,
    )
    with pytest.raises(ValueError):
        assert_pack_complete(truncated)


def test_pack_random_seed_is_persisted():
    s = _series(0)
    a = _series(1)
    pack = build_benchmark_pack(s, a, strategy_id="x", random_seed=42)
    assert pack.random_seed == 42
    rand = pack.metric("random_comparable_turnover")
    assert "seed=42" in rand.note


def test_pack_hash_changes_when_seed_changes():
    s = _series(0)
    a = _series(1)
    pack_a = build_benchmark_pack(s, a, strategy_id="x", random_seed=0)
    pack_b = build_benchmark_pack(s, a, strategy_id="x", random_seed=1)
    assert pack_a.pack_hash != pack_b.pack_hash


def test_pack_hash_is_deterministic_for_same_inputs():
    s = _series(0)
    a = _series(1)
    pack_1 = build_benchmark_pack(s, a, strategy_id="x", random_seed=0)
    pack_2 = build_benchmark_pack(s, a, strategy_id="x", random_seed=0)
    assert pack_1.pack_hash == pack_2.pack_hash


def test_strategy_beats_cash_when_returns_are_positive():
    s = np.full(252, 0.001)
    a = _series(0)
    pack = build_benchmark_pack(
        s, a, strategy_id="x", primary_baseline="cash",
    )
    cash = pack.metric("cash")
    assert cash.verdict == "beats"
    assert pack.overall_verdict == "beats"


def test_strategy_fails_cash_when_returns_are_negative():
    s = np.full(252, -0.001)
    a = _series(0)
    pack = build_benchmark_pack(
        s, a, strategy_id="x", primary_baseline="cash",
    )
    assert pack.metric("cash").verdict == "fails"


def test_pack_overall_verdict_follows_primary_baseline():
    s = np.full(252, 0.001)
    a = _series(0)
    pack = build_benchmark_pack(
        s, a, strategy_id="x", primary_baseline="buy_and_hold",
    )
    assert pack.overall_verdict == pack.metric("buy_and_hold").verdict


def test_pack_unavailable_baselines_marked_unavailable():
    s = _series(0)
    a = _series(1)
    pack = build_benchmark_pack(s, a, strategy_id="x")
    assert pack.metric("sixty_forty").verdict == "unavailable"
    assert pack.metric("previous_production").verdict == "unavailable"


def test_pack_marks_sixty_forty_available_when_bond_supplied():
    s = _series(0)
    a = _series(1)
    bond = _series(2) * 0.3
    pack = build_benchmark_pack(s, a, bond_returns=bond, strategy_id="x")
    sf = pack.metric("sixty_forty")
    assert sf.available is True
    assert sf.verdict in ("beats", "ties", "fails", "inconclusive")


def test_pack_marks_previous_production_available_when_supplied():
    s = _series(0)
    a = _series(1)
    prod = _series(3)
    pack = build_benchmark_pack(s, a, production_returns=prod, strategy_id="x")
    pp = pack.metric("previous_production")
    assert pp.available is True


def test_pack_ties_when_strategy_matches_cash():
    s = np.zeros(252)
    a = _series(0)
    pack = build_benchmark_pack(
        s, a, strategy_id="x", primary_baseline="cash",
    )
    assert pack.metric("cash").verdict in ("ties", "inconclusive")


def test_pack_records_n_periods():
    s = _series(0, n=100)
    a = _series(1, n=120)
    pack = build_benchmark_pack(s, a, strategy_id="x")
    assert pack.n_periods == 100


def test_pack_invalid_primary_baseline_raises():
    s = _series(0)
    a = _series(1)
    with pytest.raises(ValueError):
        build_benchmark_pack(s, a, strategy_id="x", primary_baseline="bogus")


def test_pack_to_dict_serialises_metrics():
    s = _series(0)
    a = _series(1)
    pack = build_benchmark_pack(s, a, strategy_id="x")
    payload = pack.to_dict()
    assert payload["strategy_id"] == "x"
    assert len(payload["metrics"]) == len(required_pack_keys())
    assert all("verdict" in m for m in payload["metrics"])


def test_pack_random_baseline_is_deterministic_with_same_seed():
    a = np.linspace(0.001, 0.005, 50)
    s = np.zeros_like(a)
    p1 = build_benchmark_pack(s, a, strategy_id="x", random_seed=7)
    p2 = build_benchmark_pack(s, a, strategy_id="x", random_seed=7)
    assert p1.metric("random_comparable_turnover").annualised_return == \
        p2.metric("random_comparable_turnover").annualised_return


def test_pack_beats_method_returns_bool():
    s = np.full(252, 0.001)
    a = _series(0)
    pack = build_benchmark_pack(s, a, strategy_id="x")
    assert pack.beats("cash") is True
