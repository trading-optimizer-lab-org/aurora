"""Strategy ancestry tree (R152).

Visualise strategy lineage: parent strategy -> variants -> archived
descendants. Builds on the existing
``research/factory/lineage.py`` graph. This module exposes a
text-rendered tree (operator-friendly via ``forge research lineage``)
and a DOT export for Graphviz.

Pure data primitive: takes a list of (parent_id, child_id, status)
edges and produces a printable representation. No factory coupling,
so it can render any provenance graph.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class AncestryEdge:
    parent_id: Optional[str]
    child_id: str
    status: str = "unknown"  # active / paused / archived / SLA-expired / suspended


def _children_index(edges: List[AncestryEdge]) -> Dict[Optional[str], List[AncestryEdge]]:
    out: Dict[Optional[str], List[AncestryEdge]] = defaultdict(list)
    for e in edges:
        out[e.parent_id].append(e)
    return out


def render_text(edges: List[AncestryEdge]) -> str:
    """Render the ancestry forest as an indented text tree."""
    children = _children_index(edges)
    lines: List[str] = []
    visited: set[str] = set()

    def _walk(node_id: str, depth: int) -> None:
        if node_id in visited:
            lines.append("  " * depth + f"- {node_id} [cycle]")
            return
        visited.add(node_id)
        # Find the status of this node from any incoming edge.
        status = ""
        for e in edges:
            if e.child_id == node_id:
                status = f" ({e.status})"
                break
        lines.append("  " * depth + f"- {node_id}{status}")
        for child in sorted(children.get(node_id, []), key=lambda x: x.child_id):
            _walk(child.child_id, depth + 1)

    # Roots: nodes that appear as child of a None parent OR never as a
    # child anywhere.
    seen_as_child: set[str] = {e.child_id for e in edges}
    seen_as_parent: set[str] = {e.parent_id for e in edges if e.parent_id}
    explicit_roots = [e.child_id for e in children.get(None, [])]
    implicit_roots = [p for p in seen_as_parent if p not in seen_as_child]
    roots = sorted(set(explicit_roots) | set(implicit_roots))
    for root in roots:
        _walk(root, depth=0)
    return "\n".join(lines)


def render_dot(edges: List[AncestryEdge]) -> str:
    """Render the ancestry as a Graphviz DOT string."""
    lines = ["digraph ancestry {"]
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box, fontname="monospace"];')
    nodes: set[str] = set()
    for e in edges:
        nodes.add(e.child_id)
        if e.parent_id:
            nodes.add(e.parent_id)
    for n in sorted(nodes):
        status = ""
        for e in edges:
            if e.child_id == n:
                status = e.status
                break
        color = {
            "active": "#2e8b57",
            "paused": "#daa520",
            "archived": "#a9a9a9",
            "sla_expired": "#cd5c5c",
            "suspended": "#8b0000",
        }.get(status, "#000000")
        lines.append(f'  "{n}" [color="{color}"];')
    for e in edges:
        if e.parent_id:
            lines.append(f'  "{e.parent_id}" -> "{e.child_id}";')
    lines.append("}")
    return "\n".join(lines)


__all__ = [
    "AncestryEdge",
    "render_text",
    "render_dot",
]
