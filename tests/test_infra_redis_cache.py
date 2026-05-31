"""Tests for aurora.infra.redis_cache.RedisCache (mock mode)."""
from __future__ import annotations

import time

import pandas as pd
import pytest

from aurora.infra.redis_cache import RedisCache, RedisCacheConfig


@pytest.fixture
def cache() -> RedisCache:
    return RedisCache(RedisCacheConfig(default_ttl=None), mock=True)


def test_get_miss_returns_none(cache):
    assert cache.get("nope") is None


def test_set_get_round_trip(cache):
    cache.set("k", b"hello")
    assert cache.get("k") == b"hello"


def test_delete_returns_bool(cache):
    cache.set("k", b"x")
    assert cache.delete("k") is True
    assert cache.delete("k") is False


def test_exists_reflects_state(cache):
    assert cache.exists("k") is False
    cache.set("k", b"v")
    assert cache.exists("k") is True


def test_ttl_expires(cache):
    cache.set("k", b"v", ttl=1)
    assert cache.get("k") == b"v"
    # Manually rewind expiry instead of sleeping.
    full = cache._key("k")
    value, _ = cache._store[full]
    cache._store[full] = (value, time.time() - 0.01)
    assert cache.get("k") is None


def test_json_helpers(cache):
    cache.set_json("payload", {"a": 1, "b": [1, 2, 3]})
    assert cache.get_json("payload") == {"a": 1, "b": [1, 2, 3]}


def test_dataframe_helpers(cache):
    df = pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]})
    cache.set_dataframe("df", df)
    out = cache.get_dataframe("df")
    assert out is not None
    pd.testing.assert_frame_equal(out, df)


def test_namespace_isolation():
    a = RedisCache(RedisCacheConfig(namespace="A"), mock=True)
    b = RedisCache(RedisCacheConfig(namespace="B"), mock=True)
    a._store = b._store = {}  # share underlying store to prove namespacing
    a.set("k", b"a-value")
    b.set("k", b"b-value")
    assert a.get("k") == b"a-value"
    assert b.get("k") == b"b-value"


def test_clear_namespace(cache):
    cache.set("a", b"1")
    cache.set("b", b"2")
    n = cache.clear_namespace()
    assert n >= 2
    assert cache.get("a") is None
