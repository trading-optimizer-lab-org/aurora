"""Data lineage tracker.

Builds a directed graph of dataset transformations. ``networkx`` is imported
lazily; when unavailable we fall back to an internal adjacency-list
representation that supports the same lookups exercised in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LineageConfig:
    """Static config for :class:`DataLineageTracker`.

    Attributes:
        prefer_networkx: try to use ``networkx`` for richer graph features.
    """
    prefer_networkx: bool = True


@dataclass
class Transformation:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    description: str = ""


class DataLineageTracker:
    """Track upstream / downstream dependencies of datasets."""

    def __init__(self, config: Optional[LineageConfig] = None) -> None:
        self.config = config or LineageConfig()
        self._fwd: dict[str, set] = {}  # node -> downstream set
        self._rev: dict[str, set] = {}  # node -> upstream set
        self._transforms: list[Transformation] = []
        self._nx_graph = None
        if self.config.prefer_networkx:
            try:
                import networkx as nx  # type: ignore
                self._nx_graph = nx.DiGraph()
            except ImportError:
                self._nx_graph = None

    # ------------------------------------------------------------------
    def add_transformation(self, t: Transformation) -> None:
        self._transforms.append(t)
        for src in t.inputs:
            self._fwd.setdefault(src, set())
            self._rev.setdefault(src, set())
        for dst in t.outputs:
            self._fwd.setdefault(dst, set())
            self._rev.setdefault(dst, set())
        for src in t.inputs:
            for dst in t.outputs:
                self._fwd[src].add(dst)
                self._rev[dst].add(src)
                if self._nx_graph is not None:
                    self._nx_graph.add_edge(src, dst, transform=t.name)

    def upstream(self, node: str) -> list[str]:
        """All ancestors of ``node`` (reverse BFS)."""
        return self._bfs(node, self._rev)

    def downstream(self, node: str) -> list[str]:
        """All descendants of ``node`` (forward BFS)."""
        return self._bfs(node, self._fwd)

    def nodes(self) -> list[str]:
        return sorted(self._fwd.keys())

    def transformations(self) -> tuple[Transformation, ...]:
        return tuple(self._transforms)

    def has_cycle(self) -> bool:
        # Kahn's algorithm: if we can't process all nodes by removing in-degree
        # zero nodes one at a time, the graph has a cycle.
        in_deg = {n: len(self._rev.get(n, set())) for n in self._fwd}
        ready = [n for n, d in in_deg.items() if d == 0]
        seen = 0
        while ready:
            n = ready.pop()
            seen += 1
            for ds in self._fwd.get(n, set()):
                in_deg[ds] -= 1
                if in_deg[ds] == 0:
                    ready.append(ds)
        return seen != len(in_deg)

    # ------------------------------------------------------------------
    def _bfs(self, start: str, adj: dict[str, set]) -> list[str]:
        if start not in adj:
            return []
        seen: set = set()
        out: list[str] = []
        stack = [start]
        while stack:
            n = stack.pop()
            for nb in adj.get(n, set()):
                if nb in seen:
                    continue
                seen.add(nb)
                out.append(nb)
                stack.append(nb)
        return sorted(out)
