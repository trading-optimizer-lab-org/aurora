"""Tests for aurora.dataeng.materialized_views."""
from __future__ import annotations

import time

import pytest

from aurora.dataeng.materialized_views import (
    MVConfig,
    MaterializedViewManager,
)


def test_register_and_refresh_on_demand():
    counter = {"n": 0}

    def src() -> int:
        counter["n"] += 1
        return counter["n"]

    m = MaterializedViewManager(MVConfig(policy="on_demand"))
    m.register("v", src, lambda x: x * 10)
    assert m.refresh("v") == 10  # first call
    assert m.refresh("v") == 10  # cached, no refresh
    assert counter["n"] == 1


def test_force_triggers_refresh():
    n = {"v": 0}

    def src() -> int:
        n["v"] += 1
        return n["v"]

    m = MaterializedViewManager(MVConfig(policy="on_demand"))
    m.register("v", src, lambda x: x)
    m.refresh("v")
    m.refresh("v", force=True)
    assert n["v"] == 2


def test_ttl_policy_refreshes_after_expiry():
    n = {"v": 0}

    def src() -> int:
        n["v"] += 1
        return n["v"]

    m = MaterializedViewManager(MVConfig(policy="ttl", ttl_s=0.01))
    m.register("v", src, lambda x: x)
    m.refresh("v")
    time.sleep(0.02)
    m.refresh("v")
    assert n["v"] == 2


def test_on_change_refreshes_on_diff():
    state = {"v": [1]}

    def src() -> list:
        return list(state["v"])

    m = MaterializedViewManager(MVConfig(policy="on_change"))
    m.register("v", src, lambda x: sum(x))
    assert m.refresh("v") == 1
    state["v"] = [1, 2]
    assert m.refresh("v") == 3


def test_register_duplicate_rejected():
    m = MaterializedViewManager()
    m.register("v", lambda: 1, lambda x: x)
    with pytest.raises(ValueError):
        m.register("v", lambda: 2, lambda x: x)


def test_get_unknown_view_raises():
    m = MaterializedViewManager()
    with pytest.raises(KeyError):
        m.get("missing")


def test_names_lists_registered():
    m = MaterializedViewManager()
    m.register("a", lambda: 1, lambda x: x)
    m.register("b", lambda: 2, lambda x: x)
    assert m.names() == ["a", "b"]
