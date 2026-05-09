"""Tests for quantforge.infra.postgres_backend.PostgresRegistry (mock mode)."""
from __future__ import annotations

import pytest

from aurora.infra.postgres_backend import PostgresConfig, PostgresRegistry


@pytest.fixture
def reg() -> PostgresRegistry:
    return PostgresRegistry(PostgresConfig(), mock=True)


def _store(reg, **overrides):
    payload = dict(
        strategy_class="MACross",
        strategy_params={"fast": 10, "slow": 30},
        asset="SPY",
        period_start="2020-01-01",
        period_end="2020-12-31",
        metrics={"sharpe": 1.5, "calmar": 0.8, "mdd": -0.1},
        tags=["batch_g"],
    )
    payload.update(overrides)
    return reg.store(**payload)


def test_store_and_get(reg):
    rid = _store(reg)
    assert rid > 0
    e = reg.get(rid)
    assert e is not None
    assert e.strategy_class == "MACross"
    assert e.strategy_params == {"fast": 10, "slow": 30}
    assert e.asset == "SPY"
    assert e.metrics["sharpe"] == 1.5
    assert e.tags == ["batch_g"]


def test_store_dedup_returns_existing_id(reg):
    rid_a = _store(reg)
    rid_b = _store(reg)
    assert rid_a == rid_b
    assert reg.count() == 1


def test_query_filters(reg):
    _store(reg, asset="SPY", strategy_class="A")
    _store(reg, asset="QQQ", strategy_class="B", strategy_params={"x": 1})
    _store(reg, asset="SPY", strategy_class="C", strategy_params={"y": 2})
    spy = reg.query(asset="SPY")
    assert {e.strategy_class for e in spy} == {"A", "C"}
    a_only = reg.query(strategy_class="A")
    assert len(a_only) == 1


def test_query_tag_intersection(reg):
    _store(reg, strategy_class="X", strategy_params={"v": 1}, tags=["alpha", "beta"])
    _store(reg, strategy_class="X", strategy_params={"v": 2}, tags=["alpha"])
    out = reg.query(tags=["alpha", "beta"])
    assert len(out) == 1


def test_delete_returns_bool(reg):
    rid = _store(reg)
    assert reg.delete(rid) is True
    assert reg.delete(rid) is False
    assert reg.count() == 0


def test_get_missing_returns_none(reg):
    assert reg.get(99999) is None
