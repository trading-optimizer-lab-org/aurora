"""Tests for quantforge.research.strategy_kg."""
from __future__ import annotations
import pytest

from quantforge.research.strategy_kg import StrategyKnowledgeGraph


def _populate(g: StrategyKnowledgeGraph) -> None:
    g.add_strategy("momentum_60", "momentum", ["trend", "carry"])
    g.add_strategy("momentum_120", "momentum", ["trend", "carry"])
    g.add_strategy("bollinger", "mean_rev", ["mean_reversion", "vol"])
    g.add_strategy("low_vol", "low_vol", ["vol", "carry"])


def test_add_strategy_and_query_factors():
    g = StrategyKnowledgeGraph()
    g.add_strategy("s1", "momentum", ["trend", "carry"])
    factors = g.factors_for("s1")
    assert factors == ["trend", "carry"]
    assert g.n_strategies() == 1
    assert g.n_factors() == 2


def test_duplicate_strategy_raises():
    g = StrategyKnowledgeGraph()
    g.add_strategy("s1", "momentum", ["trend"])
    with pytest.raises(ValueError):
        g.add_strategy("s1", "momentum", ["trend"])


def test_factors_for_unknown_raises():
    g = StrategyKnowledgeGraph()
    with pytest.raises(KeyError):
        g.factors_for("ghost")


def test_similar_returns_ranked_neighbors():
    g = StrategyKnowledgeGraph()
    _populate(g)
    sim = g.similar("momentum_60", k=3)
    assert len(sim) <= 3
    names = [n for n, _ in sim]
    # momentum_120 shares both factors (trend, carry) -> closer
    assert names[0] == "momentum_120"


def test_similar_unknown_raises():
    g = StrategyKnowledgeGraph()
    with pytest.raises(KeyError):
        g.similar("nope")


def test_similar_invalid_k():
    g = StrategyKnowledgeGraph()
    g.add_strategy("s", "x", ["f"])
    with pytest.raises(ValueError):
        g.similar("s", k=0)


def test_strategies_in_family():
    g = StrategyKnowledgeGraph()
    _populate(g)
    out = g.strategies_in_family("momentum")
    assert sorted(out) == ["momentum_120", "momentum_60"]


def test_graph_exposed():
    g = StrategyKnowledgeGraph()
    _populate(g)
    nxg = g.graph()
    assert "momentum_60" in nxg.nodes
    assert "trend" in nxg.nodes
