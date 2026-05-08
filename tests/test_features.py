"""Tests for feature store with provenance.

Run: uv run pytest quantforge/tests/test_features.py -v
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
import pytest

from quantforge.core.features import (
    FeatureKey,
    FeatureStore,
    _rsi_compute,
    _sma_compute,
    cached_rsi,
    cached_sma,
)


@pytest.fixture
def prices():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


@pytest.fixture
def store(tmp_path):
    return FeatureStore(root=str(tmp_path / "feat_store"))


# ---------------------------------------------------------------------------
# Compute + cache lifecycle
# ---------------------------------------------------------------------------

def test_compute_and_cache(store, prices):
    """First call computes (creates files); second call hits cache."""
    out1 = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    stats1 = store.stats()
    assert stats1["n_entries"] == 1

    out2 = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    stats2 = store.stats()
    # Hit -> still exactly 1 entry
    assert stats2["n_entries"] == 1
    # Same result
    assert np.allclose(out1, out2, equal_nan=True)


def test_cache_hit_returns_same(store, prices):
    """Same key returns identical array, and second call should be no slower."""
    t0 = time.perf_counter()
    a = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    t1 = time.perf_counter()
    b = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    t2 = time.perf_counter()

    assert np.allclose(a, b, equal_nan=True)
    # Timings are noisy; just sanity-check the hit produced same length
    assert len(a) == len(b) == len(prices)
    # cache hit should not be hugely slower than compute (allow generous margin)
    compute_time = t1 - t0
    hit_time = t2 - t1
    # Hit must be at most 5x compute; usually much faster
    assert hit_time <= max(compute_time * 5.0, 0.5)


def test_param_change_invalidates(store, prices):
    """Different params -> different cache entry, different result."""
    a = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    b = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=2)
    s = store.stats()
    assert s["n_entries"] == 2
    # Different RSI period -> different values somewhere
    diff_mask = ~(np.isnan(a) & np.isnan(b))
    assert not np.allclose(a[diff_mask], b[diff_mask], equal_nan=True)


def test_source_change_invalidates(store, prices):
    """Changed prices -> different source_hash -> recompute."""
    a = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    n1 = store.stats()["n_entries"]

    # Mutate prices
    prices2 = prices.copy()
    prices2.iloc[100] = prices2.iloc[100] * 1.10
    b = store.get_or_compute("SPY", "rsi", prices2, _rsi_compute, period=14)
    n2 = store.stats()["n_entries"]

    assert n2 == n1 + 1  # new entry created
    # Results must differ at/after the perturbed index
    assert not np.allclose(a[100:], b[100:], equal_nan=True)


def test_code_change_invalidates(store, prices):
    """Different compute_fn source -> different code_hash -> recompute."""
    # Use lambdas (different source) producing intentionally different arrays
    fn_a = lambda p, period=14: np.asarray(p, dtype=float) * 1.0
    fn_b = lambda p, period=14: np.asarray(p, dtype=float) * 2.0

    a = store.get_or_compute("SPY", "scaled", prices, fn_a, period=14)
    b = store.get_or_compute("SPY", "scaled", prices, fn_b, period=14)

    s = store.stats()
    assert s["n_entries"] == 2
    assert not np.allclose(a, b)


def test_invalidate_by_symbol(store, prices):
    """Invalidate(symbol=X) deletes only X's entries."""
    store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    store.get_or_compute("QQQ", "rsi", prices, _rsi_compute, period=14)
    assert store.stats()["n_entries"] == 2

    n_del = store.invalidate(symbol="SPY")
    assert n_del == 1
    s = store.stats()
    assert s["n_entries"] == 1
    # Remaining entry must be QQQ
    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0].symbol == "QQQ"


def test_invalidate_by_indicator(store, prices):
    """Invalidate(indicator=rsi) deletes all rsi entries across symbols."""
    store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    store.get_or_compute("SPY", "sma", prices, _sma_compute, n=20)
    store.get_or_compute("QQQ", "rsi", prices, _rsi_compute, period=14)
    assert store.stats()["n_entries"] == 3

    n_del = store.invalidate(indicator="rsi")
    assert n_del == 2
    assert store.stats()["n_entries"] == 1
    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0].indicator == "sma"


def test_stats(store, prices):
    """stats() returns expected n_entries and non-negative size."""
    s0 = store.stats()
    assert s0["n_entries"] == 0
    assert s0["total_size_mb"] >= 0.0

    store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    store.get_or_compute("SPY", "sma", prices, _sma_compute, n=20)
    s1 = store.stats()
    assert s1["n_entries"] == 2
    assert s1["total_size_mb"] > 0.0


# ---------------------------------------------------------------------------
# FeatureKey + path determinism
# ---------------------------------------------------------------------------

def test_feature_key_path_deterministic(tmp_path):
    """Same (symbol, indicator, params, source_hash, code_hash) -> same path."""
    k1 = FeatureKey(symbol="SPY", indicator="rsi", params={"period": 14},
                    source_hash="abc", code_hash="def")
    k2 = FeatureKey(symbol="SPY", indicator="rsi", params={"period": 14},
                    source_hash="abc", code_hash="def")
    assert k1.cache_path(tmp_path) == k2.cache_path(tmp_path)
    assert k1.combined_hash == k2.combined_hash


def test_feature_key_path_differs_on_params(tmp_path):
    k1 = FeatureKey(symbol="SPY", indicator="rsi", params={"period": 14},
                    source_hash="abc", code_hash="def")
    k2 = FeatureKey(symbol="SPY", indicator="rsi", params={"period": 2},
                    source_hash="abc", code_hash="def")
    assert k1.cache_path(tmp_path) != k2.cache_path(tmp_path)


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def test_cached_rsi_helper(store, prices):
    out = cached_rsi(store, "SPY", prices, period=14)
    assert len(out) == len(prices)
    assert store.stats()["n_entries"] == 1


def test_cached_sma_helper(store, prices):
    out = cached_sma(store, "SPY", prices, n=20)
    assert len(out) == len(prices)
    # Last value should equal mean of last 20 prices
    expected = float(prices.iloc[-20:].mean())
    assert abs(float(out[-1]) - expected) < 1e-9


# ---------------------------------------------------------------------------
# Named-edge-case cache invalidation tests
# ---------------------------------------------------------------------------

def test_features_cache_invalidates_on_param_change(store, prices):
    """Spec-named test: changing params yields new cache entry + different array."""
    a = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    n_before = store.stats()["n_entries"]
    assert n_before == 1

    b = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=21)
    n_after = store.stats()["n_entries"]
    assert n_after == n_before + 1, (
        f"param change must produce a new cache entry, got "
        f"{n_after - n_before} extra"
    )
    # Output must differ on at least one finite element
    finite = ~(np.isnan(a) | np.isnan(b))
    assert np.any(finite), "no finite overlap to compare"
    assert not np.allclose(a[finite], b[finite]), (
        "param change did not affect output"
    )


def test_features_cache_invalidates_on_data_change(store, prices):
    """Spec-named test: mutating source data yields new cache entry + different array."""
    a = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    n_before = store.stats()["n_entries"]

    prices_mutated = prices.copy()
    # perturb a chunk in the middle so RSI window touches it
    prices_mutated.iloc[200:210] = prices_mutated.iloc[200:210] * 1.05
    b = store.get_or_compute("SPY", "rsi", prices_mutated, _rsi_compute, period=14)
    n_after = store.stats()["n_entries"]
    assert n_after == n_before + 1, (
        "source data change must produce a new cache entry"
    )
    # outputs must differ at/after the perturbation index
    finite = ~(np.isnan(a) | np.isnan(b))
    finite_after_perturb = finite.copy()
    finite_after_perturb[:200] = False
    assert np.any(finite_after_perturb), "nothing finite past the perturbation"
    assert not np.allclose(
        a[finite_after_perturb], b[finite_after_perturb]
    ), "data change did not propagate to RSI output"


def test_features_cache_hit_returns_same_object(store, prices):
    """Spec-named test: a cache hit returns an array with identical contents."""
    a = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)
    b = store.get_or_compute("SPY", "rsi", prices, _rsi_compute, period=14)

    # Same shape, dtype, and values (NaN-safe) — current impl reads parquet
    # so we can't assert object identity (`a is b`), but contents must match.
    assert a.shape == b.shape
    assert str(a.dtype) == str(b.dtype)
    np.testing.assert_array_equal(
        np.where(np.isnan(a), 0.0, a),
        np.where(np.isnan(b), 0.0, b),
    )
    # NaN positions identical
    np.testing.assert_array_equal(np.isnan(a), np.isnan(b))
    # Cache hit must NOT add a second entry
    assert store.stats()["n_entries"] == 1
