"""Tests for StrategyBreeder GP-style crossover."""
from __future__ import annotations

import pytest

from quantforge.experimental.strategy_breeding import (
    Strategy,
    StrategyBreeder,
)


PARENT_A_SRC = """
def signal(prices):
    a = 1
    b = 2
    return a + b
"""

PARENT_B_SRC = """
def signal(prices):
    x = 100
    y = 200
    return x * y
"""


def _parent_a() -> Strategy:
    return Strategy(name="A", params={"lookback": 10, "thr": 0.5}, source=PARENT_A_SRC)


def _parent_b() -> Strategy:
    return Strategy(name="B", params={"lookback": 30, "thr": 1.5, "stop": 0.02}, source=PARENT_B_SRC)


def test_breed_produces_callable_offspring():
    breeder = StrategyBreeder(seed=0)
    child = breeder.breed(_parent_a(), _parent_b(), child_name="C")
    fn = child.compile()
    # The offspring must compile to a callable. Runtime semantics may vary
    # (statement-level GP can produce references to undefined names; that's
    # expected and is filtered downstream by an out-of-sample fitness gate).
    assert callable(fn)
    assert child.source.startswith("\ndef signal") or "def signal" in child.source


def test_breed_mixes_parameters():
    breeder = StrategyBreeder(seed=0)
    child = breeder.breed(_parent_a(), _parent_b())
    # Numeric scalar params should be the (possibly jittered) mean.
    assert child.params["lookback"] == pytest.approx(20)  # int rounding from float mean
    assert child.params["thr"] == pytest.approx(1.0)
    # A param only present on B should still survive.
    assert "stop" in child.params


def test_breed_is_seeded():
    a = StrategyBreeder(seed=42).breed(_parent_a(), _parent_b()).source
    b = StrategyBreeder(seed=42).breed(_parent_a(), _parent_b()).source
    assert a == b


def test_strategy_compile_rejects_missing_signal():
    s = Strategy(name="bad", params={}, source="def other(): return 1")
    with pytest.raises(ValueError):
        s.compile()


def test_param_jitter_changes_output():
    base = StrategyBreeder(seed=0, param_jitter=0.0).breed(_parent_a(), _parent_b()).params
    jit = StrategyBreeder(seed=0, param_jitter=0.5).breed(_parent_a(), _parent_b()).params
    # With jitter, at least one numeric scalar should differ.
    assert any(base[k] != jit[k] for k in ("lookback", "thr"))
