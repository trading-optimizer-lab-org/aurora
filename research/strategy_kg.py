"""Strategy Knowledge Graph.

A networkx graph that stores strategies, factors, and the relationships
between them. The graph supports two question shapes:

    similar(strategy_name, k) -> list[(name, distance)]
        Walk the graph from `strategy_name` and rank other strategies by
        their shortest-path distance.

    factors_for(strategy_name) -> list[str]
        Return the factors a strategy is wired to.

The graph is intentionally simple: an undirected MultiGraph where edges
are either ``("strategy", "factor", "exposure")`` or
``("strategy", "strategy", "shares_factor")``. Edge weights are non-negative
floats, default 1.0 -- shorter weight means more similar.

This is *not* a research database. It is a navigable index over a fixed
set of strategy descriptors that the rest of the research module can use
to recommend related strategies for the auto_research_loop or zoo.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import networkx as nx


@dataclass
class StrategyNode:
    name: str
    family: str
    factors: list[str]


@dataclass
class FactorNode:
    name: str
    description: str = ""


class StrategyKnowledgeGraph:
    """Networkx-backed knowledge graph over strategies and factors."""

    def __init__(self):
        self._g: nx.MultiGraph = nx.MultiGraph()
        self._strategies: dict[str, StrategyNode] = {}
        self._factors: dict[str, FactorNode] = {}

    # -- node management ----------------------------------------------------

    def add_strategy(self, name: str, family: str, factors: Iterable[str]
                     ) -> None:
        if name in self._strategies:
            raise ValueError(f"strategy {name!r} already exists")
        node = StrategyNode(name=name, family=family, factors=list(factors))
        self._strategies[name] = node
        self._g.add_node(name, kind="strategy", family=family)
        for f in factors:
            if f not in self._factors:
                self.add_factor(f)
            self._g.add_edge(name, f, kind="exposure", weight=1.0)
        # Connect to other strategies that share factors
        for other_name, other in self._strategies.items():
            if other_name == name:
                continue
            shared = set(other.factors) & set(factors)
            if shared:
                self._g.add_edge(name, other_name, kind="shares_factor",
                                 weight=1.0 / len(shared), factors=list(shared))

    def add_factor(self, name: str, description: str = "") -> None:
        if name in self._factors:
            return
        self._factors[name] = FactorNode(name=name, description=description)
        self._g.add_node(name, kind="factor", description=description)

    # -- queries ------------------------------------------------------------

    def n_strategies(self) -> int:
        return len(self._strategies)

    def n_factors(self) -> int:
        return len(self._factors)

    def factors_for(self, name: str) -> list[str]:
        if name not in self._strategies:
            raise KeyError(f"unknown strategy: {name!r}")
        return list(self._strategies[name].factors)

    def similar(self, name: str, k: int = 5) -> list[tuple[str, float]]:
        if name not in self._strategies:
            raise KeyError(f"unknown strategy: {name!r}")
        if k < 1:
            raise ValueError("k must be >= 1")
        # Use Dijkstra to find shortest weighted distance to all strategies.
        # We walk the strategy-strategy "shares_factor" edges plus the
        # strategy-factor-strategy two-hop paths via the factor edges.
        distances: dict[str, float] = {}
        try:
            d = nx.single_source_dijkstra_path_length(self._g, name,
                                                     weight="weight")
        except nx.NodeNotFound:
            return []
        for node, dist in d.items():
            if node == name:
                continue
            if node in self._strategies:
                distances[node] = float(dist)
        ranked = sorted(distances.items(), key=lambda kv: (kv[1], kv[0]))
        return ranked[:k]

    def strategies_in_family(self, family: str) -> list[str]:
        return sorted([n for n, s in self._strategies.items()
                       if s.family == family])

    def graph(self) -> nx.MultiGraph:
        """Expose the underlying networkx graph (read-only intent)."""
        return self._g
